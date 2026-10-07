"""Vosk fix #2:
  1. Model finder: if the extracted folder isn't a valid Vosk model, look
     deeper for the real model root (am/ + conf/); if none, the error shows the
     zip's actual layout so we can see what's wrong.
  2. 'Uninstall selected' button in the Vosk language picker.
Refuses to run twice. Writes nothing unless every anchor matches exactly once.
"""
import sys, shutil

SRC = "main.py"
src = open(SRC, encoding="utf-8").read()
if "_vosk_find_model_root" in src:
    sys.exit("Already applied")

HELPERS = '''def _vosk_find_model_root(base, max_depth=4):
    """Return the first folder under base that looks like a Vosk model."""
    base_depth = base.rstrip(os.sep).count(os.sep)
    for root, dirs, _files in os.walk(base):
        if root.count(os.sep) - base_depth > max_depth:
            dirs[:] = []
            continue
        if _vosk_model_ok(root):
            return root
    return None


def _vosk_layout(base, limit=14):
    """Short text listing of an extracted zip (2 levels) for error messages."""
    out = []
    base_depth = base.rstrip(os.sep).count(os.sep)
    for root, dirs, files in os.walk(base):
        depth = root.count(os.sep) - base_depth
        if depth >= 2:
            dirs[:] = []
        for d in sorted(dirs):
            out.append(os.path.relpath(os.path.join(root, d), base) + "/")
        if depth < 2:
            for f in sorted(files):
                if not f.endswith(".zip"):
                    out.append(os.path.relpath(os.path.join(root, f), base))
    if len(out) > limit:
        out = out[:limit] + ["..."]
    return ", ".join(out) or "(empty)"


def _vosk_download_one(self, code, title):'''

UNINSTALL = '''    def _uninstall():
        sel = [codes[i] for i in lb.curselection()
               if os.path.isdir(os.path.join(VOSK_MODEL_DIR, codes[i]))]
        if not sel:
            messagebox.showinfo("Uninstall",
                                "None of the selected languages are installed.",
                                parent=top)
            return
        names = ", ".join(_VOSK_LANG_NAMES.get(c, c) for c in sel)
        if not messagebox.askyesno(
                "Uninstall Vosk models",
                f"Delete the Vosk model for: {names}?\\n\\n"
                f"You can download it again later.", parent=top):
            return
        failed = []
        for c in sel:
            try:
                shutil.rmtree(os.path.join(VOSK_MODEL_DIR, c))
                _vosk_models.pop(c, None)
            except Exception as e:
                failed.append(f"{_VOSK_LANG_NAMES.get(c, c)}: {e}")
        top.destroy()
        self._vosk_refresh_status()
        if failed:
            messagebox.showerror("Uninstall failed", "\\n".join(failed))

    tk.Button(br, text="Download selected", command=_go, bg=GREEN, fg=BG,
              relief="flat", bd=0, padx=10, pady=3,
              font=("Segoe UI", 8, "bold")).pack(side="left", padx=4)
    tk.Button(br, text="Uninstall selected", command=_uninstall, bg=RED, fg=BG,
              relief="flat", bd=0, padx=10, pady=3,
              font=("Segoe UI", 8, "bold")).pack(side="left", padx=4)'''

EDITS = [
    ("def _vosk_download_one(self, code, title):", HELPERS),
    ('        if not _vosk_model_ok(cand):\n'
     '            return False, "downloaded folder is not a valid Vosk model"\n',
     '        if not _vosk_model_ok(cand):\n'
     '            found = _vosk_find_model_root(work)\n'
     '            if not found:\n'
     '                return False, ("downloaded folder is not a valid Vosk model."\n'
     '                               " Zip contents: " + _vosk_layout(work))\n'
     '            cand = found\n'),
    ('    tk.Button(br, text="Download selected", command=_go, bg=GREEN, fg=BG,\n'
     '              relief="flat", bd=0, padx=10, pady=3,\n'
     '              font=("Segoe UI", 8, "bold")).pack(side="left", padx=4)',
     UNINSTALL),
]

for old, _new in EDITS:
    n = src.count(old)
    assert n == 1, f"anchor matched {n} times (need exactly 1):\n{old[:80]}"
assert "RED" in src, "RED colour constant not found"

shutil.copy2(SRC, "main.py.pre_vosk2")
for old, new in EDITS:
    src = src.replace(old, new)
open(SRC, "w", encoding="utf-8").write(src)
print("OK: main.py patched (3 edits). Backup: main.py.pre_vosk2")
