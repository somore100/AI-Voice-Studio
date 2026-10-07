import pyaudio, array, math, time
pa = pyaudio.PyAudio()
idx = next(i for i in range(pa.get_device_count()) if pa.get_device_info_by_index(i)["name"] == "pipewire")
rate = int(pa.get_device_info_by_index(idx)["defaultSampleRate"])
def grab(label, secs=3):
    print(f"{label} for {secs}s...", flush=True)
    s = pa.open(format=pyaudio.paInt16, channels=1, rate=rate, input=True,
                frames_per_buffer=1024, input_device_index=idx)
    buf = b"".join(s.read(1024, exception_on_overflow=False) for _ in range(int(rate / 1024 * secs)))
    s.stop_stream(); s.close()
    a = array.array("h"); a.frombytes(buf)
    mean = sum(a) / len(a)
    ac = math.sqrt(sum((x - mean) ** 2 for x in a) / len(a))
    print(f"  {label}: dc_mean={mean:8.1f} ac_rms={ac:8.1f} peak={max(abs(x) for x in a)}")
grab("STAY SILENT"); time.sleep(1); grab("TALK NORMALLY")
pa.terminate()
