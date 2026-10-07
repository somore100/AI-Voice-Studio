#!/usr/bin/env python3
"""In-place patch for main.py (run AFTER patch_mic_resolve.py, from project root):
  python3 patch_mic_default.py [path/to/main.py]
1. "System Default" now prefers the PipeWire/Pulse session device (follows the
   desktop's selected source and mute) instead of the raw ALSA hw: jack input.
2. The dropdown defaults to "System Default" whenever such a device exists.
3. _open_mic measures ~0.5s of input on open, logs rms/peak, and raises a clear
   error if the stream is digital silence (muted / wrong input).
"""
import sys, shutil, pathlib

path = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "main.py")
src = path.read_text()
orig = src

def sub(old, new, count=1):
    global src
    n = src.count(old)
    assert n == count, f"expected {count} match(es), found {n} for:\n{old[:120]!r}"
    src = src.replace(old, new)

# 1) safe_default_input_index: session devices first, then PortAudio default
sub('''    try:
        d = pa.get_default_input_device_info()
        if not _pa_is_jack(pa, d):
            return d["index"]
    except Exception:
        pass
    cands = []
    for i in range(pa.get_device_count()):
        d = pa.get_device_info_by_index(i)
        if d.get("maxInputChannels", 0) > 0 and not _pa_is_jack(pa, d):
            cands.append((i, d["name"].lower()))
    for key in ("pipewire", "pulse", "default"):
        for i, n in cands:
            if key in n:
                return i
''',
'''    cands = []
    for i in range(pa.get_device_count()):
        d = pa.get_device_info_by_index(i)
        if d.get("maxInputChannels", 0) > 0 and not _pa_is_jack(pa, d):
            cands.append((i, d["name"].lower()))
    # Session-level devices follow the desktop's chosen source AND its mute
    # state; raw hw: devices (e.g. an unplugged headphone-jack input) don't.
    for key in ("pipewire", "pulse"):
        for i, n in cands:
            if n == key:
                return i
    try:
        d = pa.get_default_input_device_info()
        if not _pa_is_jack(pa, d):
            return d["index"]
    except Exception:
        pass
    for i, n in cands:
        if n == "default":
            return i
''')

# 2) dropdown default
sub('''        default_display = self.mics_display[best_idx + 1] if self.mics else self.mics_display[0]''',
'''        _has_session = any(n.lower() in ("pipewire", "pulse") for n in self.mics)
        if self.mics and not _has_session:
            default_display = self.mics_display[best_idx + 1]
        else:
            default_display = self.mics_display[0]   # "System Default"''')

# 3) level probe helper, before check_mic_access()
sub('''def check_mic_access():
    """Actually try to open the default input device.''',
'''def _probe_mic_level(source, skip=0.2, measure=0.5):
    """Read ~0.7s from an open sr.Microphone; return (rms, peak) of the last 0.5s."""
    import array, math
    per = source.CHUNK / float(source.SAMPLE_RATE)
    for _ in range(max(1, int(skip / per))):
        source.stream.read(source.CHUNK)
    buf = b"".join(source.stream.read(source.CHUNK)
                   for _ in range(max(1, int(measure / per))))
    a = array.array("h")
    a.frombytes(buf[: len(buf) - (len(buf) % 2)])
    if not a:
        return 0.0, 0
    return math.sqrt(sum(x * x for x in a) / len(a)), max(abs(x) for x in a)

def check_mic_access():
    """Actually try to open the default input device.''')

sub('''            yield source
        finally:
            if source.stream is not None:''',
'''            _rms, _peak = _probe_mic_level(source)
            print(f"[AVS] mic level: rms={_rms:.0f} peak={_peak}", flush=True)
            if _peak <= 1:
                raise RuntimeError(
                    "This microphone is delivering pure silence. It is "
                    "probably muted (check your keyboard's mic-mute key and "
                    "the system sound settings) or the wrong input is "
                    "selected. Unmute it or pick another microphone from "
                    "the dropdown.")
            yield source
        finally:
            if source.stream is not None:''')

assert src != orig
compile(src, str(path), "exec")
shutil.copy2(path, path.with_suffix(".py.pre_default"))
path.write_text(src)
print("PATCHED OK; syntax OK; backup:", path.with_suffix(".py.pre_default"))
