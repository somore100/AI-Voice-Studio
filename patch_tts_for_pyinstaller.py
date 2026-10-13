"""
patch_tts_for_pyinstaller.py
=============================
Run this ONCE, right after installing dependencies and BEFORE running
PyInstaller, on every platform (Windows/Linux/macOS CI jobs and local
dev builds).

Why this exists
----------------
TTS/vocoder/configs/__init__.py auto-discovers its config classes at
import time by doing:

    configs_dir = os.path.dirname(__file__)
    for file in os.listdir(configs_dir):
        ...

That works fine in a normal pip install (real files on disk), but
breaks under PyInstaller: this __init__.py gets compiled into the
frozen app's archive, and os.path.dirname(__file__) does not resolve
to a real, listable directory at runtime. The result is:

    FileNotFoundError: [Errno 2] No such file or directory:
    '.../_internal/TTS/vocoder/configs'

coqui-tts's own maintainers already hit this exact problem and fixed
it for the sibling file, TTS/tts/configs/__init__.py, by commenting
out the identical auto-discovery block (see
https://github.com/coqui-ai/TTS/issues/2802). They never applied the
same fix to TTS/vocoder/configs/__init__.py. Nothing in the TTS
codebase actually relies on the dynamic re-export this produces
(TTS.vocoder.configs.SomeConfig) - every real usage imports directly
from the specific submodule, e.g.:
    from TTS.vocoder.configs.hifigan_config import HifiganConfig
so disabling it is safe - it's exactly what upstream already proved
for tts/configs.

This script finds the installed TTS package and replaces
vocoder/configs/__init__.py with a no-op stub (matching upstream's
approach), removing the crash at its source instead of fighting
PyInstaller's data-packing behavior.
"""
import os
import sys

try:
    import TTS
except ImportError:
    print("[patch_tts_for_pyinstaller] TTS is not installed - nothing to patch.")
    sys.exit(0)

target = os.path.join(os.path.dirname(TTS.__file__), "vocoder", "configs", "__init__.py")

if not os.path.isfile(target):
    print(f"[patch_tts_for_pyinstaller] Expected file not found: {target}")
    sys.exit(1)

with open(target, "r", encoding="utf-8") as f:
    original = f.read()

if "os.listdir(configs_dir)" not in original:
    print("[patch_tts_for_pyinstaller] Already patched (or upstream changed) - leaving as-is.")
    sys.exit(0)

patched = '''"""Vocoder configs subpackage.

The upstream dynamic os.listdir-based auto-import here was disabled by
patch_tts_for_pyinstaller.py (see that script for the full explanation).
It mirrors what coqui-tts's own maintainers already did for the sibling
TTS/tts/configs/__init__.py (https://github.com/coqui-ai/TTS/issues/2802).
Nothing in the codebase imports classes via TTS.vocoder.configs.<ClassName>
- everything imports directly from the specific submodule - so this has
no effect on behavior, only on PyInstaller compatibility.
"""
'''

with open(target, "w", encoding="utf-8") as f:
    f.write(patched)

print(f"[patch_tts_for_pyinstaller] Patched: {target}")
