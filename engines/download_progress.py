"""Shared byte-level download progress hook for Coqui-based engines.

Coqui's TTS.utils.manage._download_zip_file (used by both the
github-release and huggingface download paths - i.e. both VCTK and
XTTS-v2 go through this one function) drives its progress purely
through a plain `tqdm` instance, constructed only when progress_bar=True
is passed all the way down from TTS(...). There's no callback parameter
exposed anywhere in that call chain - the download happens several
layers below the TTS() constructor call, with no hook point passed
through. The only way to observe real byte progress without
reimplementing Coqui's entire download+extract+hash-check logic
ourselves is to temporarily swap out the `tqdm` name that module looks
up (as a bare global, at call time - not captured at import time) for
our own subclass that also forwards progress to a caller-supplied
callback, then restore the original afterward.

Usage:
    def on_progress(downloaded_bytes, total_bytes):
        ...  # called from the SAME thread the download runs on -
             # marshal to the main thread (e.g. tkinter's root.after())
             # before touching any widget from here.

    with progress_hook(on_progress):
        TTS(model_name=..., progress_bar=True, gpu=False)

Callback frequency is throttled internally (roughly every 0.5% of the
total, or every 256KB for unknown-size downloads) so this stays cheap
even for XTTS's ~1.8GB file, which would otherwise fire the callback
on every single 1KB chunk Coqui reads - well over a million calls.
"""
import contextlib
import io


@contextlib.contextmanager
def progress_hook(callback):
    import TTS.utils.manage as _manage
    from tqdm import tqdm as _real_tqdm

    class _CallbackTqdm(_real_tqdm):
        def __init__(self, *args, **kwargs):
            # Swallow tqdm's own console output (the \r-based bar) -
            # we only want the numbers, not the terminal spam. Also
            # matters for packaged builds with no real stdout/terminal.
            kwargs.setdefault("file", io.StringIO())
            super().__init__(*args, **kwargs)
            self._last_reported = 0

        def update(self, n=1):
            super().update(n)
            if not callback:
                return
            total = self.total or 0
            step = max(int(total * 0.005), 256 * 1024) if total else 256 * 1024
            # "final" only makes sense when we actually know the total -
            # for unknown-size downloads (total=0), self.n >= total would
            # be true on every single call and defeat the step throttle
            # entirely, firing the callback on every ~1KB chunk instead
            # of every ~256KB.
            is_final = total > 0 and self.n >= total
            if self.n - self._last_reported >= step or is_final:
                self._last_reported = self.n
                try:
                    callback(self.n, total)
                except Exception:
                    pass

    original = _manage.tqdm
    _manage.tqdm = _CallbackTqdm
    try:
        yield
    finally:
        _manage.tqdm = original
