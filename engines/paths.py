"""Where third-party TTS libraries actually store their downloaded models.

This is deliberately separate from main.py's own app-data paths
(_MODELS_BASE etc.) - it's specifically about where *other libraries*
(Coqui TTS today; whatever Piper/Kokoro/etc. use, later) put things on
disk by their own convention, which our own app-data folder has no
control over.
"""
import os
import sys


def get_tts_cache_dir():
    """Return the directory Coqui TTS actually downloads models into.

    Mirrors trainer.io.get_user_data_dir("tts") exactly (the function
    TTS/utils/manage.py itself calls internally), so our "is this model
    already downloaded?" checks always look in the same place TTS put
    it. A prior version of this guessed from the Windows-only
    LOCALAPPDATA env var, which is empty on Linux/macOS, so downloaded
    models were never found by the status check even after a successful
    download.
    """
    try:
        from trainer.io import get_user_data_dir
        return str(get_user_data_dir("tts"))
    except Exception:
        # Fallback: reimplement the same platform logic trainer.io uses,
        # in case the trainer package isn't importable yet.
        tts_home = os.environ.get("TTS_HOME")
        xdg_home = os.environ.get("XDG_DATA_HOME")
        if tts_home:
            base = os.path.expanduser(tts_home)
        elif xdg_home:
            base = os.path.expanduser(xdg_home)
        elif sys.platform == "win32":
            base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        elif sys.platform == "darwin":
            base = os.path.expanduser("~/Library/Application Support")
        else:
            base = os.path.expanduser("~/.local/share")
        return os.path.join(base, "tts")
