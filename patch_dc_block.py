#!/usr/bin/env python3
"""In-place patch for main.py (run from project root, after the two earlier patches):
  python3 patch_dc_block.py [path/to/main.py]
Wraps the mic stream in a DC-blocking filter so speech_recognition's energy
detector sees the voice instead of a constant offset (the Acer/AMD ACP digital
mic delivers a ~5000-13000 DC offset plus a ~0.5s startup transient). Also
lengthens the open-time probe so the filter settles before listening starts.
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

sub('''def _probe_mic_level(source, skip=0.2, measure=0.5):''',
'''class _DCBlockStream:
    """Proxy for sr.Microphone.stream: subtracts a slowly tracked DC offset.

    SpeechRecognition's energy detector uses the RMS of the raw samples, so a
    constant offset (e.g. 9500) swamps speech and no phrase is ever detected.
    A per-chunk exponential mean estimate removes the offset (and its slow
    drift) while leaving speech untouched. Harmless on mics with no offset.
    """
    def __init__(self, inner, alpha=0.1):
        self._inner = inner
        self._alpha = alpha
        self._dc = None

    def read(self, size):
        import numpy as np
        data = self._inner.read(size)
        a = np.frombuffer(data[: len(data) - (len(data) % 2)], dtype=np.int16)
        if a.size == 0:
            return data
        m = float(a.mean())
        self._dc = m if self._dc is None else (1 - self._alpha) * self._dc + self._alpha * m
        out = np.clip(a.astype(np.float32) - self._dc, -32768, 32767).astype(np.int16)
        return out.tobytes()

    def __getattr__(self, name):          # close(), pyaudio_stream, ...
        return getattr(self._inner, name)

def _probe_mic_level(source, skip=0.2, measure=0.5):''')

sub('''            _rms, _peak = _probe_mic_level(source)
            print(f"[AVS] mic level: rms={_rms:.0f} peak={_peak}", flush=True)''',
'''            try:
                import numpy  # noqa: F401
                source.stream = _DCBlockStream(source.stream)
            except Exception as e:
                print(f"[AVS] DC filter unavailable ({e}); continuing without", flush=True)
            # 0.6s skip lets the mic's startup transient pass and the DC estimate settle
            _rms, _peak = _probe_mic_level(source, skip=0.6, measure=0.3)
            _dc = getattr(source.stream, "_dc", None)
            print(f"[AVS] mic level (DC removed): rms={_rms:.0f} peak={_peak}"
                  + (f" dc={_dc:.0f}" if _dc is not None else ""), flush=True)''')

assert src != orig
compile(src, str(path), "exec")
shutil.copy2(path, path.with_suffix(".py.pre_dc"))
path.write_text(src)
print("PATCHED OK; syntax OK; backup:", path.with_suffix(".py.pre_dc"))
