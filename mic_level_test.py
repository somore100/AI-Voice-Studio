import pyaudio, array, math
pa = pyaudio.PyAudio()
print("Talk now for ~3s per device...\n")
for i in range(pa.get_device_count()):
    d = pa.get_device_info_by_index(i)
    host = pa.get_host_api_info_by_index(d["hostApi"])["name"]
    if d["maxInputChannels"] < 1 or "jack" in host.lower():
        continue
    rate = int(d["defaultSampleRate"])
    try:
        s = pa.open(format=pyaudio.paInt16, channels=1, rate=rate, input=True,
                    frames_per_buffer=1024, input_device_index=i)
        frames = [s.read(1024, exception_on_overflow=False) for _ in range(int(rate / 1024 * 3))]
        s.stop_stream(); s.close()
        a = array.array("h", b"".join(frames))
        rms = math.sqrt(sum(x * x for x in a) / len(a)); peak = max(abs(x) for x in a)
        print(f"idx={i:2d} {host:5s} rms={rms:8.1f} peak={peak:6d}  {d['name']}")
    except Exception as e:
        print(f"idx={i:2d} {host:5s} FAILED: {e}  {d['name']}")
pa.terminate()
