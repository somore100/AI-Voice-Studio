"""One-time move of data from the app's old name ("AI Voice Studio") to Audiovane.

Standard library only. Nothing is deleted: the old folder is renamed, so the models
(hundreds of MB) and the settings, API key and log all carry over.
"""
import os

OLD_NAME = "AI Voice Studio"
OLD_ID = "ai-voice-studio"


def migrate_dir(new_path, old_name=OLD_NAME):
    """If `new_path` does not exist yet but a sibling folder named `old_name` does,
    rename it to `new_path`. Returns `new_path` either way (never raises)."""
    old = os.path.join(os.path.dirname(new_path), old_name)
    try:
        if not os.path.exists(new_path) and os.path.isdir(old):
            os.replace(old, new_path)
    except OSError:
        pass
    return new_path
