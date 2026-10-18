"""Voice finder - pick a TTS voice by traits instead of by name.

How it works
------------
Every installed voice speaks one short fixed sentence; the audio is measured
(median pitch, how much high-frequency energy it carries, how much the pitch
moves) and the numbers are cached in a small JSON file, so each voice is
analysed only once. The sliders then rank the voices by how close they are.

A slider position is compared with the voice's *rank* among all analysed
voices (0 = lowest, 100 = highest), so "50" always means "typical" no matter
which engines are installed.

`measure()` and `rank_voices()` have no GUI dependency; `VoiceFinder` is the
Tk window that ties them to the app.
"""
import json
import math
import os
import tempfile
import threading
import time

import numpy as np

CACHE_VERSION = 1

# (key, title, low-end label, high-end label)
TRAITS = [
    ("pitch",  "Pitch",        "Low",  "High"),
    ("bright", "Brightness",   "Dark", "Bright"),
    ("lively", "Liveliness",   "Calm", "Lively"),
]

LANG_NAMES = {
    "en": "English", "es": "Spanish", "fr": "French", "hi": "Hindi",
    "it": "Italian", "ja": "Japanese", "pt": "Portuguese", "zh": "Chinese",
}

# Kokoro: the first letter of the voice id is its language
KOKORO_LANG = {"a": "en", "b": "en", "e": "es", "f": "fr", "h": "hi",
               "i": "it", "j": "ja", "p": "pt", "z": "zh"}

SAMPLES = {
    "en": "The quick brown fox jumps over the lazy dog. Then it takes a long, quiet nap.",
    "es": "El veloz zorro marron salta sobre el perro perezoso. Luego duerme tranquilo.",
    "fr": "Le renard brun saute par-dessus le chien paresseux. Ensuite il dort tranquillement.",
    "hi": "नमस्ते, आप कैसे हैं? मैं बहुत अच्छा हूँ।",
    "it": "La volpe veloce salta sopra il cane pigro. Poi dorme tranquilla.",
    "ja": "こんにちは、今日はとてもいい天気ですね。散歩に行きましょう。",
    "pt": "A rapida raposa marrom pula sobre o cao preguicoso. Depois dorme em silencio.",
    "zh": "你好，今天天气很好。我们一起去散步吧。",
}


# ───────────────────────── measuring ─────────────────────────
def measure(path):
    """Measure one voice sample. Returns a dict {f0, bright, lively} or None
    when no clear voiced speech was found.

    f0      median pitch in Hz
    bright  energy above 3 kHz relative to the energy below it, in dB
    lively  spread of the pitch (10th-90th percentile) in semitones
    """
    import librosa
    import soundfile as sf

    y, sr = sf.read(path, dtype="float32", always_2d=True)
    y = y.mean(axis=1)
    if len(y) < sr // 2:
        return None
    if sr != 16000:
        y = librosa.resample(y, orig_sr=sr, target_sr=16000)
        sr = 16000
    y, _ = librosa.effects.trim(y, top_db=35)
    if len(y) < sr // 2:
        return None
    y = y / (np.max(np.abs(y)) + 1e-9)

    f0, voiced, _p = librosa.pyin(y, fmin=65, fmax=450, sr=sr,
                                  frame_length=1024, hop_length=256)
    f0 = f0[voiced & np.isfinite(f0)]
    if len(f0) < 12:
        return None
    med = float(np.median(f0))
    st = 12.0 * np.log2(f0 / med)
    lively = float(np.percentile(st, 90) - np.percentile(st, 10))

    # brightness from loud (voiced) frames only
    S = np.abs(librosa.stft(y, n_fft=512, hop_length=256)) ** 2
    freqs = librosa.fft_frequencies(sr=sr, n_fft=512)
    frame_e = S.sum(axis=0)
    keep = frame_e > 0.15 * np.median(frame_e[frame_e > 0])
    if keep.sum() < 8:
        return None
    lo = S[(freqs >= 80) & (freqs < 3000)][:, keep].sum()
    hi = S[freqs >= 3000][:, keep].sum()
    bright = float(10.0 * math.log10((hi + 1e-12) / (lo + 1e-12)))
    return {"f0": round(med, 1), "bright": round(bright, 2),
            "lively": round(lively, 2)}


# ───────────────────────── ranking ─────────────────────────
def _ranks(values):
    """Percentile rank 0..100 for each value (ties share a rank)."""
    arr = np.asarray(values, dtype=float)
    n = len(arr)
    if n <= 1:
        return [50.0] * n
    order = np.sort(arr)
    lo = np.searchsorted(order, arr, side="left")
    hi = np.searchsorted(order, arr, side="right")
    return [float(x) for x in ((lo + hi - 1) / 2.0) / (n - 1) * 100.0]


def trait_values(entry):
    return {"pitch": entry["f0"], "bright": entry["bright"],
            "lively": entry["lively"]}


def rank_voices(analysed, wanted, gender=None, lang=None, limit=40):
    """analysed: list of dicts with keys engine, voice, label, gender, lang,
    f0, bright, lively (gender may be None, lang may be "*" = any language).
    wanted: {trait key: slider 0..100} for the traits that are switched on.
    Returns the best matches first, each with 'score' (0..100) and 'g'
    (the gender used, which for voices without one is guessed from pitch).
    """
    if not analysed:
        return []
    pct = {}
    for key, *_ in TRAITS:
        pct[key] = _ranks([trait_values(e)[key] for e in analysed])
    out = []
    for i, e in enumerate(analysed):
        g = e.get("gender") or ("M" if e["f0"] < 165 else "F")
        if gender and g != gender:
            continue
        if lang and e.get("lang") not in (lang, "*"):
            continue
        if wanted:
            d2 = sum((pct[k][i] - v) ** 2 for k, v in wanted.items())
            dist = math.sqrt(d2 / len(wanted))          # 0..100
            score = max(0.0, 100.0 - dist)
        else:
            score = 100.0
        r = dict(e)
        r["score"] = score
        r["g"] = g
        r["guessed"] = not e.get("gender")
        out.append(r)
    out.sort(key=lambda r: (-r["score"], r["label"]))
    return out[:limit]


# ───────────────────────── cache ─────────────────────────
def load_cache(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        if d.get("version") == CACHE_VERSION and isinstance(d.get("voices"), dict):
            return d["voices"]
    except Exception:
        pass
    return {}


def save_cache(path, voices):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"version": CACHE_VERSION, "voices": voices}, fh)
        os.replace(tmp, path)
    except Exception as e:
        print(f"[AVS] voice finder: could not save cache: {e}")


def _valid(m):
    return (isinstance(m, dict)
            and all(isinstance(m.get(k), (int, float)) and math.isfinite(m[k])
                    for k in ("f0", "bright", "lively")))


# ───────────────────────── window ─────────────────────────
ENGINE_NAMES = {"vctk": "VCTK", "kokoro": "Kokoro", "xtts": "XTTS-v2"}


class VoiceFinder:
    """The 'Find a voice by traits' window.

    app        the AIApp (uses root, _btn, _label, _tts_synth, _vf_catalog,
               _vf_apply, text_entry)
    theme      dict of the app's colours (BG, CARD, SURFACE, FG, FG_DIM, ...)
    cache_path JSON file for the measurements
    """

    def __init__(self, app, theme, cache_path):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk = tk, ttk
        self.app, self.T, self.cache_path = app, theme, cache_path
        self.cache = load_cache(cache_path)
        self.catalog = []
        self._stop = threading.Event()
        self._worker = None
        self._lock = threading.Lock()          # one synthesis at a time
        self._results = []
        self.win = tk.Toplevel(app.root)
        self.win.title("Find a voice by traits")
        self.win.configure(bg=theme["BG"])
        self.win.geometry("760x680")
        self.win.minsize(640, 560)
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self._build()
        self._reload_catalog()

    # ---- layout ----
    def _build(self):
        tk, ttk, T = self.tk, self.ttk, self.T
        app = self.app
        w = self.win
        pad = dict(padx=12)

        tk.Label(w, text="Find a voice by traits", bg=T["BG"], fg=T["PURPLE"],
                 font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=12, pady=(10, 0))
        tk.Label(w, text="Each voice speaks a short sentence once and is measured; "
                 "the sliders then rank the voices.\nSliders compare a voice with the "
                 "others you have installed (50 = typical).",
                 bg=T["BG"], fg=T["FG_DIM"], font=("Segoe UI", 8),
                 justify="left").pack(anchor="w", **pad, pady=(0, 6))

        # -- engines + analysis
        top = tk.Frame(w, bg=T["CARD"], bd=1, relief="groove")
        top.pack(fill="x", padx=12, pady=4)
        row = tk.Frame(top, bg=T["CARD"]); row.pack(fill="x", padx=8, pady=(6, 2))
        tk.Label(row, text="Engines:", bg=T["CARD"], fg=T["FG"],
                 font=("Segoe UI", 9)).pack(side="left")
        self.eng_vars = {}
        self.eng_checks = {}
        for key in ("vctk", "kokoro", "xtts"):
            v = tk.BooleanVar(value=True)
            self.eng_vars[key] = v
            cb = tk.Checkbutton(row, text=ENGINE_NAMES[key], variable=v,
                                command=self._on_filter, bg=T["CARD"], fg=T["FG"],
                                selectcolor=T["SURFACE"], activebackground=T["CARD"],
                                activeforeground=T["FG"], font=("Segoe UI", 9))
            cb.pack(side="left", padx=6)
            self.eng_checks[key] = cb
        self.btn_analyze = app._btn(row, "Analyze voices", self._start_analysis,
                                    color=T["SURFACE"], fg=T["GREEN"], pady=3)
        self.btn_analyze.pack(side="right")
        self.btn_stop = app._btn(row, "Stop", self._stop_analysis,
                                 color=T["SURFACE"], fg=T["RED"], pady=3)
        self.status = tk.Label(top, text="", bg=T["CARD"], fg=T["FG_DIM"],
                               font=("Segoe UI", 8), anchor="w", justify="left")
        self.status.pack(fill="x", padx=8, pady=(0, 2))
        self.bar = ttk.Progressbar(top, mode="determinate", maximum=100)
        self.bar.pack(fill="x", padx=8, pady=(0, 6))

        # -- filters
        fr = tk.Frame(w, bg=T["BG"]); fr.pack(fill="x", padx=12, pady=(6, 0))
        tk.Label(fr, text="Gender:", bg=T["BG"], fg=T["FG"],
                 font=("Segoe UI", 9)).pack(side="left")
        self.gender = tk.StringVar(value="Any")
        for t in ("Any", "Male", "Female"):
            tk.Radiobutton(fr, text=t, value=t, variable=self.gender,
                           command=self._on_filter, bg=T["BG"], fg=T["FG"],
                           selectcolor=T["SURFACE"], activebackground=T["BG"],
                           activeforeground=T["FG"],
                           font=("Segoe UI", 9)).pack(side="left", padx=4)
        tk.Label(fr, text="   Language:", bg=T["BG"], fg=T["FG"],
                 font=("Segoe UI", 9)).pack(side="left")
        self.lang_var = tk.StringVar(value="Any")
        self.lang_box = ttk.Combobox(fr, textvariable=self.lang_var, state="readonly",
                                     width=14, values=["Any"])
        self.lang_box.pack(side="left", padx=4)
        self.lang_box.bind("<<ComboboxSelected>>", lambda e: self._on_filter())

        # -- sliders
        sf = tk.Frame(w, bg=T["BG"]); sf.pack(fill="x", padx=12, pady=(8, 2))
        self.t_use, self.t_val = {}, {}
        for i, (key, title, lo, hi) in enumerate(TRAITS):
            use = tk.BooleanVar(value=(key == "pitch"))
            val = tk.DoubleVar(value=50.0)
            self.t_use[key], self.t_val[key] = use, val
            tk.Checkbutton(sf, text=title, variable=use, command=self._on_filter,
                           bg=T["BG"], fg=T["FG"], selectcolor=T["SURFACE"],
                           activebackground=T["BG"], activeforeground=T["FG"],
                           font=("Segoe UI", 9, "bold"), width=12,
                           anchor="w").grid(row=i, column=0, sticky="w", pady=3)
            tk.Label(sf, text=lo, bg=T["BG"], fg=T["FG_DIM"], width=6, anchor="e",
                     font=("Segoe UI", 8)).grid(row=i, column=1)
            sc = ttk.Scale(sf, from_=0, to=100, orient="horizontal", variable=val,
                           length=360, command=lambda _v, k=key: self._on_slide(k))
            sc.grid(row=i, column=2, padx=4)
            tk.Label(sf, text=hi, bg=T["BG"], fg=T["FG_DIM"], width=6, anchor="w",
                     font=("Segoe UI", 8)).grid(row=i, column=3)
        tk.Label(sf, text="Tick a trait to use it; unticked traits are ignored.",
                 bg=T["BG"], fg=T["FG_DIM"], font=("Segoe UI", 8)
                 ).grid(row=len(TRAITS), column=0, columnspan=4, sticky="w")

        # -- results
        style = ttk.Style(w)
        style.configure("VF.Treeview", background=T["SURFACE"],
                        fieldbackground=T["SURFACE"], foreground=T["FG"],
                        rowheight=22, borderwidth=0, font=("Segoe UI", 9))
        style.configure("VF.Treeview.Heading", background=T["CARD"],
                        foreground=T["FG"], font=("Segoe UI", 9, "bold"))
        style.map("VF.Treeview", background=[("selected", "#3d59a1")],
                  foreground=[("selected", "#ffffff")])
        rf = tk.Frame(w, bg=T["BG"]); rf.pack(fill="both", expand=True, padx=12, pady=8)
        cols = ("match", "engine", "voice", "gender", "pitch")
        self.tree = ttk.Treeview(rf, columns=cols, show="headings",
                                 style="VF.Treeview", selectmode="browse")
        for c, t, wd, an in (("match", "Match", 60, "center"),
                             ("engine", "Engine", 80, "w"),
                             ("voice", "Voice", 300, "w"),
                             ("gender", "Gender", 70, "center"),
                             ("pitch", "Pitch", 80, "center")):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=wd, anchor=an, stretch=(c == "voice"))
        sb = ttk.Scrollbar(rf, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda e: self._use())
        self.tree.bind("<Return>", lambda e: self._use())

        bf = tk.Frame(w, bg=T["BG"]); bf.pack(fill="x", padx=12, pady=(0, 10))
        self.btn_prev = app._btn(bf, "Preview", self._preview, color=T["SURFACE"],
                                 fg=T["BLUE"])
        self.btn_prev.pack(side="left")
        app._btn(bf, "Use this voice", self._use, color=T["BLUE"], fg="#1a1b2e",
                 bold=True).pack(side="left", padx=8)
        self.note = tk.Label(bf, text="", bg=T["BG"], fg=T["FG_DIM"],
                             font=("Segoe UI", 8))
        self.note.pack(side="left", padx=8)
        app._btn(bf, "Close", self.close, color=T["SURFACE"]).pack(side="right")

    # ---- data ----
    def _reload_catalog(self):
        try:
            self.catalog = self.app._vf_catalog()
        except Exception as e:
            print(f"[AVS] voice finder: could not list voices: {e}")
            self.catalog = []
        have = {e["engine"] for e in self.catalog}
        for key, cb in self.eng_checks.items():
            if key not in have:
                self.eng_vars[key].set(False)
                cb.config(state="disabled", text=f"{ENGINE_NAMES[key]} (not installed)")
        langs = sorted({LANG_NAMES.get(e["lang"], "") for e in self.catalog
                        if e["lang"] != "*"} - {""})
        self.lang_box.config(values=["Any"] + langs)
        self._on_filter()

    def _selected_engines(self):
        return {k for k, v in self.eng_vars.items() if v.get()}

    def _analysed(self):
        engines = self._selected_engines()
        out = []
        for e in self.catalog:
            if e["engine"] not in engines:
                continue
            m = self.cache.get(e["key"])
            if _valid(m):
                r = dict(e); r.update(f0=m["f0"], bright=m["bright"], lively=m["lively"])
                out.append(r)
        return out

    def _on_slide(self, _key):
        self._on_filter()

    def _on_filter(self):
        if not self.win.winfo_exists():
            return
        engines = self._selected_engines()
        total = sum(1 for e in self.catalog if e["engine"] in engines)
        done = len(self._analysed())
        if not self._running():
            self.status.config(
                text=(f"{done} of {total} voices analysed." if total else
                      "No engine selected / installed.") +
                     ("  Press 'Analyze voices' to measure the rest (done once, then saved)."
                      if done < total else ""))
            self.bar.config(value=100 * done / total if total else 0)
        wanted = {k: self.t_val[k].get() for k in self.t_use if self.t_use[k].get()}
        g = {"Male": "M", "Female": "F"}.get(self.gender.get())
        lg = next((c for c, n in LANG_NAMES.items() if n == self.lang_var.get()), None)
        self._results = rank_voices(self._analysed(), wanted, g, lg)
        self.tree.delete(*self.tree.get_children())
        for i, r in enumerate(self._results):
            self.tree.insert("", "end", iid=str(i), values=(
                f"{r['score']:.0f}%", ENGINE_NAMES.get(r["engine"], r["engine"]),
                r["label"], ("M" if r["g"] == "M" else "F") + ("?" if r["guessed"] else ""),
                f"{r['f0']:.0f} Hz"))
        if self._results:
            self.tree.selection_set("0")
        if done == 0:
            self.note.config(text="Nothing to rank yet - analyze voices first.")
        else:
            self.note.config(text="'?' = gender guessed from pitch")

    def _running(self):
        return self._worker is not None and self._worker.is_alive()

    # ---- analysis ----
    def _start_analysis(self):
        if self._running():
            return
        engines = self._selected_engines()
        todo = [e for e in self.catalog
                if e["engine"] in engines and not _valid(self.cache.get(e["key"]))]
        if not todo:
            self.status.config(text="All selected voices are already analysed.")
            return
        self._stop.clear()
        self.btn_analyze.pack_forget()
        self.btn_stop.pack(side="right")
        self.bar.config(value=0, maximum=len(todo))
        self._worker = threading.Thread(target=self._analyse_run, args=(todo,),
                                        daemon=True)
        self._worker.start()

    def _stop_analysis(self):
        self._stop.set()
        self.status.config(text="Stopping after the current voice...")

    def _post(self, fn, *a):
        try:
            self.app.root.after(0, fn, *a)
        except Exception:
            pass

    def _analyse_run(self, todo):
        t0 = time.time()
        n_ok = n_bad = 0
        try:
            for i, e in enumerate(todo, 1):
                if self._stop.is_set():
                    break
                self._post(self._progress, i - 1, len(todo), e["label"], t0)
                tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False); tmp.close()
                try:
                    text = SAMPLES.get(e["lang"] if e["lang"] != "*" else "en", SAMPLES["en"])
                    with self._lock:
                        self.app._tts_synth(
                            (e["engine"], e["voice"],
                             "en" if e["engine"] == "xtts" else None), text, tmp.name)
                    m = measure(tmp.name)
                    if m:
                        self.cache[e["key"]] = m
                        n_ok += 1
                    else:
                        n_bad += 1
                        print(f"[AVS] voice finder: no clear speech in {e['key']}")
                except Exception as ex:
                    n_bad += 1
                    print(f"[AVS] voice finder: {e['key']} failed: {ex}")
                finally:
                    try: os.remove(tmp.name)
                    except OSError: pass
                if i % 8 == 0:
                    save_cache(self.cache_path, self.cache)
                    self._post(self._on_filter_safe)
        finally:
            save_cache(self.cache_path, self.cache)
            self._post(self._analysis_done, n_ok, n_bad, time.time() - t0)

    def _progress(self, n, total, label, t0):
        if not self.win.winfo_exists():
            return
        el = time.time() - t0
        eta = ""
        if n >= 3:
            eta = f", about {int(el / n * (total - n) / 60 + 0.5)} min left"
        self.status.config(text=f"Analysing {n + 1} of {total}: {label}{eta}")
        self.bar.config(maximum=total, value=n)

    def _on_filter_safe(self):
        if self.win.winfo_exists():
            self._on_filter()

    def _analysis_done(self, ok, bad, secs):
        if not self.win.winfo_exists():
            return
        self.btn_stop.pack_forget()
        self.btn_analyze.pack(side="right")
        self._on_filter()
        self.status.config(text=self.status.cget("text") +
                           f"  (last run: {ok} measured, {bad} failed, {secs:.0f}s)")

    # ---- actions ----
    def _current(self):
        sel = self.tree.selection()
        if not sel:
            return None
        try:
            return self._results[int(sel[0])]
        except (ValueError, IndexError):
            return None

    def _use(self):
        r = self._current()
        if not r:
            return
        self.app._vf_apply(r["engine"], r["voice"])
        self.note.config(text=f"Selected {r['label']} in the main window.")

    def _preview(self):
        r = self._current()
        if not r:
            return
        if self._running():
            self.note.config(text="Wait for the analysis to finish (or press Stop).")
            return
        text = ""
        try:
            text = self.app.text_entry.get("1.0", "end").strip()
        except Exception:
            pass
        text = (text[:200] if text else
                SAMPLES.get(r["lang"] if r["lang"] != "*" else "en", SAMPLES["en"]))
        self.btn_prev.config(state="disabled")
        self.note.config(text=f"Generating {r['label']}...")

        def work():
            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False); tmp.close()
            err = None
            try:
                with self._lock:
                    self.app._tts_synth(
                        (r["engine"], r["voice"], "en" if r["engine"] == "xtts" else None),
                        text, tmp.name)
                import pygame
                pygame.mixer.music.load(tmp.name)
                pygame.mixer.music.play()
            except Exception as ex:
                err = ex
                print(f"[AVS] voice finder preview failed: {ex}")
            self._post(self._preview_done, r["label"], err)

        threading.Thread(target=work, daemon=True).start()

    def _preview_done(self, label, err):
        if not self.win.winfo_exists():
            return
        self.btn_prev.config(state="normal")
        self.note.config(text=(f"Preview failed: {err}" if err else f"Playing {label}"))

    def close(self):
        self._stop.set()
        try:
            save_cache(self.cache_path, self.cache)
            self.win.destroy()
        except Exception:
            pass
        if getattr(self.app, "_vf_win", None) is self:
            self.app._vf_win = None
