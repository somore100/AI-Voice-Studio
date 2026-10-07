#!/usr/bin/env python3
"""patch_vosk_models.py - per-language Vosk model check + download.

Edits main.py in place (backup: main.py.pre_vosk). Every edit asserts that its
anchor matches exactly once; an AssertionError on a re-run means "already
applied", not a bug. Run from the project folder:  python patch_vosk_models.py
"""
import os, shutil, sys, py_compile

PATH = "main.py"
BACKUP = "main.py.pre_vosk"

src = open(PATH, encoding="utf-8").read()
if "VOSK_MODELS = {" in src:
    sys.exit("Already applied (VOSK_MODELS found in main.py). Nothing to do.")

NEW_BLOCK = r'''# -- Vosk per-language models -------------------------------------------
# Small models from https://alphacephei.com/vosk/models (model-list.json).
# Key = the app's Vosk code (LANGUAGES[i][2]); value = (zip/folder name, approx MB).
# Slovenian ("sl") and Croatian ("hr") have no small model, so they are absent.
VOSK_BASE_URL = "https://alphacephei.com/vosk/models"
VOSK_MODELS = {
    "en": ("vosk-model-small-en-us-0.15", 39),
    "ru": ("vosk-model-small-ru-0.22", 44),
    "de": ("vosk-model-small-de-0.15", 44),
    "fr": ("vosk-model-small-fr-0.22", 40),
    "es": ("vosk-model-small-es-0.42", 38),
    "it": ("vosk-model-small-it-0.22", 47),
    "ja": ("vosk-model-small-ja-0.22", 47),
    "zh": ("vosk-model-small-cn-0.22", 42),
    "pt": ("vosk-model-small-pt-0.3", 31),
    "pl": ("vosk-model-small-pl-0.22", 51),
    "cs": ("vosk-model-small-cs-0.4-rhasspy", 44),
    "nl": ("vosk-model-small-nl-0.22", 39),
    "tr": ("vosk-model-small-tr-0.3", 35),
    "ko": ("vosk-model-small-ko-0.22", 83),
    "ar": ("vosk-model-small-ar-0.3", 100),
}
_VOSK_LANG_NAMES = {l[2]: l[0] for l in LANGUAGES}


def _vosk_model_ok(path):
    """A real Vosk model folder has am/ and conf/ inside it."""
    return (os.path.isdir(os.path.join(path, "am"))
            and os.path.isdir(os.path.join(path, "conf")))


def _vosk_refresh_status(self):
    """Count installed per-language models and update the Models row."""
    n = sum(1 for c in VOSK_MODELS
            if _vosk_model_ok(os.path.join(VOSK_MODEL_DIR, c)))
    total = len(VOSK_MODELS)
    self.root.after(0, lambda: self._set_model_status(
        "vosk_models", n == total, f"{n}/{total} langs"))


def _vosk_progress(self, title, done, total):
    mb = done / 1048576
    def _u():
        try:
            if total:
                pct = min(100, int(done * 100 / total))
                if str(self._dl_bar["mode"]) != "determinate":
                    self._dl_bar.stop()
                    self._dl_bar.config(mode="determinate", maximum=100)
                self._dl_bar["value"] = pct
                self._dl_label.config(
                    text=f"{title}... {mb:.0f}/{total / 1048576:.0f} MB ({pct}%)",
                    fg=YELLOW)
            else:
                self._dl_label.config(text=f"{title}... {mb:.0f} MB", fg=YELLOW)
        except Exception:
            pass
    self.root.after(0, _u)


def _vosk_download_one(self, code, title):
    """Download + verify + install one model. Returns (ok, error_text)."""
    import urllib.request, zipfile, tempfile, time
    name, _mb = VOSK_MODELS[code]
    url = f"{VOSK_BASE_URL}/{name}.zip"
    os.makedirs(VOSK_MODEL_DIR, exist_ok=True)
    work = tempfile.mkdtemp(prefix=f"dl_{code}_", dir=VOSK_MODEL_DIR)
    zpath = os.path.join(work, name + ".zip")
    try:
        last_err = "unknown error"
        for attempt in range(1, 4):
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": "AI-Voice-Studio"})
                done = 0
                total = 0
                with urllib.request.urlopen(req, timeout=30) as resp, \
                        open(zpath, "wb") as out:
                    total = int(resp.headers.get("Content-Length") or 0)
                    while True:
                        chunk = resp.read(256 * 1024)
                        if not chunk:
                            break
                        out.write(chunk)
                        done += len(chunk)
                        self._vosk_progress(title, done, total)
                if total and done != total:
                    raise IOError(f"incomplete download ({done}/{total} bytes)")
                with zipfile.ZipFile(zpath) as z:
                    bad = z.testzip()
                    if bad:
                        raise IOError(f"corrupt zip member {bad}")
                    z.extractall(work)
                last_err = ""
                break
            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"
                if attempt < 3:
                    time.sleep(3 * attempt)
        if last_err:
            return False, last_err

        cand = os.path.join(work, name)
        if not os.path.isdir(cand):
            dirs = [d for d in os.listdir(work)
                    if os.path.isdir(os.path.join(work, d))]
            if len(dirs) != 1:
                return False, "unexpected zip layout"
            cand = os.path.join(work, dirs[0])
        if not _vosk_model_ok(cand):
            return False, "downloaded folder is not a valid Vosk model"
        final = os.path.join(VOSK_MODEL_DIR, code)
        if os.path.isdir(final):
            shutil.rmtree(final)
        shutil.move(cand, final)
        _vosk_models.pop(code, None)
        return True, ""
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _vosk_download_many(self, codes):
    results = []
    try:
        for i, code in enumerate(codes, 1):
            title = f"Vosk {_VOSK_LANG_NAMES.get(code, code)} ({i}/{len(codes)})"
            ok, err = self._vosk_download_one(code, title)
            results.append((code, ok, err))
    finally:
        self._vosk_dl_busy = False

    def _done():
        try:
            self._dl_bar.stop()
            self._dl_bar.config(mode="indeterminate", value=0)
        except Exception:
            pass
        bad = [(c, e) for c, ok, e in results if not ok]
        good = [c for c, ok, _ in results if ok]
        if bad:
            msg = "\n".join(f"{_VOSK_LANG_NAMES.get(c, c)}: {e}" for c, e in bad)
            try:
                self._dl_label.config(text="Vosk download failed", fg=RED)
            except Exception:
                pass
            messagebox.showerror("Vosk download failed", msg)
        if good:
            names = ", ".join(_VOSK_LANG_NAMES.get(c, c) for c in good)
            try:
                self._dl_label.config(text=f"Vosk installed: {names}", fg=GREEN)
            except Exception:
                pass
            messagebox.showinfo("Vosk model installed",
                                f"Installed: {names}\n\nPress Start again to use it.")
        self._check_models()
    self.root.after(0, _done)


def _vosk_download_async(self, codes):
    """Main thread only."""
    if getattr(self, "_vosk_dl_busy", False):
        messagebox.showinfo("Vosk", "A Vosk download is already running.")
        return
    self._vosk_dl_busy = True
    threading.Thread(target=self._vosk_download_many,
                     args=(list(codes),), daemon=True).start()


def _vosk_missing_prompt(self, code, msg):
    """Replaces the dead-end 'Vosk Model Missing' dialog. Main thread."""
    name = _VOSK_LANG_NAMES.get(code, code)
    info = VOSK_MODELS.get(code)
    if info is None:
        messagebox.showinfo(
            "Vosk not available",
            f"Vosk has no ready-made small model for {name}.\n\n"
            f"Use Whisper for this language instead.")
        return
    if messagebox.askyesno(
            "Vosk model not installed",
            f"The Vosk model for {name} isn't installed.\n\n"
            f"Download it now (~{info[1]} MB)?"):
        self._vosk_download_async([code])


def _vosk_pick_dialog(self):
    """Install button on the 'Vosk models' row: pick languages to download."""
    top = tk.Toplevel(self.root)
    top.title("Vosk language models")
    top.configure(bg=BG)
    top.transient(self.root)
    tk.Label(top, text="Select languages to download (small models):",
             bg=BG, fg=FG, font=("Segoe UI", 9, "bold")).pack(
                 anchor="w", padx=12, pady=(12, 4))
    codes = list(VOSK_MODELS)
    lb = tk.Listbox(top, selectmode="extended", height=len(codes), width=44,
                    bg=CARD, fg=FG, selectbackground=BLUE,
                    selectforeground=BG, relief="flat", bd=0,
                    exportselection=False, font="TkFixedFont")
    for c in codes:
        inst = _vosk_model_ok(os.path.join(VOSK_MODEL_DIR, c))
        lb.insert("end", f"{_VOSK_LANG_NAMES.get(c, c):<12} ~{VOSK_MODELS[c][1]:>3} MB"
                         f"   {'[installed]' if inst else ''}")
    lb.pack(padx=12, pady=4)
    tk.Label(top, text="Slovenian and Croatian: no Vosk model exists - use Whisper.",
             bg=BG, fg=FG_DIM, font=("Segoe UI", 8)).pack(anchor="w", padx=12)

    def _select_missing():
        lb.selection_clear(0, "end")
        for i, c in enumerate(codes):
            if not _vosk_model_ok(os.path.join(VOSK_MODEL_DIR, c)):
                lb.selection_set(i)

    def _go():
        sel = [codes[i] for i in lb.curselection()]
        if not sel:
            return
        top.destroy()
        self._vosk_download_async(sel)

    br = tk.Frame(top, bg=BG)
    br.pack(pady=10)
    tk.Button(br, text="Select missing", command=_select_missing, bg=CARD,
              fg=FG, relief="flat", bd=0, padx=10, pady=3,
              font=("Segoe UI", 8, "bold")).pack(side="left", padx=4)
    tk.Button(br, text="Download selected", command=_go, bg=GREEN, fg=BG,
              relief="flat", bd=0, padx=10, pady=3,
              font=("Segoe UI", 8, "bold")).pack(side="left", padx=4)


AIApp._vosk_refresh_status  = _vosk_refresh_status
AIApp._vosk_progress        = _vosk_progress
AIApp._vosk_download_one    = _vosk_download_one
AIApp._vosk_download_many   = _vosk_download_many
AIApp._vosk_download_async  = _vosk_download_async
AIApp._vosk_missing_prompt  = _vosk_missing_prompt
AIApp._vosk_pick_dialog     = _vosk_pick_dialog


'''

EDITS = [
    # 1. get_vosk_model: require a real model layout, not just a folder
    ("        if not os.path.isdir(model_path):",
     "        if not _vosk_model_ok(model_path):"),

    # 2. Models & Setup: new row (before the Vosk package row)
    ('("vosk_pkg", "Vosk package",',
     '("vosk_models", "Vosk models", "~40MB ea", "Per-language STT models"),\n'
     '        ("vosk_pkg", "Vosk package",'),

    # 3. Install button of the new row opens the language picker
    ("btn.config(command=lambda k=key: self._download_one(k))",
     'if key == "vosk_models":\n'
     "            btn.config(command=self._vosk_pick_dialog)\n"
     "        else:\n"
     "            btn.config(command=lambda k=key: self._download_one(k))"),

    # 4. Check All also counts installed Vosk models
    ("\n\n\ndef _ensure_engine_tos(self, key):",
     "\n    # Vosk per-language models\n"
     "    try:\n"
     "        self._vosk_refresh_status()\n"
     "    except Exception:\n"
     "        pass\n"
     "\n\ndef _ensure_engine_tos(self, key):"),

    # 5. Start-STT path: offer a download instead of a dead-end dialog.
    #    (e=e binds the exception now; a bare lambda reads it after the
    #    except block has already deleted it.)
    ('self.root.after(0, lambda: messagebox.showerror("Vosk Model Missing", str(e)))',
     "self.root.after(0, lambda e=e, v=vlang: self._vosk_missing_prompt(v, str(e)))"),

    # 6. New code + method attachments, just before the existing patch list
    ("# Patch these methods onto AIApp\n",
     NEW_BLOCK + "# Patch these methods onto AIApp\n"),
]

out = src
for old, new in EDITS:
    n = out.count(old)
    assert n == 1, f"anchor matched {n} times (need exactly 1): {old[:70]!r}"
    out = out.replace(old, new)

shutil.copy2(PATH, BACKUP)
open(PATH, "w", encoding="utf-8").write(out)
try:
    py_compile.compile(PATH, doraise=True)
except py_compile.PyCompileError as e:
    shutil.copy2(BACKUP, PATH)
    sys.exit(f"Syntax check failed, main.py restored from {BACKUP}:\n{e}")
print(f"OK: main.py patched ({len(EDITS)} edits). Backup: {BACKUP}")
