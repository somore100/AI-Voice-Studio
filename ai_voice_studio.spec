# ─────────────────────────────────────────────────────────────
#  AI Voice Studio — PyInstaller spec file
#  Run with:  py -3.10 -m PyInstaller ai_voice_studio.spec
# ─────────────────────────────────────────────────────────────
import sys, os
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

# Read console preference set by build_exe.bat
_show_console = os.environ.get("AVS_CONSOLE", "0") == "1"

block_cipher = None

# ── Find vosk package directory so we can bundle its DLLs ────
import vosk as _vosk_pkg
_vosk_dir = os.path.dirname(_vosk_pkg.__file__)

# ── Collect vosk DLLs and data files ─────────────────────────
_vosk_binaries = []
for f in os.listdir(_vosk_dir):
    full = os.path.join(_vosk_dir, f)
    if f.endswith(('.dll', '.so', '.dylib')) and os.path.isfile(full):
        _vosk_binaries.append((full, 'vosk'))

# Also bundle the entire vosk package folder as data
# (vosk.__init__ does os.add_dll_directory on its own folder)
_vosk_datas = [(os.path.join(_vosk_dir, f), 'vosk')
               for f in os.listdir(_vosk_dir)
               if os.path.isfile(os.path.join(_vosk_dir, f))]

# ── Collect numpy DLLs (fixes Windows DLL load error) ───────
try:
    from PyInstaller.utils.hooks import collect_dynamic_libs
    _numpy_bins = collect_dynamic_libs('numpy')
except Exception:
    _numpy_bins = []

# ── Collect TTS data files ───────────────────────────────────
try:
    from PyInstaller.utils.hooks import collect_data_files
    _tts_datas = collect_data_files('TTS')
except Exception:
    _tts_datas = []

# ── Collect trainer data files ───────────────────────────────
try:
    _trainer_datas = collect_data_files('trainer')
except Exception:
    _trainer_datas = []

# ── Models folder (optional) ─────────────────────────────────
_model_datas = [('models', 'models')] if os.path.isdir('models') else []

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=_vosk_binaries + _numpy_bins,
    datas=_vosk_datas + _model_datas + _tts_datas + _trainer_datas,
    hiddenimports=[
        'TTS', 'TTS.api', 'TTS.tts', 'TTS.tts.configs.xtts_config',
        'TTS.tts.configs', 'TTS.tts.models', 'TTS.tts.utils',
        'TTS.tts.layers', 'TTS.utils.audio', 'TTS.utils.io',
        'TTS.config', 'TTS.encoder', 'TTS.vocoder',
        'coqpit', 'trainer',
        'TTS.tts.configs', 'TTS.tts.models', 'TTS.tts.utils',
        'TTS.tts.layers', 'TTS.utils.audio', 'TTS.utils.io',
        'TTS.config', 'TTS.encoder', 'TTS.vocoder',
        'coqpit', 'trainer',
        'TTS.tts.models.xtts', 'TTS.utils', 'TTS.vocoder',
        'whisper', 'whisper.audio', 'whisper.decoding',
        'whisper.model', 'whisper.tokenizer', 'whisper.transcribe',
        'vosk',
        'speech_recognition', 'pyaudio', 'pygame', 'pygame.mixer',
        'torch', 'torchaudio',
        'numpy', 'librosa', 'scipy', 'sklearn',
        'tkinter', 'tkinter.ttk', 'tkinter.filedialog', 'tkinter.messagebox',
        'backports', 'backports.tarfile', 'jaraco', 'jaraco.text', 'jaraco.context', 'jaraco.functools',
    ],
    hookspath=[],
    runtime_hooks=['hook_vosk.py'],
    excludes=[
        'matplotlib', 'IPython', 'jupyter', 'notebook',
        'PIL', 'cv2', 'tensorflow', 'keras',
        'pytest', 'unittest',
    ],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AI_Voice_Studio',
    debug=False,
    strip=False,
    upx=False,
    console=_show_console,
    disable_windowed_traceback=False,
    target_arch=None,
    icon='logo.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='AI_Voice_Studio',
)
