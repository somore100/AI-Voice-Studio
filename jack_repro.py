import sys, pyaudio
mode = sys.argv[1]
pa = pyaudio.PyAudio()
def api(d): return pa.get_host_api_info_by_index(d["hostApi"])["name"]
if mode == "default":
    for i in range(pa.get_host_api_count()):
        h = pa.get_host_api_info_by_index(i)
        print("HOSTAPI", i, h["name"], "devices:", h["deviceCount"], "default_in:", h["defaultInputDevice"])
    print("DEFAULT HOST API:", pa.get_default_host_api_info()["name"])
    for i in range(pa.get_device_count()):
        d = pa.get_device_info_by_index(i)
        if d["maxInputChannels"] > 0:
            print("INPUT", i, api(d), "|", d["name"], "|", d["defaultSampleRate"])
idx = None
if mode == "alsa":
    cands = []
    for i in range(pa.get_device_count()):
        d = pa.get_device_info_by_index(i)
        if d["maxInputChannels"] > 0 and "ALSA" in api(d):
            cands.append((i, d["name"]))
    for key in ("pipewire", "pulse", "default"):
        hit = [c for c in cands if key in c[1].lower()]
        if hit:
            idx = hit[0][0]; break
    if idx is None and cands: idx = cands[0][0]
    print("ALSA PICK:", idx, [c for c in cands if c[0] == idx])
info = pa.get_device_info_by_index(idx) if idx is not None else pa.get_default_input_device_info()
print("OPENING:", info["index"], api(info), info["name"])
s = pa.open(format=pyaudio.paInt16, channels=1, rate=int(info["defaultSampleRate"]), input=True, input_device_index=info["index"], frames_per_buffer=1024)
for _ in range(40): s.read(1024, exception_on_overflow=False)
s.stop_stream(); s.close(); pa.terminate()
print("DONE", mode)
