import os
import sys

# Early crash logger - writes to app folder before anything else loads
try:
    _log_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'startup.log')
    _log = open(_log_path, 'w')
    _log.write('Starting...\n'); _log.flush()
    def _logw(msg):
        _log.write(msg + '\n'); _log.flush()
except:
    def _logw(msg): pass

_logw('Python imports starting')
import tkinter as tk
_logw('tkinter ok')
from tkinter import messagebox, ttk, filedialog
import threading
import random
import tempfile
import time
import urllib.request
import urllib.parse
import json
import speech_recognition as sr
_logw("speech_recognition ok")
import pygame
_logw("pygame ok")
_logw(f"BASE dir: {_BASE}")
_logw("About to create Tk window")

# ──────────────────────────────────────────────────────────────
#  PERSISTENT CONFIG
# ──────────────────────────────────────────────────────────────
LAST_FOLDER     = r"C:/Users/Dominik Žibert/Documents/ai_voice/audio"  # auto-updates on browse
SAVED_FAVORITES = ['Ivy', 'Kinsley', 'Leah', 'Lucas', 'Madeline', 'Olivia']  # auto-updates when you star/unstar voices

# ──────────────────────────────────────────────────────────────
#  MODEL PATHS
# ──────────────────────────────────────────────────────────────
_BASE             = os.path.dirname(os.path.realpath(__file__))

# Set espeak path if bundled with app (Windows installer bundles it)
_ESPEAK_PATH = os.path.join(_BASE, "espeak")
if os.path.isdir(_ESPEAK_PATH):
    os.environ["PHONEMIZER_ESPEAK_PATH"] = _ESPEAK_PATH
    os.environ["ESPEAK_DATA_PATH"]       = os.path.join(_ESPEAK_PATH, "espeak-ng-data")
VCTK_MODEL_PATH   = os.path.join(_BASE, "models", "vctk")
XTTS_MODEL_PATH   = os.path.join(_BASE, "models", "xtts_v2")
WHISPER_MODEL_DIR = os.path.join(_BASE, "models", "whisper")
VOSK_MODEL_DIR    = os.path.join(_BASE, "models", "vosk")

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
_tts_vctk      = None
_tts_xtts      = None
_whisper_model = None
_vosk_models   = {}

def get_tts_vctk():
    global _tts_vctk
    if _tts_vctk is None:
        from TTS.api import TTS
        if os.path.isdir(VCTK_MODEL_PATH):
            _tts_vctk = TTS(model_path=VCTK_MODEL_PATH,
                             config_path=os.path.join(VCTK_MODEL_PATH, "config.json"),
                             progress_bar=False, gpu=False)
        else:
            _tts_vctk = TTS(model_name="tts_models/en/vctk/vits",
                             progress_bar=False, gpu=False)
    return _tts_vctk

def get_tts_xtts():
    global _tts_xtts
    if _tts_xtts is None:
        import torch
        import torch.serialization
        try:
            from TTS.tts.configs.xtts_config import XttsConfig
            torch.serialization.add_safe_globals([XttsConfig])
        except Exception:
            pass
        from TTS.api import TTS
        if os.path.isdir(XTTS_MODEL_PATH):
            _tts_xtts = TTS(model_path=XTTS_MODEL_PATH,
                             config_path=os.path.join(XTTS_MODEL_PATH, "config.json"),
                             progress_bar=False, gpu=False)
        else:
            _tts_xtts = TTS(model_name="tts_models/multilingual/multi-dataset/xtts_v2",
                             progress_bar=False, gpu=False)
    return _tts_xtts

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

XTTS_SUPPORTED = {"en","sl","ru","de","fr","es","it","ja","zh","pt","pl","cs","nl","ar","ko","hr","tr","hu","ro"}

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
#  MIC PERMISSION DIALOG
# ──────────────────────────────────────────────────────────────
def ask_mic_permission(root):
    dlg = tk.Toplevel(root); dlg.title("Microphone Access")
    dlg.configure(bg=CARD); dlg.resizable(False, False); dlg.grab_set()
    root.update_idletasks()
    x = root.winfo_x() + root.winfo_width()  // 2 - 220
    y = root.winfo_y() + root.winfo_height() // 2 - 100
    dlg.geometry(f"440x200+{x}+{y}")
    tk.Label(dlg, text="Microphone Permission",
             bg=CARD, fg=PURPLE, font=("Segoe UI",12,"bold")).pack(pady=(18,4))
    tk.Label(dlg,
             text=("This app needs your microphone for Speech-to-Text.\n\n"
                   "If blocked, go to:\n"
                   "Windows Settings > Privacy > Microphone > Allow apps to access."),
             bg=CARD, fg=FG, font=("Segoe UI",9), justify="center", wraplength=400
             ).pack(pady=(0,14))
    result = tk.BooleanVar(value=False)
    def allow(): result.set(True);  dlg.destroy()
    def deny():  result.set(False); dlg.destroy()
    brow = tk.Frame(dlg, bg=CARD); brow.pack()
    for txt, cmd, col in [("Allow", allow, GREEN), ("Deny", deny, RED)]:
        tk.Button(brow, text=txt, command=cmd, bg=col, fg=BG, relief="flat",
                  cursor="hand2", padx=16, pady=6,
                  font=("Segoe UI",9,"bold"), bd=0).pack(side="left", padx=8)
    dlg.wait_window()
    return result.get()

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

        _logw("mixer init")
        pygame.mixer.init()
        _logw("mixer ok")
        self.favorites    = set(SAVED_FAVORITES)
        self.preview_temp = None
        self.fav_btn      = None
        self.fav_status   = None
        self.is_listening = False

        self._scroller = ScrollableFrame(root)
        self._scroller.pack(fill="both", expand=True)
        self._inner = self._scroller.inner

        _logw("building models frame")
        self._build_models_frame()
        _logw("models frame ok")
        self._build_tts_frame()
        _logw("building stt frame")
        self._build_stt_frame()
        _logw("stt frame ok")
        self._build_translator_frame()
        self._build_footer()

        root.after(150, lambda: self._scroller.bind_all_mousewheel(self._inner))
        root.after(1000, self._request_mic_permission)

    def _request_mic_permission(self):
        try:
            allowed = ask_mic_permission(self.root)
            self._mic_allowed = allowed
            if allowed:
                self._stt_note.config(text="Microphone access granted", fg=GREEN)
                self.root.after(3000, lambda: self._stt_note.config(
                    text="Don't forget to choose the right microphone!", fg=YELLOW))
            else:
                self._stt_note.config(text="Microphone access denied", fg=RED)
        except Exception as e:
            print(f"Mic permission error: {e}")
            self._mic_allowed = True  # assume allowed if dialog fails

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
        self.xtts_lang_var = tk.StringVar(value=LANG_DISPLAY[0])
        ttk.Combobox(self._xtts_lang_frame, textvariable=self.xtts_lang_var,
                     values=LANG_DISPLAY, state="readonly",
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
                    "XTTS-v2  17 languages including Slovenian, Russian, English",
                    fg=FG_DIM, font=("Segoe UI",8)).pack(anchor="w", padx=4, pady=4)

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
        try:
            self.mics = sr.Microphone.list_microphone_names()
        except Exception:
            self.mics = []
        best_idx          = auto_detect_mic(self.mics)
        self.selected_mic = tk.StringVar(value=self.mics[best_idx] if self.mics else "None")
        ttk.Combobox(mic_row, textvariable=self.selected_mic,
                     values=self.mics, state="readonly",
                     width=40, font=("Segoe UI",9)).pack(side="left", padx=6)
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
        self._btn(util, "Mini",  self.minimized_mode,   color=SURFACE).pack(side="left", padx=4)
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
        if not self._mic_allowed:
            if not ask_mic_permission(self.root): return
            self._mic_allowed = True
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
        try:
            r = google_translate(text, src, tgt)
            self.root.after(0, lambda: self._show_translation(r))
        except Exception as e:
            self.root.after(0, lambda: self._tr_error(str(e)))

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

    def _build_footer(self):
        f = tk.Frame(self._inner, bg=BG); f.pack(fill="x", padx=10, pady=(4,14))
        tk.Label(f, text="made by domore100", bg=BG, fg=FG_DIM,
                 font=("Segoe UI",8)).pack(side="right", padx=(0,2))
        tk.Label(f, text="v1  |", bg=BG, fg=BORDER,
                 font=("Segoe UI",8)).pack(side="right", padx=(0,4))

    def refresh_voice_list(self):
        filt = self.gender_filter.get(); entries = []
        for name, (sid, gender) in SPEAKER_MAP.items():
            if filt == "Fav"    and name not in self.favorites: continue
            if filt == "Male"   and gender != "M":              continue
            if filt == "Female" and gender != "F":              continue
            star  = "★ " if name in self.favorites else ""
            entries.append((name in self.favorites, name, f"{star}{name}"))
        entries.sort(key=lambda x: (not x[0], x[1]))
        self._voice_name_map = {e[2]: e[1] for e in entries}  # display -> real name
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
                get_tts_xtts().tts_to_file(text=text, language=lang, file_path=tmp.name)
            else:
                get_tts_vctk().tts_to_file(text=text, speaker=sid, file_path=tmp.name)
            pygame.mixer.music.load(tmp.name); pygame.mixer.music.play()
            self.root.after(0, self._stop_loading)
            self.root.after(0, lambda: self._set_tts_status("Playing preview...", GREEN))
        except Exception as e:
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
                get_tts_xtts().tts_to_file(text=text, language=lang, file_path=out)
            else:
                get_tts_vctk().tts_to_file(text=text, speaker=sid, file_path=out)
            self.root.after(0, self._stop_loading)
            self.root.after(0, lambda: messagebox.showinfo("Saved!", f"Audio saved to:\n{out}"))
            self.root.after(0, lambda: self._set_tts_status("Saved!", GREEN))
        except Exception as e:
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
        mic_index = self.mics.index(self.selected_mic.get())

        if engine.startswith("Whisper"):
            import numpy as np
            self.root.after(0, lambda: self._set_stt_status("Loading Whisper model...", YELLOW))
            model = get_whisper_model()
            wlang = LANG_WHISPER[lang_disp]
            with sr.Microphone(device_index=mic_index, sample_rate=16000) as source:
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
            with sr.Microphone(device_index=mic_index, sample_rate=16000) as source:
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

        self.root.after(0, lambda: self._set_stt_status("Idle", FG_DIM))
        self.root.after(0, lambda: self.live_word_var.set(""))

    def minimized_mode(self):
        self.transcript.master.pack_forget()
        self.eq_canvas.pack(pady=5); self.create_equalizer()
        if self.is_listening: self.start_equalizer()

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

def _build_models_frame(self):
    f = self._lf("Models & Setup", fg_title=CYAN)

    tk.Label(f, text="Download or verify AI models required by the app.",
             bg=CARD, fg=FG_DIM, font=("Segoe UI",8)).pack(anchor="w", padx=2, pady=(0,6))

    # Status rows
    self._model_rows = {}
    models = [
        ("whisper",  "Whisper STT",           "~150 MB",  "Speech recognition"),
        ("vctk",     "VCTK English voices",    "~100 MB",  "English TTS (100+ voices)"),
        ("xtts",     "XTTS-v2 Multilingual",  "~2 GB",    "Multilingual TTS (17 languages)"),
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
    whisper_local = os.path.join(_BASE, "models", "whisper", "small.pt")
    whisper_cache = os.path.join(os.path.expanduser("~"), ".cache", "whisper", "small.pt")
    ok = os.path.isfile(whisper_local) or os.path.isfile(whisper_cache)
    self.root.after(0, lambda o=ok: self._set_model_status("whisper", o,
        "Ready" if o else "Missing"))

    # VCTK
    self.root.after(0, lambda: self._set_model_status("vctk", None))
    vctk_local = os.path.join(_BASE, "models", "vctk")
    lad = os.environ.get("LOCALAPPDATA", "")
    tts_cache = os.path.join(lad, "tts")
    vctk_cached = os.path.isdir(tts_cache) and any(
        "vctk" in d for d in os.listdir(tts_cache))
    ok = os.path.isdir(vctk_local) or vctk_cached
    self.root.after(0, lambda o=ok: self._set_model_status("vctk", o,
        "Ready" if o else "Missing"))

    # XTTS
    self.root.after(0, lambda: self._set_model_status("xtts", None))
    xtts_local = os.path.join(_BASE, "models", "xtts_v2")
    xtts_cached = os.path.isdir(tts_cache) and any(
        "xtts_v2" in d for d in os.listdir(tts_cache))
    ok = os.path.isdir(xtts_local) or xtts_cached
    self.root.after(0, lambda o=ok: self._set_model_status("xtts", o,
        "Ready" if o else "Missing"))


def _download_missing(self):
    threading.Thread(target=self._do_download_missing, daemon=True).start()


def _do_download_missing(self):
    self.root.after(0, lambda: self._dl_bar.start(12))

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

    # Install packages
    pkg_map = {
        "tts_pkg":     "TTS",
        "whisper_pkg": "openai-whisper",
        "vosk_pkg":    "vosk",
    }
    for key in missing_pkgs:
        pip_name = pkg_map[key]
        self.root.after(0, lambda n=pip_name: self._dl_label.config(
            text=f"Installing {n}...", fg=YELLOW))
        import subprocess, sys
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install", pip_name],
            capture_output=True, text=True)
        ok = r.returncode == 0
        self.root.after(0, lambda k=key, o=ok: self._set_model_status(
            k, o, "Installed" if o else "Failed"))

    # Also install torch if TTS was missing
    if "tts_pkg" in missing_pkgs:
        self.root.after(0, lambda: self._dl_label.config(
            text="Installing PyTorch (large download)...", fg=YELLOW))
        import subprocess, sys
        subprocess.run([sys.executable, "-m", "pip", "install",
                        "torch", "torchaudio",
                        "--index-url", "https://download.pytorch.org/whl/cpu"],
                       capture_output=True)

    # Download models
    for key in missing_models:
        self.root.after(0, lambda k=key: self._dl_label.config(
            text=f"Downloading {k} model...", fg=YELLOW))
        self._do_download_model(key)

    self.root.after(0, lambda: self._dl_bar.stop())
    self.root.after(0, lambda: self._dl_label.config(text="Done!", fg=GREEN))
    self.root.after(0, self._check_models)


def _download_one(self, key):
    threading.Thread(target=lambda: self._do_download_one(key), daemon=True).start()


def _do_download_one(self, key):
    self.root.after(0, lambda: self._dl_bar.start(12))
    self.root.after(0, lambda: self._dl_label.config(
        text=f"Downloading {key}...", fg=YELLOW))
    self._do_download_model(key)
    self.root.after(0, lambda: self._dl_bar.stop())
    self.root.after(0, lambda: self._dl_label.config(text="Done!", fg=GREEN))
    self.root.after(0, self._check_models)


def _do_download_model(self, key):
    import subprocess, sys
    try:
        if key == "whisper":
            import whisper
            whisper.load_model("small")
            self.root.after(0, lambda: self._set_model_status("whisper", True, "Ready"))
        elif key == "vctk":
            from TTS.api import TTS
            TTS(model_name="tts_models/en/vctk/vits", progress_bar=False, gpu=False)
            self.root.after(0, lambda: self._set_model_status("vctk", True, "Ready"))
        elif key == "xtts":
            import torch, torch.serialization
            try:
                from TTS.tts.configs.xtts_config import XttsConfig
                torch.serialization.add_safe_globals([XttsConfig])
            except Exception:
                pass
            from TTS.api import TTS
            TTS(model_name="tts_models/multilingual/multi-dataset/xtts_v2",
                progress_bar=False, gpu=False)
            self.root.after(0, lambda: self._set_model_status("xtts", True, "Ready"))
    except Exception as e:
        self.root.after(0, lambda k=key, err=str(e): self._set_model_status(
            k, False, "Failed"))
        self.root.after(0, lambda err=str(e): self._dl_label.config(
            text=f"Error: {err[:60]}", fg=RED))


# Patch these methods onto AIApp
AIApp._build_models_frame    = _build_models_frame
AIApp._set_model_status      = _set_model_status
AIApp._check_models          = _check_models
AIApp._do_check_models       = _do_check_models
AIApp._download_missing      = _download_missing
AIApp._do_download_missing   = _do_download_missing
AIApp._download_one          = _download_one
AIApp._do_download_one       = _do_download_one
AIApp._do_download_model     = _do_download_model

if __name__ == "__main__":
    _logw("Starting UI")
    try:
        root = tk.Tk()
        _logw("Tk created")
        app  = AIApp(root)
        root.mainloop()
    except Exception as e:
        import traceback
        print("\n=== FATAL ERROR ===")
        traceback.print_exc()
        print("===================")
        input("Press Enter to close...")


# ──────────────────────────────────────────────────────────────
#  MODEL DOWNLOAD MANAGER  (appended to AIApp)
# ──────────────────────────────────────────────────────────────
