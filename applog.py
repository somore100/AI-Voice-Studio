"""Copies everything the app prints (stdout + stderr) into a log file with
timestamps, so background / autostarted runs, which have no terminal, can still
be diagnosed. Standard library only, reusable.

    import applog
    applog.setup("/path/to/app.log")
"""
import os
import sys
import time

MAX_BYTES = 1_000_000


class _Tee:
    def __init__(self, orig, fh):
        self._orig, self._fh, self._bol = orig, fh, True

    def write(self, s):
        if self._orig is not None:
            try:
                self._orig.write(s)
            except Exception:
                pass
        try:
            for part in s.splitlines(True):
                if self._bol:
                    self._fh.write(time.strftime("[%Y-%m-%d %H:%M:%S] "))
                self._fh.write(part)
                self._bol = part.endswith("\n")
            self._fh.flush()
        except Exception:
            pass
        return len(s)

    def flush(self):
        for t in (self._orig, self._fh):
            try:
                if t is not None:
                    t.flush()
            except Exception:
                pass

    def isatty(self):
        return bool(self._orig is not None and self._orig.isatty())

    def __getattr__(self, name):             # encoding, fileno, ...
        if self._orig is not None:
            return getattr(self._orig, name)
        raise AttributeError(name)


def setup(path, max_bytes=MAX_BYTES):
    """Start logging to `path` (the previous log is kept once as path + '.1').
    Returns the path, or None if the file cannot be opened."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path) and os.path.getsize(path) > max_bytes:
            os.replace(path, path + ".1")
        fh = open(path, "a", encoding="utf-8", errors="replace")
    except OSError:
        return None
    fh.write(f"\n===== started {time.strftime('%Y-%m-%d %H:%M:%S')} "
             f"(pid {os.getpid()}, args: {' '.join(sys.argv[1:]) or '-'}) =====\n")
    sys.stdout = _Tee(sys.stdout, fh)
    sys.stderr = _Tee(sys.stderr, fh)
    return path
