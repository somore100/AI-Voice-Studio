#!/usr/bin/env python3
"""In-place patch for main.py: name-based mic resolution + guarded cleanup.

Run from the project root:  python3 patch_mic_resolve.py [path/to/main.py]
Every edit asserts an exact expected match count before anything is written.
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

# 1) resolve_input_index() helper, placed right before check_mic_access()
sub('''def check_mic_access():
    """Actually try to open the default input device.''',
'''def resolve_input_index(pa, mic):
    """Resolve a mic selection to a CURRENT non-JACK PortAudio index.

    `mic` is None (system default), a (pa_index, name) tuple as stored in
    mics_real, a bare int, or a bare name. The stored index is only trusted
    if the device at that index still has the same name; otherwise we look
    the name up again (PortAudio indices shift between enumerations).
    Returns (index, name). Raises RuntimeError if the device is gone.
    """
    def _ok(i):
        d = pa.get_device_info_by_index(i)
        return d.get("maxInputChannels", 0) > 0 and not _pa_is_jack(pa, d)

    if mic is None:
        i = safe_default_input_index(pa)
        return i, pa.get_device_info_by_index(i)["name"]

    if isinstance(mic, tuple):
        idx, name = mic
    elif isinstance(mic, int):
        idx, name = mic, None
    else:
        idx, name = None, str(mic)

    n = pa.get_device_count()
    if idx is not None and 0 <= idx < n and _ok(idx):
        d = pa.get_device_info_by_index(idx)
        if name is None or d["name"] == name:
            return idx, d["name"]
    if name is not None:
        for i in range(n):
            if _ok(i) and pa.get_device_info_by_index(i)["name"] == name:
                return i, name
    raise RuntimeError(
        f"The selected microphone ({name or idx}) is no longer available. "
        "Pick a microphone from the dropdown again (or use System Default).")

def check_mic_access():
    """Actually try to open the default input device.''')

# 2) mics_real now holds (index, name) tuples so the index can be re-verified
sub('self.mics_real = [None] + self._mic_pa_indices',
    'self.mics_real = [None] + list(_pairs)   # (pa_index, name) tuples')

# 3) _open_mic: resolve by name at open time, log, wrap setup errors
sub('''        if mic_index is None:
            try:
                import pyaudio as _pyaudio
                _p = _pyaudio.PyAudio()
                try:
                    mic_index = safe_default_input_index(_p)
                finally:
                    _p.terminate()
            except Exception:
                mic_index = None
        source = sr.Microphone(device_index=mic_index)
        source.__enter__()
''',
'''        import pyaudio as _pyaudio
        _p = _pyaudio.PyAudio()
        try:
            try:
                mic_index, _nm = resolve_input_index(_p, mic_index)
            except RuntimeError:
                raise
            except Exception as e:
                raise RuntimeError(f"Could not find a usable input device: {e}") from e
            _d = _p.get_device_info_by_index(mic_index)
            _h = _p.get_host_api_info_by_index(_d["hostApi"])["name"]
            print(f"[AVS] mic open: idx={mic_index} name={_nm!r} host={_h} "
                  f"rate={_d.get('defaultSampleRate')}", flush=True)
        finally:
            _p.terminate()
        try:
            source = sr.Microphone(device_index=mic_index)
        except Exception as e:
            raise RuntimeError(f"Could not open microphone: {e}") from e
        source.__enter__()
''')

sub('''                    "picking a different microphone from the dropdown."
                )''',
'''                    "picking a different microphone from the dropdown. "
                    "(PortAudio details are printed in the terminal.)"
                )''')

# 4) guarded __exit__ so a closed PortAudio stream can't mask the real error
sub('''            if source.stream is not None:
                source.__exit__(None, None, None)
            else:''',
'''            if source.stream is not None:
                try:
                    source.__exit__(None, None, None)
                except Exception as e:
                    print(f"[AVS] mic close error (ignored): {e}", flush=True)
            else:''')

# 5) STT loops: a dead stream must stop the loop, not spin on a swallowed error
sub('''                        except Exception:
                            self.root.after(0, lambda: self.live_word_var.set(""))''',
'''                        except OSError:
                            raise   # PortAudio stream died - surface it, don't spin
                        except Exception:
                            self.root.after(0, lambda: self.live_word_var.set(""))''',
    count=2)

# 6) STT loops: show OSError from the mic as a clear dialog too
sub('''            except RuntimeError as e:
                self.root.after(0, lambda err=str(e): messagebox.showerror("Microphone Error", err))''',
'''            except (RuntimeError, OSError) as e:
                print(f"[AVS] STT mic error: {e!r}", flush=True)
                _m = str(e) if isinstance(e, RuntimeError) else f"The microphone stream failed: {e}"
                self.root.after(0, lambda err=_m: messagebox.showerror("Microphone Error", err))''',
    count=2)

assert src != orig
compile(src, str(path), "exec")
bak = path.with_suffix(".py.pre_resolve")
shutil.copy2(path, bak)
path.write_text(src)
print("PATCHED OK; syntax OK; backup:", bak)
