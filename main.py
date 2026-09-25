import os
import sys
import tkinter as tk
from tkinter import messagebox, ttk, filedialog
import threading
import random
import tempfile
import time
import urllib.request
import urllib.parse
import json
import traceback
import speech_recognition as sr
import pygame
from contextlib import contextmanager

# ──────────────────────────────────────────────────────────────
#  EAGER TORCH IMPORT (must happen on the main thread, before any
#  background threads exist)
# ──────────────────────────────────────────────────────────────
# torch is only ever imported lazily elsewhere in this file (inside
# functions, when actually needed for TTS/whisper work). But several
# background threads (e.g. the startup model-check thread) end up being
# the FIRST thing to trigger `import torch` if we don't force it here.
# Under PyInstaller's frozen import machinery, a nested submodule import
# of torch racing across threads can leave torch partially initialized
# in one thread's view, crashing with:
#   AttributeError: partially initialized module 'torch' has no
#   attribute 'autograd' (most likely due to a circular import)
# Importing torch once here, synchronously, on the main thread, before
# any thread is spawned, guarantees it's fully cached in sys.modules
# first — every later `import torch` anywhere is then just a cheap
# dict lookup, not real module execution, so there's nothing left to race.
try:
    import torch          # noqa: F401
    import torch.autograd  # noqa: F401
except Exception as _e:
    print(f"[AVS] Warning: eager torch import failed: {_e}")

# ──────────────────────────────────────────────────────────────
#  EAGER TTS IMPORT (same reasoning as torch above)
# ──────────────────────────────────────────────────────────────
# TTS was never imported at module scope anywhere in this file — every
# `from TTS.api import TTS` lives inside the engines/coqui_vctk.py and
# engines/coqui_xtts.py modules' download()/_get_instance() functions,
# and every one of those only ever runs on a background thread
# (Preview/Save/download all use threading.Thread).
# So the very first import of TTS under PyInstaller's frozen importer
# happened on a background thread, hitting the same class of race as
# the torch bug above — except for TTS it surfaces as:
#   KeyError: 'TTS'
# raised from importlib._bootstrap_external._get_parent_path(), because
# TTS's own _NamespacePath machinery does sys.modules['TTS'] mid-import
# and finds it not yet registered. Importing it here, synchronously, on
# the main thread before any thread exists, fixes it the same way.
try:
    import TTS              # noqa: F401
    from TTS.api import TTS as _TTS_api  # noqa: F401
except Exception as _e:
    print(f"[AVS] Warning: eager TTS import failed: {_e}")

# ──────────────────────────────────────────────────────────────
#  PERSISTENT CONFIG
# ──────────────────────────────────────────────────────────────
LAST_FOLDER     = r"C:/Users/Dominik Žibert/Documents/ai_voice/audio"  # auto-updates on browse
SAVED_FAVORITES = ['Adam', 'Emma', 'Ivy']  # auto-updates when you star/unstar voices

# ──────────────────────────────────────────────────────────────
#  MODEL PATHS
# ──────────────────────────────────────────────────────────────
if getattr(sys, 'frozen', False):
    _BASE = os.path.dirname(sys.executable)
else:
    _BASE = os.path.dirname(os.path.realpath(__file__))

def _user_data_dir():
    """Cross-platform writable location for models/config when running frozen.
    Windows: %APPDATA%\\AI Voice Studio
    macOS:   ~/Library/Application Support/AI Voice Studio
    Linux:   $XDG_DATA_HOME/AI Voice Studio  (falls back to ~/.local/share)
    This matters because a frozen build's own folder can be read-only
    (Program Files without admin, a mounted AppImage, a signed .app bundle)."""
    if sys.platform == "win32":
        base = os.environ.get('APPDATA') or os.path.expanduser('~')
        return os.path.join(base, 'AI Voice Studio')
    elif sys.platform == "darwin":
        return os.path.expanduser('~/Library/Application Support/AI Voice Studio')
    else:
        base = os.environ.get('XDG_DATA_HOME') or os.path.expanduser('~/.local/share')
        return os.path.join(base, 'AI Voice Studio')

if getattr(sys, 'frozen', False):
    _MODELS_BASE = os.path.join(_user_data_dir(), 'models')
else:
    _MODELS_BASE = os.path.join(_BASE, 'models')
os.makedirs(_MODELS_BASE, exist_ok=True)

# Set espeak path if bundled with app (Windows installer bundles it)
_ESPEAK_PATH = os.path.join(_BASE, "espeak")
if os.path.isdir(_ESPEAK_PATH):
    os.environ["PHONEMIZER_ESPEAK_PATH"] = _ESPEAK_PATH
    os.environ["ESPEAK_DATA_PATH"]       = os.path.join(_ESPEAK_PATH, "espeak-ng-data")
# VCTK/XTTS's own local-vs-cache path resolution now lives inside their
# engine modules (engines/coqui_vctk.py, engines/coqui_xtts.py), each
# given _MODELS_BASE via TTS_ENGINES = get_tts_engines(_MODELS_BASE) below.
WHISPER_MODEL_DIR = os.path.join(_MODELS_BASE, "whisper")
VOSK_MODEL_DIR    = os.path.join(_MODELS_BASE, "vosk")


# ──────────────────────────────────────────────────────────────
#  TTS ENGINE REGISTRY
# ──────────────────────────────────────────────────────────────
# All pluggable TTS engines (VCTK, XTTS-v2 today; Piper/Kokoro/Fish
# Speech/MeloTTS/ChatTTS as they're added) live in the engines/ package
# and register themselves here. The Models table, Check All/Download
# Missing flow, and per-engine license dialogs below all drive off this
# dict instead of hardcoding engine names/paths - see engines/registry.py
# for how to add a new engine.
from engines.registry import get_tts_engines
from engines.coqui_xtts import CLONE_PREFIX
TTS_ENGINES = get_tts_engines(_MODELS_BASE)

# Captions/subtitles generation (ffmpeg extraction + Whisper word-level
# transcription + caption chunking + .srt/.vtt writers) - see subtitles.py.
import subtitles


# ──────────────────────────────────────────────────────────────
#  PER-ENGINE LICENSE (TOS) HANDLING
# ──────────────────────────────────────────────────────────────
# Some engines (XTTS-v2's CPML today) require explicit license
# agreement before their first download. Coqui's own download code
# blocks on a terminal input() call to get that agreement, which is
# fatal from a background thread (no stdin to read) and from a packaged
# app with no terminal at all - see engines/coqui_xtts.py's docstring.
# This shows a real GUI dialog instead, driven by whatever engine.
# requires_tos/tos_title/tos_text says, so it automatically covers any
# future engine that also needs a license click-through.
def _engine_tos_marker(key):
    return os.path.join(_MODELS_BASE, f".{key}_tos_agreed")


def _engine_tos_already_agreed(key):
    spec = TTS_ENGINES.get(key)
    if not spec or not spec.requires_tos:
        return True
    return os.path.isfile(_engine_tos_marker(key))


def _apply_agreed_tos_env_vars():
    # Coqui-specific escape hatch: XTTS's tos_agreed() short-circuits to
    # True (skipping its own input() prompt) if COQUI_TOS_AGREED == "1".
    # Other engines may need their own env vars/markers when added.
    if os.path.isfile(_engine_tos_marker("xtts")):
        os.environ["COQUI_TOS_AGREED"] = "1"


# Apply immediately at import time (main thread, before any background
# thread or TTS import), so a returning user never sees the dialog again.
_apply_agreed_tos_env_vars()

# ──────────────────────────────────────────────────────────────
#  COLOURS
# ──────────────────────────────────────────────────────────────
BG      = "#1a1b2e"
CARD    = "#1e1f33"
SURFACE = "#2a2b45"
BORDER  = "#3a3b5c"
BLUE    = "#7aa2f7"
GREEN   = "#9ece6a"
RED     = "#f7768e"
YELLOW  = "#e0af68"
PURPLE  = "#bb9af7"
CYAN    = "#7dcfff"
ORANGE  = "#ff9e64"
FG      = "#c0caf5"
FG_DIM  = "#565f89"

# ──────────────────────────────────────────────────────────────
#  STT ENGINE AVAILABILITY
# ──────────────────────────────────────────────────────────────
try:
    import whisper as _w_test
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False

try:
    from vosk import Model as _VoskModel, KaldiRecognizer as _VoskRec
    VOSK_AVAILABLE = True
except ImportError:
    VOSK_AVAILABLE = False

# ──────────────────────────────────────────────────────────────
#  LAZY MODEL CACHE
# ──────────────────────────────────────────────────────────────
# VCTK/XTTS instance caching now lives inside engines/coqui_vctk.py and
# engines/coqui_xtts.py respectively (each engine module owns its own
# lazy-singleton pattern) - see TTS_ENGINES[key].synthesize() call sites
# below instead of the old get_tts_vctk()/get_tts_xtts() functions that
# used to be here.
_whisper_model = None
_vosk_models   = {}

def get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        import whisper
        model_file = os.path.join(WHISPER_MODEL_DIR, "small.pt")
        if os.path.isfile(model_file):
            _whisper_model = whisper.load_model(model_file)
        else:
            _whisper_model = whisper.load_model("small")
    return _whisper_model

def get_vosk_model(lang_code):
    if lang_code not in _vosk_models:
        from vosk import Model
        model_path = os.path.join(VOSK_MODEL_DIR, lang_code)
        if not os.path.isdir(model_path):
            raise FileNotFoundError(
                f"Vosk model for '{lang_code}' not found at:\n{model_path}\n\n"
                f"Download from https://alphacephei.com/vosk/models\n"
                f"and extract to that folder.")
        _vosk_models[lang_code] = Model(model_path)
    return _vosk_models[lang_code]

# ──────────────────────────────────────────────────────────────
#  LANGUAGES
# ──────────────────────────────────────────────────────────────
LANGUAGES = [
    ("English",    "en", "en", "en", "en"),
    ("Slovenian",  "sl", "sl", "sl", "sl"),
    ("Russian",    "ru", "ru", "ru", "ru"),
    ("German",     "de", "de", "de", "de"),
    ("French",     "fr", "fr", "fr", "fr"),
    ("Spanish",    "es", "es", "es", "es"),
    ("Italian",    "it", "it", "it", "it"),
    ("Japanese",   "ja", "ja", "ja", "ja"),
    ("Chinese",    "zh", "zh", "zh", "zh"),
    ("Portuguese", "pt", "pt", "pt", "pt"),
    ("Polish",     "pl", "pl", "pl", "pl"),
    ("Czech",      "cs", "cs", "cs", "cs"),
    ("Dutch",      "nl", "nl", "nl", "nl"),
    ("Turkish",    "tr", "tr", "tr", "tr"),
    ("Croatian",   "hr", "hr", "hr", "hr"),
    ("Korean",     "ko", "ko", "ko", "ko"),
    ("Arabic",     "ar", "ar", "ar", "ar"),
]

LANG_DISPLAY = [l[0] for l in LANGUAGES]
LANG_WHISPER = {l[0]: l[1] for l in LANGUAGES}
LANG_VOSK    = {l[0]: l[2] for l in LANGUAGES}
LANG_XTTS    = {l[0]: l[3] for l in LANGUAGES}
LANG_TR      = {l[0]: l[4] for l in LANGUAGES}

# XTTS-v2 genuinely supports only these 17 languages (Coqui's own docs:
# en, es, fr, de, it, pt, pl, tr, ru, nl, cs, ar, zh-cn, hu, ko, ja, hi).
# Two languages in our LANGUAGES table above - Slovenian and Croatian -
# are NOT among them, despite the old XTTS_SUPPORTED set (wrongly)
# including "sl"/"hr" and omitting "hi". That let unsupported codes
# reach Coqui's code, which raises: "Language sl is not supported."
# "hu"/"ro" below were dead entries with no matching LANGUAGES row.
XTTS_SUPPORTED = {"en","ru","de","fr","es","it","ja","zh","pt","pl","cs","nl","ar","ko","tr"}

# Languages selectable for XTTS specifically - filtered to what the
# model actually supports, so an unsupported language can't be picked
# in the first place (rather than silently falling back to English).
XTTS_LANG_DISPLAY = [name for name in LANG_DISPLAY if LANG_XTTS[name] in XTTS_SUPPORTED]

# ──────────────────────────────────────────────────────────────
#  VCTK SPEAKER MAP
# ──────────────────────────────────────────────────────────────
SPEAKER_MAP = {
    "Adam":("p225","M"),"Liam":("p226","M"),"John":("p227","M"),"Emma":("p228","F"),
    "Mia":("p229","F"),"Olivia":("p230","F"),"James":("p231","M"),"Emily":("p232","F"),
    "Sophie":("p233","F"),"Grace":("p234","F"),"Lucas":("p236","M"),"Nathan":("p237","M"),
    "Ethan":("p238","M"),"Chloe":("p239","F"),"Zoe":("p240","F"),"Hannah":("p241","F"),
    "Daniel":("p243","M"),"Oliver":("p244","M"),"Amelia":("p245","F"),"Isabella":("p246","F"),
    "Charlotte":("p247","F"),"Ella":("p248","F"),"Scarlett":("p249","F"),"Victoria":("p250","F"),
    "Henry":("p251","M"),"Mason":("p252","M"),"Logan":("p253","M"),"Harper":("p254","F"),
    "Evelyn":("p255","F"),"Avery":("p256","F"),"Abigail":("p257","F"),"Lily":("p258","F"),
    "Aria":("p259","F"),"Ellie":("p260","F"),"Jackson":("p261","M"),"Aiden":("p262","M"),
    "Sebastian":("p263","M"),"Luna":("p264","F"),"Camila":("p265","F"),"Penelope":("p266","F"),
    "Riley":("p267","F"),"Layla":("p268","F"),"Nora":("p269","F"),"Lillian":("p270","F"),
    "Eleanor":("p271","F"),"Eliana":("p272","F"),"Paisley":("p273","F"),"Naomi":("p274","F"),
    "Elena":("p275","F"),"Savannah":("p276","F"),"Stella":("p277","F"),"Aurora":("p278","F"),
    "Bella":("p279","F"),"Claire":("p280","F"),"Skylar":("p281","F"),"Lucy":("p282","F"),
    "Anna":("p283","F"),"Samantha":("p284","F"),"Caroline":("p285","F"),"Genesis":("p286","F"),
    "Aaliyah":("p287","F"),"Kennedy":("p288","F"),"Kinsley":("p292","F"),"Allison":("p293","F"),
    "Violet":("p294","F"),"Natalie":("p295","F"),"Aubrey":("p297","F"),"Leah":("p298","F"),
    "Audrey":("p299","F"),"Autumn":("p300","F"),"Lila":("p301","F"),"Zoey":("p302","F"),
    "Brooklyn":("p303","F"),"Alexa":("p304","F"),"Kylie":("p305","F"),"Maya":("p306","F"),
    "Madeline":("p307","F"),"Peyton":("p308","F"),"Katherine":("p310","F"),"Mackenzie":("p311","F"),
    "Adaline":("p312","F"),"Eva":("p313","F"),"Josephine":("p314","F"),"Emilia":("p316","F"),
    "Serenity":("p317","F"),"Piper":("p318","F"),"Sadie":("p323","F"),"Delilah":("p326","F"),
    "Ariana":("p329","F"),"Ivy":("p330","F"),"Quinn":("p333","F"),"Everleigh":("p334","F"),
    "Adeline":("p335","F"),"Ruby":("p336","F"),"Isla":("p339","F"),"Lydia":("p340","F"),
    "Jade":("p341","F"),"Melody":("p343","F"),"Brianna":("p345","F"),"Lena":("p347","F"),
    "Valentina":("p351","F"),"Leila":("p360","F"),"Vivienne":("p361","F"),"Margot":("p362","F"),
    "Diana":("p363","F"),"Kate":("p374","F"),"Rose":("p376","F"),
}

def disp(name, sid): return f"{name} ({sid})"

# ──────────────────────────────────────────────────────────────
#  SELF-WRITING CONFIG
# ──────────────────────────────────────────────────────────────
def _rewrite_config(key, value_repr, comment):
    try:
        path = os.path.realpath(__file__)
        with open(path, "r", encoding="utf-8") as f: lines = f.readlines()
        for i, line in enumerate(lines):
            if line.startswith(f"{key} ="):
                lines[i] = f"{key} = {value_repr}  # {comment}\n"; break
        with open(path, "w", encoding="utf-8") as f: f.writelines(lines)
    except Exception: pass

def persist_folder(v):    _rewrite_config("LAST_FOLDER",     f'r"{v}"',       "auto-updates on browse")
def persist_favorites(v): _rewrite_config("SAVED_FAVORITES", repr(sorted(v)), "auto-updates when you star/unstar voices")

# ──────────────────────────────────────────────────────────────
#  AUTO-DETECT MICROPHONE
# ──────────────────────────────────────────────────────────────
def auto_detect_mic(mic_list):
    keywords   = ["microphone","mic","headset","webcam","usb audio","realtek","input"]
    anti_words = ["output","speaker","hdmi","virtual","stereo mix","loopback"]
    best_idx, best_score = 0, -1
    for i, name in enumerate(mic_list):
        n = name.lower()
        if any(a in n for a in anti_words): continue
        score = sum(k in n for k in keywords)
        if score > best_score: best_score = score; best_idx = i
    return best_idx

# ──────────────────────────────────────────────────────────────
#  GOOGLE TRANSLATE
# ──────────────────────────────────────────────────────────────
def google_translate(text, src, tgt):
    if src == tgt: return text
    params = urllib.parse.urlencode({"client":"gtx","sl":src,"tl":tgt,"dt":"t","q":text})
    req = urllib.request.Request(
        f"https://translate.googleapis.com/translate_a/single?{params}",
        headers={"User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=8) as r:
        data = json.loads(r.read().decode())
    return "".join(seg[0] for seg in data[0] if seg[0])

# ──────────────────────────────────────────────────────────────
#  SCROLLABLE FRAME
# ──────────────────────────────────────────────────────────────
class ScrollableFrame(tk.Frame):
    def __init__(self, parent, **kw):
        super().__init__(parent, **kw)
        self._canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        self._vsb    = ttk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._vsb.set)
        self._vsb.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self._canvas, bg=BG)
        self._win  = self._canvas.create_window((0,0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda _: self._canvas.configure(
            scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", lambda e: self._canvas.itemconfig(
            self._win, width=e.width))
        for s in ("<MouseWheel>","<Button-4>","<Button-5>"):
            self._canvas.bind(s, self._scroll)

    def _scroll(self, e):
        if   e.num==4: self._canvas.yview_scroll(-1, "units")
        elif e.num==5: self._canvas.yview_scroll( 1, "units")
        else:          self._canvas.yview_scroll(int(-1*(e.delta/120)), "units")

    def bind_all_mousewheel(self, w):
        for s in ("<MouseWheel>","<Button-4>","<Button-5>"):
            w.bind(s, self._scroll, add="+")
        for c in w.winfo_children(): self.bind_all_mousewheel(c)

# ──────────────────────────────────────────────────────────────
#  MIC PERMISSION CHECK (real OS-level test, not a fake dialog)
# ──────────────────────────────────────────────────────────────
def check_mic_access():
    """Actually try to open the default input device.
    Returns (ok: bool, message: str)."""
    try:
        import pyaudio
        pa = pyaudio.PyAudio()
        try:
            info = pa.get_default_input_device_info()
        except Exception:
            pa.terminate()
            return False, "No microphone detected on this system."
        try:
            # Use the device's own native rate rather than forcing
            # 16000 - some ALSA devices reject that exact rate
            # (paInvalidSampleRate) even though they work fine at their
            # own default, and everything downstream resamples anyway.
            native_rate = int(info.get("defaultSampleRate") or 16000)
            stream = pa.open(format=pyaudio.paInt16, channels=1, rate=native_rate,
                              input=True, frames_per_buffer=1024,
                              input_device_index=info["index"])
            stream.stop_stream()
            stream.close()
            pa.terminate()
            return True, "Microphone access granted"
        except Exception as e:
            pa.terminate()
            return False, str(e)
    except Exception as e:
        return False, f"Microphone check failed: {e}"


def show_mic_blocked_dialog(root, reason):
    dlg = tk.Toplevel(root); dlg.title("Microphone Blocked")
    dlg.configure(bg=CARD); dlg.resizable(False, False); dlg.grab_set()
    root.update_idletasks()
    x = root.winfo_x() + root.winfo_width()  // 2 - 220
    y = root.winfo_y() + root.winfo_height() // 2 - 110
    dlg.geometry(f"440x220+{x}+{y}")
    tk.Label(dlg, text="Microphone Blocked", bg=CARD, fg=RED,
             font=("Segoe UI", 12, "bold")).pack(pady=(18, 4))
    tk.Label(dlg,
             text=("This app couldn't access your microphone:\n"
                   f"{reason}\n\n"
                   "Windows: Settings > Privacy > Microphone\n"
                   "macOS: System Settings > Privacy & Security > Microphone\n"
                   "Linux: check pavucontrol / system sound settings\n\n"
                   "Fix it, then click Retry."),
             bg=CARD, fg=FG, font=("Segoe UI", 9), justify="center", wraplength=400
             ).pack(pady=(0, 14))
    result = {"retry": False}
    def retry(): result["retry"] = True; dlg.destroy()
    def close(): dlg.destroy()
    brow = tk.Frame(dlg, bg=CARD); brow.pack()
    tk.Button(brow, text="Retry", command=retry, bg=GREEN, fg=BG, relief="flat",
              cursor="hand2", padx=16, pady=6, font=("Segoe UI", 9, "bold"), bd=0
              ).pack(side="left", padx=8)
    tk.Button(brow, text="Close", command=close, bg=SURFACE, fg=FG, relief="flat",
              cursor="hand2", padx=16, pady=6, font=("Segoe UI", 9), bd=0
              ).pack(side="left", padx=8)
    dlg.wait_window()
    return result["retry"]

# ──────────────────────────────────────────────────────────────
#  MAIN APP
# ──────────────────────────────────────────────────────────────
class AIApp:
    def __init__(self, root):
        self.root = root
        root.title("AI Voice Studio")
        root.geometry("820x920")
        root.configure(bg=BG)
        root.resizable(True, True)
        self._mic_allowed = False
        # Tracks whether a model download is actively running in a
        # background thread, so we can warn before the user closes the
        # app mid-download - closing kills the (daemon) download thread
        # instantly with no resume, leaving a partial/empty model folder
        # behind that looked like it was "installed" (see _do_check_models
        # size-based fix for why that's now caught, but prevention here
        # is better than detecting it after the fact).
        self._download_in_progress = False
        root.protocol("WM_DELETE_WINDOW", self._on_close_request)

        style = ttk.Style(); style.theme_use("clam")
        style.configure("TCombobox",
                        fieldbackground=SURFACE, background=SURFACE,
                        foreground=FG, selectbackground=SURFACE,
                        selectforeground=FG, arrowcolor=FG)
        style.map("TCombobox", fieldbackground=[("readonly", SURFACE)])
        style.configure("TCheckbutton", background=CARD, foreground=FG)
        style.map("TCheckbutton", background=[("active",CARD)], foreground=[("active",FG)])
        style.configure("Vertical.TScrollbar",
                        background=SURFACE, troughcolor=CARD,
                        bordercolor=CARD, arrowcolor=FG_DIM, relief="flat")
        for name, col in [("Loading",BLUE),("Trans",ORANGE),("XTTS",PURPLE)]:
            style.configure(f"{name}.Horizontal.TProgressbar",
                            troughcolor=SURFACE, background=col,
                            bordercolor=SURFACE, lightcolor=col,
                            darkcolor=col, relief="flat")

        pygame.mixer.init()
        self.favorites    = set(SAVED_FAVORITES)
        self.preview_temp = None
        self.fav_btn      = None
        self.fav_status   = None
        self.is_listening = False

        self._scroller = ScrollableFrame(root)
        self._scroller.pack(fill="both", expand=True)
        self._inner = self._scroller.inner

        self._build_models_frame()
        self._build_tts_frame()
        self._build_stt_frame()
        self._build_captions_frame()
        self._build_translator_frame()
        self._build_voice_changer_frame()
        self._build_footer()

        root.after(150, lambda: self._scroller.bind_all_mousewheel(self._inner))
        root.after(400, self._request_mic_permission)

    def _on_close_request(self):
        if self._download_in_progress:
            proceed = messagebox.askyesno(
                "Download in progress",
                "A model download is still running. Closing now will "
                "cancel it and leave an incomplete model folder that "
                "you'll need to re-download from scratch.\n\n"
                "Close anyway?")
            if not proceed:
                return
        self.root.destroy()

    def _request_mic_permission(self):
        ok, msg = check_mic_access()
        self._mic_allowed = ok
        if not self._stt_note.winfo_exists():
            return
        if ok:
            self._stt_note.config(text="Microphone access granted", fg=GREEN)
            self.root.after(3000, lambda: self._stt_note.winfo_exists() and self._stt_note.config(
                text="Don't forget to choose the right microphone!", fg=YELLOW))
        else:
            self._stt_note.config(text="Microphone blocked - STT won't work", fg=RED)
            if show_mic_blocked_dialog(self.root, msg):
                self._request_mic_permission()   # user clicked Retry

    def _ensure_mic_access(self):
        """Re-check mic access on demand (e.g. right before starting STT or
        the voice changer), in case it was blocked/fixed since startup.
        Returns True if the mic is usable, False otherwise."""
        if self._mic_allowed:
            return True
        ok, msg = check_mic_access()
        self._mic_allowed = ok
        if ok:
            return True
        if show_mic_blocked_dialog(self.root, msg):
            return self._ensure_mic_access()   # user clicked Retry
        return False

    def _refresh_mic_list(self, initial=False):
        """(Re)populate self.mics / mics_display / mics_real from the
        system's current microphone list, and pick the best-guess
        device via auto_detect_mic(). mics_real maps a mics_display
        index to the real device_index to pass to sr.Microphone() -
        None for "System Default", an int for every other entry.

        (mics_real used to be built as `[None] + self.mics`, which put
        device *names* where device *indices* belonged and was never
        actually read anywhere - the real lookup went through
        `self.mics.index(self.selected_mic.get())` instead, which
        raised a ValueError whenever "System Default" was selected,
        silently killing the STT thread mid-listen with the UI still
        showing "Listening..." - indistinguishable from a freeze.)
        """
        self.mics = sr.Microphone.list_microphone_names()
        best_idx = auto_detect_mic(self.mics)
        self.mics_display = ["System Default"] + self.mics if self.mics else ["No microphone found"]
        self.mics_real = [None] + list(range(len(self.mics)))
        default_display = self.mics_display[best_idx + 1] if self.mics else self.mics_display[0]
        if initial:
            self.selected_mic = tk.StringVar(value=default_display)
        else:
            self.selected_mic.set(default_display)
            if hasattr(self, "mic_combo"):
                self.mic_combo["values"] = self.mics_display

    def _autodetect_mic(self):
        self._refresh_mic_list()
        self._set_stt_status(f"Autodetected: {self.selected_mic.get()}", CYAN)
        self.root.after(2200, lambda: self._set_stt_status(
            "Listening..." if getattr(self, "is_listening", False) else "Press Start to begin", FG_DIM))

    def _resolve_mic_index(self):
        """Map the selected dropdown entry to the device_index
        sr.Microphone expects: None for "System Default", an int for a
        named device."""
        try:
            disp_idx = self.mics_display.index(self.selected_mic.get())
        except ValueError:
            disp_idx = 0
        return self.mics_real[disp_idx] if disp_idx < len(self.mics_real) else None

    @contextmanager
    def _open_mic(self, mic_index):
        """Open a Microphone as a context manager, guarding against two
        real bugs that combined into the packaged-AppImage STT crash:

        1. We used to force `sample_rate=16000` on every Microphone()
           call. Some ALSA devices reject that exact rate outright
           (PortAudio's "paInvalidSampleRate"), even though the same
           device works fine at its own native rate. We already
           resample to 16kHz downstream via `get_raw_data(convert_rate=
           16000, ...)`, so there's no need to force the capture rate -
           letting SpeechRecognition auto-pick the device's own
           defaultSampleRate avoids the mismatch entirely.

        2. speech_recognition's own Microphone.__enter__() has a bug:
           if opening the PyAudio stream fails for any reason, it
           catches the exception, terminates PyAudio... and then still
           returns normally instead of re-raising. That leaves
           `source.stream` as None with no exception raised, so calling
           code sails into adjust_for_ambient_noise() and hits an
           AssertionError there ("must be entered before adjusting"),
           and then __exit__() hits a second crash (AttributeError:
           'NoneType' object has no attribute 'close') trying to close
           a stream that was never opened. We check for that failure
           state ourselves right after __enter__() and turn it into one
           clear, catchable RuntimeError instead of that double crash.
        """
        source = sr.Microphone(device_index=mic_index)
        source.__enter__()
        try:
            if source.stream is None:
                raise RuntimeError(
                    "Could not open this microphone - it may be busy, "
                    "disconnected, or rejected by the audio driver. Try "
                    "picking a different microphone from the dropdown."
                )
            yield source
        finally:
            if source.stream is not None:
                source.__exit__(None, None, None)
            else:
                try:
                    source.audio.terminate()
                except Exception:
                    pass

    def _lf(self, title, fg_title=PURPLE):
        f = tk.LabelFrame(self._inner, text=f"  {title}  ",
                          bg=CARD, fg=fg_title, font=("Segoe UI",10,"bold"),
                          bd=2, relief="groove", labelanchor="nw", padx=6, pady=6)
        f.pack(fill="x", padx=10, pady=6)
        return f

    def _label(self, parent, text, fg=FG, font=("Segoe UI",9), **kw):
        try:    bg = parent.cget("bg")
        except: bg = BG
        return tk.Label(parent, text=text, bg=bg, fg=fg, font=font, **kw)

    def _btn(self, parent, text, cmd, color=SURFACE, fg=FG, bold=False, padx=12, pady=5):
        f = ("Segoe UI",9,"bold") if bold else ("Segoe UI",9)
        b = tk.Button(parent, text=text, command=cmd, bg=color, fg=fg,
                      activebackground=self._lc(color), activeforeground=fg,
                      relief="flat", cursor="hand2", padx=padx, pady=pady, font=f, bd=0)
        b.bind("<Enter>", lambda e: b.config(bg=self._lc(color)))
        b.bind("<Leave>", lambda e: b.config(bg=color))
        return b

    @staticmethod
    def _lc(h):
        r,g,b = int(h[1:3],16), int(h[3:5],16), int(h[5:7],16)
        return f"#{min(255,r+28):02x}{min(255,g+28):02x}{min(255,b+28):02x}"

    def _textarea(self, parent, height=6):
        wrap = tk.Frame(parent, bg=BORDER, padx=1, pady=1)
        wrap.pack(fill="x", padx=2, pady=(0,4))
        t = tk.Text(wrap, height=height, bg=SURFACE, fg=FG,
                    insertbackground=BLUE, relief="flat",
                    font=("Segoe UI",10), wrap="word", padx=6, pady=6)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        t.pack(side="left", fill="both", expand=True)
        def _mw(e):
            if   e.num==4: t.yview_scroll(-1,"units")
            elif e.num==5: t.yview_scroll( 1,"units")
            else:          t.yview_scroll(int(-1*(e.delta/120)),"units")
            return "break"
        for s in ("<MouseWheel>","<Button-4>","<Button-5>"): t.bind(s, _mw)
        return t

    def _prog_widgets(self, parent, style="Loading"):
        pf = tk.Frame(parent, bg=CARD); pf.pack(fill="x", padx=4, pady=(2,2))
        lbl = self._label(pf, "", fg=FG_DIM, font=("Segoe UI",8)); lbl.pack(anchor="w")
        bar = ttk.Progressbar(pf, style=f"{style}.Horizontal.TProgressbar",
                               mode="indeterminate", length=400)
        bar.pack(fill="x", pady=(2,0))
        return lbl, bar

    def _build_tts_frame(self):
        f = self._lf("Text-to-Speech")
        ob = tk.Frame(f, bg=CARD); ob.pack(fill="x", padx=2, pady=(0,4))
        tk.Label(ob, text="OFFLINE", bg=CARD, fg=GREEN,
                 font=("Segoe UI",8,"bold")).pack(side="left")
        self._label(ob, "  Both engines run 100% locally",
                    fg=FG_DIM, font=("Segoe UI",8)).pack(side="left")

        eng = tk.Frame(f, bg=CARD); eng.pack(fill="x", padx=2, pady=(0,4))
        self._label(eng, "Engine:").pack(side="left")
        self.tts_engine = tk.StringVar(value="VCTK (English voices)")
        ttk.Combobox(eng, textvariable=self.tts_engine, state="readonly",
                     width=30, font=("Segoe UI",9),
                     values=["VCTK (English voices)", "XTTS-v2 (Multilingual)"]
                     ).pack(side="left", padx=(4,10))
        self.tts_engine.trace_add("write", lambda *_: self._on_engine_change())

        self._xtts_lang_frame = tk.Frame(eng, bg=CARD)
        self._label(self._xtts_lang_frame, "Language:").pack(side="left")
        self.xtts_lang_var = tk.StringVar(value=XTTS_LANG_DISPLAY[0])
        ttk.Combobox(self._xtts_lang_frame, textvariable=self.xtts_lang_var,
                     values=XTTS_LANG_DISPLAY, state="readonly",
                     width=16, font=("Segoe UI",9)).pack(side="left", padx=4)

        self._label(f, "Enter text to speak:").pack(anchor="w", padx=2, pady=(2,2))
        self.text_entry = self._textarea(f, height=4)

        self._vctk_panel = tk.Frame(f, bg=CARD); self._vctk_panel.pack(fill="x")
        vrow = tk.Frame(self._vctk_panel, bg=CARD); vrow.pack(fill="x", padx=2, pady=3)
        self._label(vrow, "Voice:").pack(side="left")
        self.speaker_var = tk.StringVar()
        self.speaker_dropdown = ttk.Combobox(vrow, textvariable=self.speaker_var,
                                              state="readonly", width=28, font=("Segoe UI",9))
        self.speaker_dropdown.pack(side="left", padx=(4,10))
        self._label(vrow, "Filter:").pack(side="left")
        self.gender_filter = tk.StringVar(value="All")
        for lbl, val in [("All","All"),("Fav","Fav"),("Male","Male"),("Female","Female")]:
            tk.Radiobutton(vrow, text=lbl, variable=self.gender_filter, value=val,
                           command=self.refresh_voice_list,
                           bg=CARD, fg=FG, selectcolor=SURFACE,
                           activebackground=CARD, activeforeground=FG,
                           font=("Segoe UI",9)).pack(side="left", padx=3)

        frow = tk.Frame(self._vctk_panel, bg=CARD); frow.pack(fill="x", padx=2, pady=2)
        self.fav_btn = self._btn(frow, "Add to Favorites",
                                  self.toggle_favorite, color=SURFACE, fg=YELLOW)
        self.fav_btn.pack(side="left")
        self.fav_status = self._label(frow, ""); self.fav_status.pack(side="left", padx=10)
        self.refresh_voice_list()
        self.speaker_var.trace_add("write", lambda *_: self.update_fav_btn())

        self._xtts_panel = tk.Frame(f, bg=CARD)
        self._label(self._xtts_panel,
                    f"XTTS-v2  {len(XTTS_LANG_DISPLAY)} of the app's languages "
                    "supported (see dropdown above)",
                    fg=FG_DIM, font=("Segoe UI",8)).pack(anchor="w", padx=4, pady=(4,0))
        xvrow = tk.Frame(self._xtts_panel, bg=CARD); xvrow.pack(fill="x", padx=4, pady=4)
        self._label(xvrow, "Voice:").pack(side="left")
        xtts_voices = TTS_ENGINES["xtts"].list_voices()
        self.xtts_speaker_var = tk.StringVar(
            value=xtts_voices[0] if xtts_voices else "")
        self._xtts_preset_dropdown = ttk.Combobox(
            xvrow, textvariable=self.xtts_speaker_var,
            values=xtts_voices, state="readonly",
            width=22, font=("Segoe UI",9))
        self._xtts_preset_dropdown.pack(side="left", padx=(4,10))

        self.xtts_clone_path = None
        xcrow = tk.Frame(self._xtts_panel, bg=CARD); xcrow.pack(fill="x", padx=4, pady=(0,4))
        self._btn(xcrow, "Clone Voice from File...", self._pick_xtts_clone,
                  color=SURFACE).pack(side="left")
        self._xtts_clone_label = self._label(
            xcrow, "  Using built-in preset voice above", fg=FG_DIM, font=("Segoe UI",8))
        self._xtts_clone_label.pack(side="left", padx=4)
        self._xtts_clone_clear = self._btn(
            xcrow, "Clear", self._clear_xtts_clone, color=SURFACE, fg=RED)
        self._xtts_clone_clear.pack(side="left", padx=4)
        self._xtts_clone_clear.pack_forget()  # only shown once a clone file is set

        # Speed slider
        spd = tk.Frame(f, bg=CARD); spd.pack(fill="x", padx=2, pady=4)
        self._label(spd, "Speed:").pack(side="left")
        self.tts_speed = tk.DoubleVar(value=1.0)
        speed_slider = ttk.Scale(spd, from_=0.5, to=2.0, orient="horizontal",
                                  variable=self.tts_speed, length=200)
        speed_slider.pack(side="left", padx=6)
        self._speed_label = tk.Label(spd, text="1.0x", bg=CARD, fg=CYAN,
                                      font=("Segoe UI",9,"bold"), width=4)
        self._speed_label.pack(side="left")
        self.tts_speed.trace_add("write", lambda *_: self._speed_label.config(
            text=f"{self.tts_speed.get():.1f}x"))
        self._btn(spd, "Reset", lambda: self.tts_speed.set(1.0),
                  color=SURFACE, padx=6).pack(side="left", padx=4)

        fldr = tk.Frame(f, bg=CARD); fldr.pack(fill="x", padx=2, pady=4)
        self._label(fldr, "Save to:").pack(side="left")
        self.save_path_var = tk.StringVar(
            value=LAST_FOLDER if os.path.exists(LAST_FOLDER) else "")
        tk.Entry(fldr, textvariable=self.save_path_var, bg=SURFACE, fg=FG,
                 insertbackground=BLUE, relief="flat",
                 font=("Segoe UI",9), width=46).pack(side="left", padx=6)
        self._btn(fldr, "Browse", self.browse_folder).pack(side="left")

        brow = tk.Frame(f, bg=CARD); brow.pack(pady=(6,2))
        self._btn(brow, "Preview",    self.preview_voice,  color=BLUE,  fg=BG, bold=True).pack(side="left", padx=5)
        self._btn(brow, "Save Audio", self.generate_voice, color=GREEN, fg=BG, bold=True).pack(side="left", padx=5)
        self._btn(brow, "Stop",       self.stop_preview,   color=RED,   fg=BG, bold=True).pack(side="left", padx=5)

        self._prog_label, self._progressbar_w = self._prog_widgets(f, "Loading")
        self.tts_status = self._label(f, "Ready", fg=FG_DIM)
        self.tts_status.pack(pady=(2,6))

    def _pick_xtts_clone(self):
        path = filedialog.askopenfilename(
            title="Choose a reference voice clip to clone",
            filetypes=[("Audio files", "*.wav *.mp3 *.flac *.m4a *.ogg"),
                       ("All files", "*.*")])
        if not path:
            return
        self.xtts_clone_path = path
        fname = os.path.basename(path)
        self._xtts_clone_label.config(
            text=f"  Cloning from: {fname}", fg=GREEN)
        self._xtts_clone_clear.pack(side="left", padx=4)
        self._xtts_preset_dropdown.config(state="disabled")

    def _clear_xtts_clone(self):
        self.xtts_clone_path = None
        self._xtts_clone_label.config(
            text="  Using built-in preset voice above", fg=FG_DIM)
        self._xtts_clone_clear.pack_forget()
        self._xtts_preset_dropdown.config(state="readonly")

    def _xtts_voice_arg(self):
        """The `voice` string to hand XTTS's synthesize(): a cloned
        reference clip if one was picked, otherwise the selected preset
        name. See engines/coqui_xtts.py's CLONE_PREFIX for how this
        gets interpreted on the other end."""
        if getattr(self, "xtts_clone_path", None):
            return CLONE_PREFIX + self.xtts_clone_path
        return self.xtts_speaker_var.get()

    def _on_engine_change(self):
        if self.tts_engine.get().startswith("XTTS"):
            self._vctk_panel.pack_forget()
            self._xtts_lang_frame.pack(side="left")
            self._xtts_panel.pack(fill="x")
        else:
            self._xtts_panel.pack_forget()
            self._xtts_lang_frame.pack_forget()
            self._vctk_panel.pack(fill="x")

    def _build_stt_frame(self):
        f = self._lf("Speech-to-Text")
        brow = tk.Frame(f, bg=CARD); brow.pack(fill="x", padx=2, pady=(0,6))
        w_col = GREEN if WHISPER_AVAILABLE else FG_DIM
        v_col = GREEN if VOSK_AVAILABLE   else FG_DIM
        tk.Label(brow, text="Whisper" if WHISPER_AVAILABLE else "Whisper (not installed)",
                 bg=CARD, fg=w_col, font=("Segoe UI",8,"bold")).pack(side="left")
        self._label(brow, "   |   ", fg=FG_DIM, font=("Segoe UI",8)).pack(side="left")
        tk.Label(brow, text="Vosk" if VOSK_AVAILABLE else "Vosk (not installed)",
                 bg=CARD, fg=v_col, font=("Segoe UI",8,"bold")).pack(side="left")
        self._label(brow, "   All offline", fg=FG_DIM, font=("Segoe UI",8)).pack(side="left")

        eng_row = tk.Frame(f, bg=CARD); eng_row.pack(fill="x", padx=2, pady=(0,4))
        self._label(eng_row, "STT Engine:").pack(side="left")
        available = []
        if WHISPER_AVAILABLE: available.append("Whisper (recommended)")
        if VOSK_AVAILABLE:    available.append("Vosk (lightweight)")
        if not available:     available = ["None installed"]
        self.stt_engine = tk.StringVar(value=available[0])
        ttk.Combobox(eng_row, textvariable=self.stt_engine, state="readonly",
                     values=available, width=24, font=("Segoe UI",9)
                     ).pack(side="left", padx=(4,10))
        self._label(eng_row, "Spoken language:").pack(side="left")
        self.stt_lang_var = tk.StringVar(value=LANG_DISPLAY[0])
        ttk.Combobox(eng_row, textvariable=self.stt_lang_var,
                     values=LANG_DISPLAY, state="readonly",
                     width=16, font=("Segoe UI",9)).pack(side="left", padx=4)

        mic_row = tk.Frame(f, bg=CARD); mic_row.pack(fill="x", padx=2, pady=(2,0))
        self._label(mic_row, "Mic:").pack(side="left")
        self.recognizer   = sr.Recognizer()
        self._refresh_mic_list(initial=True)
        self.mic_combo = ttk.Combobox(mic_row, textvariable=self.selected_mic,
                     values=self.mics_display, state="readonly",
                     width=36, font=("Segoe UI",9))
        self.mic_combo.pack(side="left", padx=6)
        self._btn(mic_row, "Autodetect", self._autodetect_mic,
                  color=SURFACE, padx=8).pack(side="left")
        self.always_on_top = tk.BooleanVar(value=False)
        ttk.Checkbutton(mic_row, text="On Top", variable=self.always_on_top,
                        command=self.toggle_top).pack(side="right", padx=4)

        self._stt_note = self._label(
            f, "Don't forget to choose the right microphone!",
            fg=YELLOW, font=("Segoe UI",8))
        self._stt_note.pack(anchor="w", padx=2, pady=(2,2))

        st = tk.Frame(f, bg=CARD); st.pack(fill="x", padx=2, pady=(2,0))
        self.stt_dot      = tk.Label(st, text="●", bg=CARD, fg=FG_DIM, font=("Segoe UI",13))
        self.stt_dot.pack(side="left")
        self.status_label = self._label(st, "Press Start to begin", fg=FG_DIM)
        self.status_label.pack(side="left", padx=(3,0))
        self.live_word_var = tk.StringVar(value="")
        tk.Label(st, textvariable=self.live_word_var, bg=CARD, fg=CYAN,
                 font=("Segoe UI",9,"italic")).pack(side="left", padx=(8,0))

        self.transcript  = self._textarea(f, height=10)
        self.eq_canvas   = tk.Canvas(f, width=230, height=54, bg=CARD, highlightthickness=0)
        self.eq_bars     = []; self.eq_animating = False
        self._stt_btn_frame = tk.Frame(f, bg=CARD); self._stt_btn_frame.pack(pady=(2,4))

        util = tk.Frame(f, bg=CARD); util.pack(pady=(0,6))
        self._btn(util, "Copy",  self.copy_transcript,  color=BLUE,  fg=BG, bold=True).pack(side="left", padx=4)
        self._btn(util, "Clear", self.clear_transcript, color=SURFACE).pack(side="left", padx=4)
        self.mini_btn = self._btn(util, "Mini",  self.minimized_mode,   color=SURFACE)
        self.mini_btn.pack(side="left", padx=4)
        self._stt_set_state("idle")

    def _stt_set_state(self, state):
        for w in self._stt_btn_frame.winfo_children(): w.destroy()
        if state == "idle":
            self._btn(self._stt_btn_frame, "Start",
                      self._stt_start, color=GREEN, fg=BG, bold=True).pack(side="left", padx=5)
        elif state == "listening":
            self._btn(self._stt_btn_frame, "Stop",
                      self._stt_stop, color=RED, fg=BG, bold=True).pack(side="left", padx=5)
        elif state == "stopped":
            self._btn(self._stt_btn_frame, "Continue",
                      self._stt_continue, color=GREEN, fg=BG, bold=True).pack(side="left", padx=5)
            self._btn(self._stt_btn_frame, "Overwrite",
                      self._stt_overwrite, color=YELLOW, fg=BG, bold=True).pack(side="left", padx=5)

    def _stt_start(self):
        if not self._ensure_mic_access():
            return
        if self.stt_engine.get() == "None installed":
            messagebox.showerror("No STT Engine",
                "No speech recognition engine installed.\n\npip install openai-whisper\npip install vosk")
            return
        self.is_listening = True
        self._stt_set_state("listening")
        self._set_stt_status("Listening...", GREEN)
        threading.Thread(target=self._listen_loop, daemon=True).start()
        self.start_equalizer()

    def _stt_stop(self):
        self.is_listening = False; self.stop_equalizer()
        self._set_stt_status("Stopped", FG_DIM)
        self.live_word_var.set(""); self._stt_set_state("stopped")

    def _stt_continue(self):
        self.is_listening = True; self._stt_set_state("listening")
        self._set_stt_status("Listening...", GREEN)
        threading.Thread(target=self._listen_loop, daemon=True).start()
        self.start_equalizer()

    def _stt_overwrite(self):
        self.transcript.delete("1.0", tk.END); self.live_word_var.set("")
        self.is_listening = True; self._stt_set_state("listening")
        self._set_stt_status("Listening...", GREEN)
        threading.Thread(target=self._listen_loop, daemon=True).start()
        self.start_equalizer()

    def _build_captions_frame(self):
        f = self._lf("Captions / Subtitles", fg_title=ORANGE)
        self._label(f, "Generate .srt/.vtt captions from an audio or video "
                        "file (uses Whisper - separate from the live mic "
                        "STT above).", fg=FG_DIM, font=("Segoe UI",8)
                    ).pack(anchor="w", padx=2, pady=(0,6))

        frow = tk.Frame(f, bg=CARD); frow.pack(fill="x", padx=2, pady=(0,4))
        self._btn(frow, "Choose File...", self._captions_choose_file,
                   color=BLUE, fg=BG).pack(side="left")
        self.captions_file_var = tk.StringVar(value="No file selected")
        tk.Label(frow, textvariable=self.captions_file_var, bg=CARD, fg=FG,
                 font=("Segoe UI",9), anchor="w"
                 ).pack(side="left", padx=8, fill="x", expand=True)

        opts = tk.Frame(f, bg=CARD); opts.pack(fill="x", padx=2, pady=(0,4))
        self._label(opts, "Spoken language:").pack(side="left")
        self.captions_lang_var = tk.StringVar(value=LANG_DISPLAY[0])
        ttk.Combobox(opts, textvariable=self.captions_lang_var,
                     values=LANG_DISPLAY, state="readonly",
                     width=16, font=("Segoe UI",9)).pack(side="left", padx=(4,14))
        self._label(opts, "Format:").pack(side="left")
        self.captions_format_var = tk.StringVar(value="SRT")
        ttk.Combobox(opts, textvariable=self.captions_format_var,
                     values=["SRT", "VTT"], state="readonly",
                     width=6, font=("Segoe UI",9)).pack(side="left", padx=4)

        st = tk.Frame(f, bg=CARD); st.pack(fill="x", padx=2, pady=(4,0))
        self.captions_status = self._label(st, "Choose a file to begin", fg=FG_DIM)
        self.captions_status.pack(side="left")

        self._btn(f, "Generate Captions", self._captions_generate,
                   color=GREEN, fg=BG, bold=True).pack(pady=(8,2))

        if not WHISPER_AVAILABLE:
            self._label(f, "Whisper is required for captions and isn't "
                            "installed (pip install openai-whisper).",
                        fg=RED, font=("Segoe UI",8)).pack(anchor="w", padx=2)
        elif not subtitles.ffmpeg_path():
            self._label(f, "ffmpeg wasn't found on your system PATH - "
                            "captions need it to read audio/video files.",
                        fg=YELLOW, font=("Segoe UI",8)).pack(anchor="w", padx=2)

    def _captions_choose_file(self):
        path = filedialog.askopenfilename(
            title="Choose audio or video file",
            filetypes=[("Audio/Video", "*.mp4 *.mkv *.mov *.avi *.webm "
                                        "*.wav *.mp3 *.m4a *.flac *.ogg"),
                       ("All files", "*.*")])
        if not path:
            return
        self._captions_input_path = path
        self.captions_file_var.set(os.path.basename(path))
        self.captions_status.config(text="Ready", fg=FG_DIM)

    def _captions_generate(self):
        path = getattr(self, "_captions_input_path", None)
        if not path:
            messagebox.showerror("No file", "Choose an audio or video file first.")
            return
        if not WHISPER_AVAILABLE:
            messagebox.showerror("Whisper not installed",
                "Captions need Whisper.\n\npip install openai-whisper")
            return
        if not subtitles.ffmpeg_path():
            messagebox.showerror("ffmpeg not found",
                "Captions need ffmpeg to extract audio from your file.\n\n"
                "Install it and make sure it's on your system PATH, "
                "then try again.")
            return
        threading.Thread(target=self._do_generate_captions,
                          args=(path,), daemon=True).start()

    def _do_generate_captions(self, path):
        self.root.after(0, lambda: self.captions_status.config(
            text="Extracting audio...", fg=YELLOW))
        tmp_wav = os.path.join(tempfile.gettempdir(),
                                f"avs_captions_{int(time.time())}.wav")
        try:
            subtitles.extract_audio(path, tmp_wav)

            self.root.after(0, lambda: self.captions_status.config(
                text="Loading Whisper model...", fg=YELLOW))
            model = get_whisper_model()
            wlang = LANG_WHISPER[self.captions_lang_var.get()]

            self.root.after(0, lambda: self.captions_status.config(
                text="Transcribing... this can take a while for longer "
                     "files", fg=YELLOW))
            words = subtitles.transcribe_words(model, tmp_wav, language=wlang)
            if not words:
                raise RuntimeError("No speech detected in this file.")

            captions = subtitles.chunk_into_captions(words)

            fmt = self.captions_format_var.get()
            ext = ".srt" if fmt == "SRT" else ".vtt"
            out_path = os.path.splitext(path)[0] + ext
            if fmt == "SRT":
                subtitles.write_srt(captions, out_path)
            else:
                subtitles.write_vtt(captions, out_path)

            self.root.after(0, lambda: self.captions_status.config(
                text="Done!", fg=GREEN))
            self.root.after(0, lambda: messagebox.showinfo(
                "Captions saved",
                f"Saved {len(captions)} captions to:\n{out_path}"))
        except Exception as e:
            print(f"[AVS] Captions failed: {e}")
            traceback.print_exc()
            self.root.after(0, lambda: self.captions_status.config(
                text="Error", fg=RED))
            self.root.after(0, lambda err=str(e): messagebox.showerror(
                "Captions failed", err))
        finally:
            if os.path.isfile(tmp_wav):
                try:
                    os.remove(tmp_wav)
                except OSError:
                    pass

    def _build_translator_frame(self):
        f = self._lf("Translator", fg_title=ORANGE)
        ob = tk.Frame(f, bg=CARD); ob.pack(fill="x", padx=2, pady=(0,6))
        tk.Label(ob, text="ONLINE", bg=CARD, fg=CYAN,
                 font=("Segoe UI",8,"bold")).pack(side="left")
        self._label(ob, "  Requires internet  (Google Translate)",
                    fg=FG_DIM, font=("Segoe UI",8)).pack(side="left")

        lr = tk.Frame(f, bg=CARD); lr.pack(fill="x", padx=2, pady=(0,6))
        self._label(lr, "From:").pack(side="left")
        self.tr_from_var = tk.StringVar(value=LANG_DISPLAY[0])
        ttk.Combobox(lr, textvariable=self.tr_from_var, values=LANG_DISPLAY,
                     state="readonly", width=16, font=("Segoe UI",9)).pack(side="left", padx=4)
        self._btn(lr, "Swap", self._tr_swap, color=SURFACE, padx=8).pack(side="left", padx=6)
        self._label(lr, "To:").pack(side="left")
        self.tr_to_var = tk.StringVar(value=LANG_DISPLAY[1])
        ttk.Combobox(lr, textvariable=self.tr_to_var, values=LANG_DISPLAY,
                     state="readonly", width=16, font=("Segoe UI",9)).pack(side="left", padx=4)

        sh = tk.Frame(f, bg=CARD); sh.pack(fill="x", padx=2)
        self._label(sh, "Source text:").pack(side="left")
        self._btn(sh, "Paste from STT", self._tr_paste_stt,
                  color=SURFACE, padx=8).pack(side="right")
        self.tr_input = self._textarea(f, height=5)

        tb = tk.Frame(f, bg=CARD); tb.pack(pady=(2,4))
        self._btn(tb, "Translate", self._do_translate, color=ORANGE, fg=BG, bold=True).pack(side="left", padx=5)
        self._btn(tb, "Clear All", self._tr_clear,     color=SURFACE).pack(side="left", padx=5)

        self._tr_prog_label, self._tr_progressbar_w = self._prog_widgets(f, "Trans")

        rh = tk.Frame(f, bg=CARD); rh.pack(fill="x", padx=2)
        self._label(rh, "Translation:").pack(side="left")
        self._btn(rh, "Copy result", self._tr_copy_result, color=BLUE, fg=BG).pack(side="right")
        self.tr_output = self._textarea(f, height=5)
        self.tr_output.config(state="disabled")
        self.tr_status = self._label(f, "", fg=FG_DIM); self.tr_status.pack(pady=(0,4))

    def _tr_swap(self):
        a, b = self.tr_from_var.get(), self.tr_to_var.get()
        self.tr_from_var.set(b); self.tr_to_var.set(a)

    def _tr_paste_stt(self):
        t = self.transcript.get("1.0", tk.END).strip()
        if not t: messagebox.showinfo("Nothing to paste", "STT transcript is empty."); return
        self.tr_input.delete("1.0", tk.END); self.tr_input.insert("1.0", t)

    def _tr_clear(self):
        self.tr_input.delete("1.0", tk.END)
        self.tr_output.config(state="normal"); self.tr_output.delete("1.0", tk.END)
        self.tr_output.config(state="disabled"); self.tr_status.config(text="")

    def _tr_copy_result(self):
        t = self.tr_output.get("1.0", tk.END).strip()
        if t:
            self.root.clipboard_clear(); self.root.clipboard_append(t)
            self.tr_status.config(text="Copied!", fg=GREEN)
            self.root.after(1800, lambda: self.tr_status.config(text=""))

    def _do_translate(self):
        text = self.tr_input.get("1.0", tk.END).strip()
        if not text: messagebox.showerror("Error", "Please enter text to translate."); return
        src = LANG_TR[self.tr_from_var.get()]; tgt = LANG_TR[self.tr_to_var.get()]
        self._tr_prog_label.config(text="Translating...", fg=ORANGE)
        self._tr_progressbar_w.start(12); self.tr_status.config(text="")
        threading.Thread(target=self._translate_thread, args=(text,src,tgt), daemon=True).start()

    def _translate_thread(self, text, src, tgt):
        # google_translate()'s urlopen(timeout=8) only bounds the socket
        # connect/read phase - hostname resolution (getaddrinfo) happens
        # first and isn't covered by that timeout at all. On a network
        # that silently drops (rather than rejects) traffic to
        # translate.googleapis.com - a firewall/DNS filter, some VPNs -
        # that lookup can hang indefinitely and the "Translating..."
        # spinner never resolves either way. Run the real call on its
        # own daemon thread and enforce our own hard timeout here so the
        # UI always gets an answer.
        result = {}
        done = threading.Event()

        def worker():
            try:
                result["value"] = google_translate(text, src, tgt)
            except Exception as e:
                result["error"] = str(e)
            finally:
                done.set()

        threading.Thread(target=worker, daemon=True).start()
        if not done.wait(timeout=12):
            self.root.after(0, lambda: self._tr_error(
                "Timed out after 12s reaching Google Translate - check your "
                "internet connection, or whether translate.googleapis.com "
                "is reachable from this network (some firewalls/VPNs block "
                "it silently)."))
            return
        if "error" in result:
            self.root.after(0, lambda: self._tr_error(result["error"]))
        else:
            self.root.after(0, lambda: self._show_translation(result["value"]))

    def _show_translation(self, r):
        self._tr_progressbar_w.stop(); self._tr_progressbar_w["value"] = 0
        self._tr_prog_label.config(text="")
        self.tr_output.config(state="normal"); self.tr_output.delete("1.0", tk.END)
        self.tr_output.insert("1.0", r); self.tr_output.config(state="disabled")
        self.tr_status.config(text="Done", fg=GREEN)

    def _tr_error(self, msg):
        self._tr_progressbar_w.stop(); self._tr_progressbar_w["value"] = 0
        self._tr_prog_label.config(text="")
        self.tr_status.config(text=f"Error: {msg}", fg=RED)

    def _build_voice_changer_frame(self):
        f = self._lf("Voice Changer", fg_title=ORANGE)

        # Info label
        info = tk.Frame(f, bg=CARD); info.pack(fill="x", padx=2, pady=(0,6))
        tk.Label(info, text="OPTIONAL", bg=CARD, fg=YELLOW,
                 font=("Segoe UI",8,"bold")).pack(side="left")
        self._label(info, "  Real-time voice conversion using TTS pipeline",
                    fg=FG_DIM, font=("Segoe UI",8)).pack(side="left")

        # Pitch control
        pc = tk.Frame(f, bg=CARD); pc.pack(fill="x", padx=2, pady=3)
        self._label(pc, "Pitch:").pack(side="left")
        self.vc_pitch = tk.DoubleVar(value=0.0)
        ttk.Scale(pc, from_=-12.0, to=12.0, orient="horizontal",
                  variable=self.vc_pitch, length=200).pack(side="left", padx=6)
        self._vc_pitch_lbl = tk.Label(pc, text="0.0", bg=CARD, fg=CYAN,
                                       font=("Segoe UI",9,"bold"), width=5)
        self._vc_pitch_lbl.pack(side="left")
        self.vc_pitch.trace_add("write", lambda *_: self._vc_pitch_lbl.config(
            text=f"{self.vc_pitch.get():+.1f}"))
        self._btn(pc, "Reset", lambda: self.vc_pitch.set(0.0),
                  color=SURFACE, padx=6).pack(side="left", padx=4)

        # Speed control for voice changer
        sc = tk.Frame(f, bg=CARD); sc.pack(fill="x", padx=2, pady=3)
        self._label(sc, "Speed:").pack(side="left")
        self.vc_speed = tk.DoubleVar(value=1.0)
        ttk.Scale(sc, from_=0.5, to=2.0, orient="horizontal",
                  variable=self.vc_speed, length=200).pack(side="left", padx=6)
        self._vc_speed_lbl = tk.Label(sc, text="1.0x", bg=CARD, fg=CYAN,
                                       font=("Segoe UI",9,"bold"), width=5)
        self._vc_speed_lbl.pack(side="left")
        self.vc_speed.trace_add("write", lambda *_: self._vc_speed_lbl.config(
            text=f"{self.vc_speed.get():.1f}x"))

        # Pipeline mode
        pl = tk.Frame(f, bg=CARD); pl.pack(fill="x", padx=2, pady=3)
        self._label(pl, "Mode:").pack(side="left")
        self.vc_mode = tk.StringVar(value="Pitch only")
        ttk.Combobox(pl, textvariable=self.vc_mode, state="readonly",
                     values=["Pitch only", "TTS pipeline (STT→TTS)"],
                     width=24, font=("Segoe UI",9)).pack(side="left", padx=6)

        # Status
        self._vc_status = self._label(f, "Stopped", fg=FG_DIM)
        self._vc_status.pack(anchor="w", padx=4, pady=2)

        # Buttons
        br = tk.Frame(f, bg=CARD); br.pack(pady=4)
        self._vc_start_btn = self._btn(br, "Start Voice Changer",
                                        self._vc_start, color=GREEN, fg=BG, bold=True)
        self._vc_start_btn.pack(side="left", padx=5)
        self._btn(br, "Stop", self._vc_stop, color=RED, fg=BG, bold=True).pack(side="left", padx=5)

        self._vc_running = False

    def _vc_start(self):
        if self._vc_running: return
        mode = self.vc_mode.get()
        if "TTS pipeline" in mode:
            if not self._ensure_mic_access():
                return
            # If the engine selected in the TTS tab is XTTS, this pipeline
            # will hit XTTS's CPML license requirement - resolve it here
            # on the main thread before the loop thread starts (same
            # reasoning as preview/save above).
            if self._is_xtts() and not self._ensure_engine_tos("xtts"):
                return
        self._vc_running = True
        self._vc_status.config(text="Running...", fg=GREEN)
        threading.Thread(target=self._vc_loop, daemon=True).start()

    def _vc_stop(self):
        self._vc_running = False
        self.root.after(0, lambda: self._vc_status.config(text="Stopped", fg=FG_DIM))

    def _vc_loop(self):
        import numpy as np
        mode = self.vc_mode.get()

        if "TTS pipeline" in mode:
            # STT -> TTS pipeline
            engine = self.stt_engine.get() if hasattr(self, 'stt_engine') else "Whisper (recommended)"
            lang_disp = self.stt_lang_var.get() if hasattr(self, 'stt_lang_var') else "English"
            mic_idx = self._resolve_mic_index()

            while self._vc_running:
                try:
                    with self._open_mic(mic_idx) as source:
                        self.recognizer.adjust_for_ambient_noise(source, duration=0.3)
                        self.root.after(0, lambda: self._vc_status.config(
                            text="Listening...", fg=GREEN))
                        audio = self.recognizer.listen(source, phrase_time_limit=5)

                    self.root.after(0, lambda: self._vc_status.config(
                        text="Processing...", fg=YELLOW))

                    # STT
                    raw = np.frombuffer(
                        audio.get_raw_data(convert_rate=16000, convert_width=2),
                        dtype=np.int16).astype(np.float32) / 32768.0
                    model = get_whisper_model()
                    result = model.transcribe(raw, fp16=False)
                    text = result["text"].strip()

                    if text and self._vc_running:
                        self.root.after(0, lambda t=text: self._vc_status.config(
                            text=f"Speaking: {t[:40]}", fg=CYAN))
                        # TTS output
                        import tempfile
                        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                        tmp.close()
                        sid = self.get_selected_speaker_id() if not self._is_xtts() else None
                        if sid:
                            TTS_ENGINES["vctk"].synthesize(text, sid, tmp.name)
                        else:
                            lang = LANG_XTTS.get(self.xtts_lang_var.get(), "en")
                            TTS_ENGINES["xtts"].synthesize(
                                text, self._xtts_voice_arg(), tmp.name, lang)
                        pygame.mixer.music.load(tmp.name)
                        pygame.mixer.music.play()
                        while pygame.mixer.music.get_busy() and self._vc_running:
                            time.sleep(0.1)
                except Exception as e:
                    if self._vc_running:
                        self.root.after(0, lambda err=str(e): self._vc_status.config(
                            text=f"Error: {err[:50]}", fg=RED))
                        time.sleep(1)
        else:
            # Pitch only mode - shift pitch of mic input
            self.root.after(0, lambda: self._vc_status.config(
                text="Pitch mode: play audio to hear effect", fg=YELLOW))
            time.sleep(1)
            self.root.after(0, lambda: self._vc_status.config(
                text="Tip: Use TTS pipeline mode for real-time voice changing", fg=FG_DIM))
            self._vc_running = False

    def _build_footer(self):
        f = tk.Frame(self._inner, bg=BG); f.pack(fill="x", padx=10, pady=(4,14))
        tk.Label(f, text="made by domore100", bg=BG, fg=FG_DIM,
                 font=("Segoe UI",8)).pack(side="right", padx=(0,2))
        tk.Label(f, text="v1  |", bg=BG, fg=BORDER,
                 font=("Segoe UI",8)).pack(side="right", padx=(0,4))

    # NOTE: The Model Download Manager UI/logic (_build_models_frame,
    # _check_models, _download_missing, etc.) lives below as module-level
    # functions and gets patched onto this class near the end of the file
    # (search "Patch these methods onto AIApp"). An earlier, differently-
    # implemented copy of these same methods used to live here and was
    # dead code — Python's later `AIApp._x = _x` assignments always won,
    # so this in-class copy never actually ran. Removed 2026-08-24 to
    # match the dedup already done for the duplicate __main__ block.

    def refresh_voice_list(self):
        filt = self.gender_filter.get(); entries = []
        for name, (sid, gender) in SPEAKER_MAP.items():
            if filt == "Fav"    and name not in self.favorites: continue
            if filt == "Male"   and gender != "M":              continue
            if filt == "Female" and gender != "F":              continue
            star  = "* " if name in self.favorites else ""
            gicon = "M " if gender == "M" else "F "
            entries.append((name in self.favorites, name, f"{star}{gicon}{disp(name,sid)}"))
        entries.sort(key=lambda x: (not x[0], x[1]))
        self._voice_name_map = {e[2]: e[1] for e in entries}
        display = [e[2] for e in entries]
        self.speaker_dropdown["values"] = display
        if display:
            cur = self.speaker_var.get(); cn = self._voice_name_map.get(cur)
            self.speaker_dropdown.set(
                next((d for d in display if self._voice_name_map.get(d) == cn), display[0]))
        self.update_fav_btn()

    def get_selected_speaker_id(self):
        real = self._voice_name_map.get(self.speaker_var.get())
        return SPEAKER_MAP[real][0] if real and real in SPEAKER_MAP else None

    def get_selected_real_name(self):
        return self._voice_name_map.get(self.speaker_var.get())

    def update_fav_btn(self):
        if self.fav_btn is None: return
        name = self.get_selected_real_name()
        self.fav_btn.config(
            text="Remove Favorite" if name in self.favorites else "Add to Favorites",
            fg=YELLOW if name in self.favorites else FG_DIM)

    def toggle_favorite(self):
        name = self.get_selected_real_name()
        if not name: return
        if name in self.favorites:
            self.favorites.discard(name)
            self.fav_status.config(text=f"Removed {name}", fg=RED)
        else:
            self.favorites.add(name)
            self.fav_status.config(text=f"Added {name}!", fg=YELLOW)
        persist_favorites(self.favorites); self.refresh_voice_list()
        self.root.after(2000, lambda: self.fav_status.config(text=""))

    def browse_folder(self):
        folder = filedialog.askdirectory()
        if folder: self.save_path_var.set(folder); persist_folder(folder)

    def get_next_filename(self):
        folder = self.save_path_var.get()
        if not folder: messagebox.showerror("Error", "Please select a save folder."); return None
        os.makedirs(folder, exist_ok=True)
        i = 1
        while True:
            p = os.path.join(folder, f"ai_voice{i}.wav")
            if not os.path.exists(p): return p
            i += 1

    def _get_text(self):
        t = self.text_entry.get("1.0", tk.END).strip()
        if not t: messagebox.showerror("Error", "Please enter some text first."); return None
        return t

    def _set_tts_status(self, t, c=FG_DIM): self.tts_status.config(text=t, fg=c)
    def _start_loading(self, msg): self._prog_label.config(text=msg, fg=BLUE); self._progressbar_w.start(12)
    def _stop_loading(self): self._progressbar_w.stop(); self._progressbar_w["value"]=0; self._prog_label.config(text="")
    def _is_xtts(self): return self.tts_engine.get().startswith("XTTS")

    def preview_voice(self):
        text = self._get_text()
        if not text: return
        sid = None
        if not self._is_xtts():
            sid = self.get_selected_speaker_id()
            if not sid: messagebox.showerror("Error", "Please select a valid voice."); return
        else:
            # XTTS may need a first-time download, which requires CPML
            # license agreement. Resolve that here on the main thread -
            # Coqui's own code would otherwise hang on input() from
            # inside the background preview thread below.
            if not self._ensure_engine_tos("xtts"):
                return
        self._start_loading("Loading model and generating speech...")
        self._set_tts_status("Generating preview...", YELLOW)
        threading.Thread(target=self._do_preview, args=(text,sid), daemon=True).start()

    def _do_preview(self, text, sid):
        try:
            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False); tmp.close()
            self.preview_temp = tmp.name
            if self._is_xtts():
                lang = LANG_XTTS[self.xtts_lang_var.get()]
                if lang not in XTTS_SUPPORTED: lang = "en"
                TTS_ENGINES["xtts"].synthesize(text, self._xtts_voice_arg(), tmp.name, lang)
            else:
                TTS_ENGINES["vctk"].synthesize(text, sid, tmp.name)
            pygame.mixer.music.load(tmp.name); pygame.mixer.music.play()
            self.root.after(0, self._stop_loading)
            self.root.after(0, lambda: self._set_tts_status("Playing preview...", GREEN))
        except Exception as e:
            print(f"[AVS] Preview failed: {e}")
            traceback.print_exc()
            if e.__cause__ is not None:
                print("[AVS] Underlying cause:")
                traceback.print_exception(type(e.__cause__), e.__cause__, e.__cause__.__traceback__)
            self.root.after(0, self._stop_loading)
            self.root.after(0, lambda: messagebox.showerror("Preview Error", str(e)))
            self.root.after(0, lambda: self._set_tts_status("Error", RED))

    def stop_preview(self):
        pygame.mixer.music.stop(); self._stop_loading()
        self._set_tts_status("Stopped", FG_DIM)

    def generate_voice(self):
        text = self._get_text()
        if not text: return
        sid = None
        if not self._is_xtts():
            sid = self.get_selected_speaker_id()
            if not sid: messagebox.showerror("Error", "Please select a valid voice."); return
        else:
            if not self._ensure_engine_tos("xtts"):
                return
        out = self.get_next_filename()
        if not out: return
        self._start_loading("Generating and saving audio...")
        self._set_tts_status("Saving audio...", YELLOW)
        threading.Thread(target=self._do_save, args=(text,sid,out), daemon=True).start()

    def _do_save(self, text, sid, out):
        try:
            if self._is_xtts():
                lang = LANG_XTTS[self.xtts_lang_var.get()]
                if lang not in XTTS_SUPPORTED: lang = "en"
                TTS_ENGINES["xtts"].synthesize(text, self._xtts_voice_arg(), out, lang)
            else:
                TTS_ENGINES["vctk"].synthesize(text, sid, out)
            self.root.after(0, self._stop_loading)
            self.root.after(0, lambda: messagebox.showinfo("Saved!", f"Audio saved to:\n{out}"))
            self.root.after(0, lambda: self._set_tts_status("Saved!", GREEN))
        except Exception as e:
            print(f"[AVS] Save failed: {e}")
            traceback.print_exc()
            if e.__cause__ is not None:
                print("[AVS] Underlying cause:")
                traceback.print_exception(type(e.__cause__), e.__cause__, e.__cause__.__traceback__)
            self.root.after(0, self._stop_loading)
            self.root.after(0, lambda: messagebox.showerror("TTS Error", str(e)))
            self.root.after(0, lambda: self._set_tts_status("Error", RED))

    def toggle_top(self): self.root.attributes("-topmost", self.always_on_top.get())

    def copy_transcript(self):
        t = self.transcript.get("1.0", tk.END).strip()
        if t:
            self.root.clipboard_clear(); self.root.clipboard_append(t)
            self._set_stt_status("Copied!", GREEN)
            self.root.after(1800, lambda: self._set_stt_status(
                "Listening..." if self.is_listening else "Press Start to begin", FG_DIM))

    def clear_transcript(self):
        self.transcript.delete("1.0", tk.END); self.live_word_var.set("")

    def _set_stt_status(self, t, c=FG_DIM):
        self.stt_dot.config(fg=c); self.status_label.config(text=t, fg=c)

    def _push_words(self, text):
        for word in text.split():
            self.root.after(0, lambda w=word: self.live_word_var.set(w))
            self.root.after(0, lambda w=word: self.transcript.insert(tk.END, w+" "))
            self.root.after(0, lambda: self.transcript.see(tk.END))
            time.sleep(0.07)
        self.root.after(0, lambda: self.live_word_var.set(""))

    def _listen_loop(self):
        engine    = self.stt_engine.get()
        lang_disp = self.stt_lang_var.get()
        mic_index = self._resolve_mic_index()

        if engine.startswith("Whisper"):
            import numpy as np
            self.root.after(0, lambda: self._set_stt_status("Loading Whisper model...", YELLOW))
            model = get_whisper_model()
            wlang = LANG_WHISPER[lang_disp]
            try:
                with self._open_mic(mic_index) as source:
                    self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                    while self.is_listening:
                        try:
                            self.root.after(0, lambda: self._set_stt_status("Listening...", GREEN))
                            self.root.after(0, lambda: self.live_word_var.set(""))
                            audio = self.recognizer.listen(source, phrase_time_limit=7)
                            self.root.after(0, lambda: self._set_stt_status("Processing...", YELLOW))
                            raw = np.frombuffer(
                                audio.get_raw_data(convert_rate=16000, convert_width=2),
                                dtype=np.int16).astype(np.float32)/32768.0
                            result = model.transcribe(raw, language=wlang, fp16=False)
                            text = result["text"].strip()
                            if text:
                                self._push_words(text)
                                self.root.after(0, lambda: self._set_stt_status("Listening...", GREEN))
                        except Exception:
                            self.root.after(0, lambda: self.live_word_var.set(""))
                            self.root.after(0, lambda: self._set_stt_status("Listening...", GREEN))
            except RuntimeError as e:
                self.root.after(0, lambda err=str(e): messagebox.showerror("Microphone Error", err))
                self.root.after(0, lambda: self._set_stt_status("Mic error", RED))
                self.root.after(0, lambda: self._stt_set_state("idle"))
                self.is_listening = False

        elif engine.startswith("Vosk"):
            from vosk import KaldiRecognizer
            vlang = LANG_VOSK[lang_disp]
            self.root.after(0, lambda: self._set_stt_status(f"Loading Vosk ({vlang})...", YELLOW))
            try:
                vosk_model = get_vosk_model(vlang)
            except FileNotFoundError as e:
                self.root.after(0, lambda: messagebox.showerror("Vosk Model Missing", str(e)))
                self.root.after(0, lambda: self._set_stt_status("Model not found", RED))
                self.root.after(0, lambda: self._stt_set_state("idle"))
                self.is_listening = False; return

            rec = KaldiRecognizer(vosk_model, 16000); rec.SetWords(True)
            try:
                with self._open_mic(mic_index) as source:
                    self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                    while self.is_listening:
                        try:
                            self.root.after(0, lambda: self._set_stt_status("Listening...", GREEN))
                            self.root.after(0, lambda: self.live_word_var.set(""))
                            audio = self.recognizer.listen(source, phrase_time_limit=7)
                            raw = audio.get_raw_data(convert_rate=16000, convert_width=2)
                            if rec.AcceptWaveform(raw):
                                result = json.loads(rec.Result())
                                text = result.get("text","").strip()
                            else:
                                partial = json.loads(rec.PartialResult())
                                text = partial.get("partial","").strip()
                            if text:
                                self._push_words(text)
                                self.root.after(0, lambda: self._set_stt_status("Listening...", GREEN))
                        except Exception:
                            self.root.after(0, lambda: self.live_word_var.set(""))
                            self.root.after(0, lambda: self._set_stt_status("Listening...", GREEN))
            except RuntimeError as e:
                self.root.after(0, lambda err=str(e): messagebox.showerror("Microphone Error", err))
                self.root.after(0, lambda: self._set_stt_status("Mic error", RED))
                self.root.after(0, lambda: self._stt_set_state("idle"))
                self.is_listening = False

        self.root.after(0, lambda: self._set_stt_status("Idle", FG_DIM))
        self.root.after(0, lambda: self.live_word_var.set(""))

    def minimized_mode(self):
        # Was a one-way trip before: it always hid the transcript and
        # showed the equalizer, with no code path back - "Mini" needs to
        # actually be a toggle so it can return to the text view.
        self._mini_mode = not getattr(self, "_mini_mode", False)
        if self._mini_mode:
            self.transcript.master.pack_forget()
            self.eq_canvas.pack(pady=5, before=self._stt_btn_frame)
            self.create_equalizer()
            if self.is_listening: self.start_equalizer()
            self.mini_btn.config(text="Full")
        else:
            self.stop_equalizer()
            self.eq_canvas.pack_forget()
            self.transcript.master.pack(fill="x", padx=2, pady=(0,4),
                                         before=self._stt_btn_frame)
            self.mini_btn.config(text="Mini")

    def create_equalizer(self):
        self.eq_canvas.delete("all"); self.eq_bars = []
        for i in range(10):
            x0 = i*22+4
            self.eq_bars.append(
                self.eq_canvas.create_rectangle(x0,46,x0+16,48,fill=BLUE,outline=""))

    def start_equalizer(self): self.eq_animating = True;  self._animate_eq()
    def stop_equalizer(self):  self.eq_animating = False

    def _animate_eq(self):
        if not self.eq_animating: return
        cols = [BLUE, PURPLE, GREEN]
        for i, bar in enumerate(self.eq_bars):
            h = random.randint(8,46); x0,_,x1,_ = self.eq_canvas.coords(bar)
            self.eq_canvas.coords(bar, x0, 50-h, x1, 50)
            self.eq_canvas.itemconfig(bar, fill=cols[i%3])
        self.root.after(180, self._animate_eq)


# ──────────────────────────────────────────────────────────────
#  MODEL DOWNLOAD MANAGER  (appended to AIApp)
# ──────────────────────────────────────────────────────────────

def _build_models_frame(self):
    f = self._lf("Models & Setup", fg_title=CYAN)

    tk.Label(f, text="Download or verify AI models required by the app.",
             bg=CARD, fg=FG_DIM, font=("Segoe UI",8)).pack(anchor="w", padx=2, pady=(0,6))

    # Status rows
    self._model_rows = {}
    # TTS engine rows are generated from the registry (engines/registry.py)
    # so adding a new engine there automatically gets a row here too -
    # nothing in this function needs to change.
    tts_engine_rows = [
        (key, spec.display_name, spec.approx_size, spec.description)
        for key, spec in TTS_ENGINES.items()
    ]
    models = [
        ("whisper",  "Whisper STT",           "~150 MB",  "Speech recognition"),
        *tts_engine_rows,
        ("tts_pkg",  "Coqui TTS package",     "pip",      "TTS engine"),
        ("whisper_pkg","Whisper package",      "pip",      "STT engine"),
        ("vosk_pkg", "Vosk package",           "pip",      "Lightweight STT"),
    ]

    for key, name, size, desc in models:
        row = tk.Frame(f, bg=CARD); row.pack(fill="x", pady=2, padx=2)
        tk.Label(row, text=name, bg=CARD, fg=FG,
                 font=("Segoe UI",9,"bold"), width=22, anchor="w").pack(side="left")
        tk.Label(row, text=size, bg=CARD, fg=FG_DIM,
                 font=("Segoe UI",8), width=8).pack(side="left")
        tk.Label(row, text=desc, bg=CARD, fg=FG_DIM,
                 font=("Segoe UI",8), width=26, anchor="w").pack(side="left")
        status = tk.Label(row, text="...", bg=CARD, fg=YELLOW,
                          font=("Segoe UI",8,"bold"), width=12)
        status.pack(side="left")
        btn = tk.Button(row, text="Install", bg=BLUE, fg=BG,
                        relief="flat", cursor="hand2", padx=8, pady=2,
                        font=("Segoe UI",8,"bold"), bd=0)
        self._model_rows[key] = (status, btn)

    # Progress
    self._dl_label = self._label(f, "", fg=FG_DIM, font=("Segoe UI",8))
    self._dl_label.pack(anchor="w", padx=2, pady=(6,0))
    self._dl_bar = ttk.Progressbar(f, style="Loading.Horizontal.TProgressbar",
                                    mode="indeterminate", length=500)
    self._dl_bar.pack(fill="x", padx=2, pady=(2,6))

    # Buttons
    br = tk.Frame(f, bg=CARD); br.pack(pady=4)
    self._btn(br, "Check All",        self._check_models,    color=SURFACE).pack(side="left", padx=4)
    self._btn(br, "Download Missing", self._download_missing, color=GREEN, fg=BG, bold=True).pack(side="left", padx=4)

    # Wire individual install buttons
    for key, name, size, desc in models:
        status, btn = self._model_rows[key]
        btn.config(command=lambda k=key: self._download_one(k))

    # Check on startup
    self.root.after(800, self._check_models)


def _set_model_status(self, key, ok, text=None):
    status, btn = self._model_rows[key]
    if ok is True:
        status.config(text=text or "OK", fg=GREEN)
        btn.pack_forget()
    elif ok is False:
        status.config(text=text or "Missing", fg=RED)
        btn.pack(side="right", padx=4)
    else:
        status.config(text=text or "Checking...", fg=YELLOW)
        btn.pack_forget()


def _check_models(self):
    threading.Thread(target=self._do_check_models, daemon=True).start()


def _do_check_models(self):
    import subprocess, sys

    def check_pkg(imp):
        try:
            __import__(imp)
            return True
        except ImportError:
            return False

    # Packages
    self.root.after(0, lambda: self._set_model_status("tts_pkg", None))
    ok = check_pkg("TTS")
    self.root.after(0, lambda o=ok: self._set_model_status("tts_pkg", o,
        "Installed" if o else "Missing"))

    self.root.after(0, lambda: self._set_model_status("whisper_pkg", None))
    ok = check_pkg("whisper")
    self.root.after(0, lambda o=ok: self._set_model_status("whisper_pkg", o,
        "Installed" if o else "Missing"))

    self.root.after(0, lambda: self._set_model_status("vosk_pkg", None))
    ok = check_pkg("vosk")
    self.root.after(0, lambda o=ok: self._set_model_status("vosk_pkg", o,
        "Installed" if o else "Missing"))

    # Whisper model
    self.root.after(0, lambda: self._set_model_status("whisper", None))
    whisper_local = os.path.join(_MODELS_BASE, "whisper", "small.pt")
    whisper_cache = os.path.join(os.path.expanduser("~"), ".cache", "whisper", "small.pt")
    min_whisper_bytes = 200 * 1024 * 1024  # "small" checkpoint is ~460MB
    def _file_ok(p):
        try:
            return os.path.isfile(p) and os.path.getsize(p) >= min_whisper_bytes
        except OSError:
            return False
    ok = _file_ok(whisper_local) or _file_ok(whisper_cache)
    self.root.after(0, lambda o=ok: self._set_model_status("whisper", o,
        "Ready" if o else "Missing"))

    # TTS engines (VCTK, XTTS today; any future engine added to
    # engines/registry.py is automatically checked here too)
    for key, spec in TTS_ENGINES.items():
        self.root.after(0, lambda k=key: self._set_model_status(k, None))
        try:
            ok = spec.is_installed()
        except Exception:
            ok = False
        self.root.after(0, lambda k=key, o=ok: self._set_model_status(
            k, o, "Ready" if o else "Missing"))


def _ensure_engine_tos(self, key):
    """Get license agreement for engine `key` via a GUI dialog (main
    thread only - never call this from inside a background thread).
    Returns True if the engine needs no agreement, or the user has
    agreed (now or in a past run); False if they declined.

    Driven entirely by TTS_ENGINES[key].requires_tos/tos_title/tos_text,
    so any future engine with its own license click-through (not just
    XTTS's CPML) is automatically covered without new code here.
    """
    if _engine_tos_already_agreed(key):
        return True
    spec = TTS_ENGINES[key]
    agreed = messagebox.askyesno(spec.tos_title, spec.tos_text)
    if agreed:
        os.makedirs(_MODELS_BASE, exist_ok=True)
        with open(_engine_tos_marker(key), "w", encoding="utf-8") as f:
            f.write("agreed")
        if key == "xtts":
            os.environ["COQUI_TOS_AGREED"] = "1"
    return agreed


def _download_missing(self):
    # Resolve XTTS's CPML license agreement here, on the main thread,
    # BEFORE any background thread starts. Coqui's own download code
    # would otherwise call input() from inside that thread to ask this
    # same question - which just hangs forever (no stdin to read from a
    # background thread, and no terminal at all in a packaged app).
    xtts_status, _ = self._model_rows["xtts"]
    xtts_missing = "Missing" in xtts_status.cget("text")
    self._xtts_tos_ok = self._ensure_engine_tos("xtts") if xtts_missing else True
    threading.Thread(target=self._do_download_missing, daemon=True).start()


PKG_MAP = {
    "tts_pkg":     "TTS",
    "whisper_pkg": "openai-whisper",
    "vosk_pkg":    "vosk",
}


def _install_pip_package(self, key):
    """pip-install the package behind a Downloads-panel package row
    (tts_pkg / whisper_pkg / vosk_pkg) and update its status. Shared by
    both "Download Missing" (bulk) and each row's own "Install" button
    - _do_download_model() used to have no branch at all for these
    three keys, so clicking "Install" on e.g. the Whisper package row
    ran pip install for nothing, then still reported "Done!" and
    re-checked the (unchanged, still-missing) import - "Done!" but
    still "Missing" was the visible symptom.
    """
    pip_name = PKG_MAP[key]
    self.root.after(0, lambda n=pip_name: self._dl_label.config(
        text=f"Installing {n}...", fg=YELLOW))
    import subprocess, sys
    r = subprocess.run(
        [sys.executable, "-m", "pip", "install", pip_name],
        capture_output=True, text=True)
    ok = r.returncode == 0
    self.root.after(0, lambda k=key, o=ok: self._set_model_status(
        k, o, "Installed" if o else "Failed"))
    if not ok:
        err = (r.stderr or r.stdout or "").strip().splitlines()[-1:] or ["pip install failed"]
        self.root.after(0, lambda e=err[0]: self._dl_label.config(
            text=f"Error installing {pip_name}: {e[:60]}", fg=RED))

    # TTS needs torch, which isn't declared as its pip dependency here
    # (deliberately - the CPU wheel comes from PyTorch's own index).
    if key == "tts_pkg" and ok:
        self.root.after(0, lambda: self._dl_label.config(
            text="Installing PyTorch (large download)...", fg=YELLOW))
        subprocess.run([sys.executable, "-m", "pip", "install",
                        "torch", "torchaudio",
                        "--index-url", "https://download.pytorch.org/whl/cpu"],
                       capture_output=True)
    return ok


def _do_download_missing(self):
    self.root.after(0, lambda: self._dl_bar.start(12))
    self._download_in_progress = True

    missing_pkgs  = []
    missing_models = []

    for key in ["tts_pkg", "whisper_pkg", "vosk_pkg"]:
        status, _ = self._model_rows[key]
        if "Missing" in status.cget("text"):
            missing_pkgs.append(key)

    for key in ["whisper", "vctk", "xtts"]:
        status, _ = self._model_rows[key]
        if "Missing" in status.cget("text"):
            missing_models.append(key)

    # If the user declined the XTTS license dialog, don't attempt that
    # download at all - Coqui's code would otherwise hang trying to ask
    # for the same agreement via input() with no stdin available.
    if "xtts" in missing_models and not getattr(self, "_xtts_tos_ok", True):
        missing_models.remove("xtts")
        self.root.after(0, lambda: self._set_model_status(
            "xtts", False, "License declined"))

    # Install packages
    for key in missing_pkgs:
        self._install_pip_package(key)

    # Download models
    for key in missing_models:
        label = f"Downloading {key} model..."
        if key == "xtts":
            label = ("Downloading XTTS-v2 (~1.8GB - this can take several "
                      "minutes, please don't close the app)...")
        self.root.after(0, lambda t=label: self._dl_label.config(text=t, fg=YELLOW))
        self._do_download_model(key)

    self._download_in_progress = False
    self.root.after(0, lambda: self._dl_bar.stop())
    self.root.after(0, lambda: self._dl_label.config(text="Done!", fg=GREEN))
    self.root.after(0, self._check_models)


def _download_one(self, key):
    if key == "xtts" and not self._ensure_engine_tos("xtts"):
        self._set_model_status("xtts", False, "License declined")
        return
    threading.Thread(target=lambda: self._do_download_one(key), daemon=True).start()


def _do_download_one(self, key):
    self.root.after(0, lambda: self._dl_bar.start(12))
    self._download_in_progress = True
    label = f"Downloading {key}..."
    if key == "xtts":
        label = ("Downloading XTTS-v2 (~1.8GB - this can take several "
                  "minutes, please don't close the app)...")
    self.root.after(0, lambda t=label: self._dl_label.config(text=t, fg=YELLOW))
    self._do_download_model(key)
    self._download_in_progress = False
    self.root.after(0, lambda: self._dl_bar.stop())
    self.root.after(0, lambda: self._dl_label.config(text="Done!", fg=GREEN))
    self.root.after(0, self._check_models)


def _do_download_model(self, key):
    try:
        if key in PKG_MAP:
            self._install_pip_package(key)
        elif key == "whisper":
            import whisper
            whisper.load_model("small")
            self.root.after(0, lambda: self._set_model_status("whisper", True, "Ready"))
        elif key in TTS_ENGINES:
            def on_progress(downloaded, total, k=key):
                mb_done = downloaded / (1024 * 1024)
                if total:
                    # Known size (VCTK, and any future engine whose host
                    # sends Content-Length): real determinate % bar.
                    pct = min(100, int(downloaded * 100 / total))
                    mb_total = total / (1024 * 1024)
                    def _update():
                        if str(self._dl_bar["mode"]) != "determinate":
                            self._dl_bar.stop()
                            self._dl_bar.config(mode="determinate", maximum=100)
                        self._dl_bar["value"] = pct
                        self._dl_label.config(
                            text=f"Downloading {k}... {mb_done:.0f} MB / "
                                 f"{mb_total:.0f} MB ({pct}%)", fg=YELLOW)
                else:
                    # Unknown size (XTTS-v2's host omits Content-Length) -
                    # no % is possible, so keep the bar animating in
                    # indeterminate mode and just show a live MB counter
                    # instead of freezing on stale "0 MB / 0 MB" numbers.
                    def _update():
                        if str(self._dl_bar["mode"]) != "indeterminate":
                            self._dl_bar.config(mode="indeterminate")
                            self._dl_bar.start(12)
                        self._dl_label.config(
                            text=f"Downloading {k}... {mb_done:.0f} MB "
                                 f"downloaded (total size unknown)", fg=YELLOW)
                self.root.after(0, _update)

            TTS_ENGINES[key].download(progress_cb=on_progress)
            self.root.after(0, lambda k=key: self._set_model_status(k, True, "Ready"))
    except Exception as e:
        self.root.after(0, lambda k=key, err=str(e): self._set_model_status(
            k, False, "Failed"))
        self.root.after(0, lambda err=str(e): self._dl_label.config(
            text=f"Error: {err[:60]}", fg=RED))
    finally:
        # Always leave the bar back in indeterminate mode for whatever
        # download/install comes next - not every download can report
        # real progress (pip installs, whisper's own downloader), so
        # this is the safe default the next step starts from.
        def _reset_bar():
            self._dl_bar.config(mode="indeterminate")
            self._dl_bar.start(12)
        self.root.after(0, _reset_bar)


# Patch these methods onto AIApp
AIApp._build_models_frame    = _build_models_frame
AIApp._set_model_status      = _set_model_status
AIApp._check_models          = _check_models
AIApp._do_check_models       = _do_check_models
AIApp._install_pip_package   = _install_pip_package
AIApp._download_missing      = _download_missing
AIApp._do_download_missing   = _do_download_missing
AIApp._download_one          = _download_one
AIApp._do_download_one       = _do_download_one
AIApp._do_download_model     = _do_download_model
AIApp._ensure_engine_tos      = _ensure_engine_tos


if __name__ == "__main__":
    root = tk.Tk()
    app  = AIApp(root)
    root.mainloop()
