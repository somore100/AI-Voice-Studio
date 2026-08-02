# hook_vosk.py — PyInstaller runtime hook for Vosk
# Vosk's __init__.py calls os.add_dll_directory() on its own folder.
# Inside a PyInstaller bundle the folder is in _internal\vosk\
# This hook patches the path before vosk loads so it finds its DLLs.
#
# os.add_dll_directory() is Windows-only (added in Python 3.8 on win32).
# On Linux/macOS it doesn't exist at all, so calling it unconditionally
# crashes a frozen Linux/macOS build with:
#   AttributeError: module 'os' has no attribute 'add_dll_directory'

import os
import sys

if sys.platform == "win32" and hasattr(sys, '_MEIPASS'):
    vosk_path = os.path.join(sys._MEIPASS, 'vosk')
    if os.path.isdir(vosk_path):
        os.add_dll_directory(vosk_path)
