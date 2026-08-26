# ─────────────────────────────────────────────────────────────
#  AI Voice Studio — macOS PyInstaller spec
#  Run with:  python3.12 -m PyInstaller ai_voice_studio_macos.spec
# ─────────────────────────────────────────────────────────────
import os
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

block_cipher = None

import vosk as _vosk_pkg
_vosk_dir = os.path.dirname(_vosk_pkg.__file__)

_vosk_binaries = []
for f in os.listdir(_vosk_dir):
    full = os.path.join(_vosk_dir, f)
    if f.endswith(('.dll', '.so', '.dylib')) and os.path.isfile(full):
        _vosk_binaries.append((full, 'vosk'))

_vosk_datas = [(os.path.join(_vosk_dir, f), 'vosk')
               for f in os.listdir(_vosk_dir)
               if os.path.isfile(os.path.join(_vosk_dir, f))]

try:
    _numpy_bins = collect_dynamic_libs('numpy')
    _numpy_datas = collect_data_files('numpy')
except Exception as e:
    print(f"numpy collection error: {e}")
    _numpy_bins = []
    _numpy_datas = []

try:
    _tts_datas = collect_data_files('TTS')
except Exception:
    _tts_datas = []

# ── gruut's __init__.py reads a plain VERSION text file relative to its
# own package dir at import time (_DIR / "VERSION").read_text(...) - a
# plain data-file omission, not a .py-source issue. Without this it's
# missing under PyInstaller and gruut (a TTS multilingual/text-cleaning
# dependency, reached during TTS's own import chain) fails with
# FileNotFoundError: .../gruut/VERSION
try:
    _gruut_datas = collect_data_files('gruut')
except Exception:
    _gruut_datas = []

try:
    _trainer_datas = collect_data_files('trainer')
except Exception:
    _trainer_datas = []

# ── Collect torch/torchaudio fully (binaries + datas + submodules) ──
from PyInstaller.utils.hooks import collect_all
_torch_datas, _torch_bins, _torch_hidden = collect_all('torch')
try:
    _torchaudio_datas, _torchaudio_bins, _torchaudio_hidden = collect_all('torchaudio')
except Exception:
    _torchaudio_datas, _torchaudio_bins, _torchaudio_hidden = [], [], []

# transformers lazy-loads model-specific classes (e.g. GPT2PreTrainedModel,
# used by Coqui's XTTS) by dynamic string-based import, which PyInstaller's
# static analysis can't see. collect_all forces every submodule in.
try:
    _tf_datas, _tf_bins, _tf_hidden = collect_all('transformers')
except Exception:
    _tf_datas, _tf_bins, _tf_hidden = [], [], []

_model_datas = [('models', 'models')] if os.path.isdir('models') else []

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=_vosk_binaries + _numpy_bins + _torch_bins + _torchaudio_bins + _tf_bins,
    datas=_vosk_datas + _model_datas + _tts_datas + _trainer_datas + _gruut_datas + _numpy_datas + _torch_datas + _torchaudio_datas + _tf_datas,
    hiddenimports=_torch_hidden + _torchaudio_hidden + _tf_hidden + [
        'TTS', 'TTS.api', 'TTS.tts', 'TTS.tts.configs.xtts_config',
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
        'numpy.core', 'numpy.core._multiarray_umath', 'numpy.core._multiarray_tests',
        'numpy.linalg', 'numpy.linalg._umath_linalg', 'numpy.fft', 'numpy.random',
    ],
    hookspath=[],
    runtime_hooks=['hook_vosk.py'],
    excludes=[
        # matplotlib is NOT excluded - TTS/tts/utils/visual.py imports it
        # unconditionally (already headless: matplotlib.use("Agg")), and
        # it's reached via base_tts.py, which most TTS models inherit
        # from - excluding it breaks core TTS imports, not just plotting.
        'IPython', 'jupyter', 'notebook',
        'cv2', 'tensorflow', 'keras',  # PIL removed - matplotlib requires it (pillow>=9 is a hard matplotlib dependency)
        'pytest',
    ],
    cipher=block_cipher,
    noarchive=False,
    # 'inflect' (pulled in via TTS's text-cleaning pipeline) decorates
    # its engine class with @typeguard.typechecked, which calls
    # inspect.getsource() on itself at import time. PyInstaller's default
    # bytecode-only-in-archive collection has no real source file for that
    # to read, causing 'OSError: could not get source code'. Forcing 'py'
    # collection mode makes PyInstaller keep/collect inflect as real loose
    # .py source instead, which inspect.getsource() can read normally.
    module_collection_mode={'inflect': 'py'},
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
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
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

# BUNDLE wraps the COLLECT output into a proper macOS .app
app = BUNDLE(
    coll,
    name='AI Voice Studio.app',
    icon=None,   # add 'logo.icns' here once a proper .icns icon exists
    bundle_identifier='com.domore100.aivoicestudio',
    info_plist={
        'NSMicrophoneUsageDescription': 'AI Voice Studio needs microphone access for Speech-to-Text.',
        'CFBundleShortVersionString': '1.0.0',
    },
)
