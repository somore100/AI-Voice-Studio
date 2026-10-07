"""Vosk fix #3:
  1. Accept the older flat model layout (final.mdl + mfcc.conf at the top
     level) used by e.g. the Portuguese and Turkish small models, as well as
     the newer am/ + conf/ layout.
  2. The 'Vosk models' row keeps a visible button at all times, relabelled
     'Manage' (opens the picker, which has Download and Uninstall).
Refuses to run twice; writes nothing unless every anchor matches once.
"""
import sys, shutil

SRC = "main.py"
src = open(SRC, encoding="utf-8").read()
if "flat layout" in src:
    sys.exit("Already applied")

EDITS = [
    ('    return (os.path.isdir(os.path.join(path, "am"))\n'
     '            and os.path.isdir(os.path.join(path, "conf")))\n',
     '    if (os.path.isdir(os.path.join(path, "am"))\n'
     '            and os.path.isdir(os.path.join(path, "conf"))):\n'
     '        return True\n'
     '    # older flat layout (e.g. small pt / tr models)\n'
     '    return (os.path.isfile(os.path.join(path, "final.mdl"))\n'
     '            and os.path.isfile(os.path.join(path, "mfcc.conf")))\n'),
    ('    status, btn = self._model_rows[key]\n'
     '    if ok is True:\n'
     '        status.config(text=text or "OK", fg=GREEN)\n'
     '        btn.pack_forget()\n',
     '    status, btn = self._model_rows[key]\n'
     '    if key == "vosk_models":\n'
     '        btn.config(text="Manage")\n'
     '    if ok is True:\n'
     '        status.config(text=text or "OK", fg=GREEN)\n'
     '        if key == "vosk_models":\n'
     '            btn.pack(side="right", padx=4)\n'
     '        else:\n'
     '            btn.pack_forget()\n'),
    ('"Select languages to download (small models):"',
     '"Select languages, then Download or Uninstall:"'),
]
for old, _ in EDITS:
    n = src.count(old)
    assert n == 1, f"anchor matched {n} times (need exactly 1):\n{old[:80]}"

shutil.copy2(SRC, "main.py.pre_vosk3")
for old, new in EDITS:
    src = src.replace(old, new)
open(SRC, "w", encoding="utf-8").write(src)
print("OK: main.py patched (3 edits). Backup: main.py.pre_vosk3")
