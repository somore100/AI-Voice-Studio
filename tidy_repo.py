#!/usr/bin/env python3
"""One-shot tidy for AI Voice Studio. Run from the repo folder. Safe to re-run.
1. restores logo.ico / logo.png if deleted (builds need them)
2. makes editing a curve tick "Use curves" (curve_editor.py)
3. MOVES (never deletes) patch scripts, main.py backups, logs, diag scripts
   into ./_archive/ and adds _archive/ + log/backup patterns to .gitignore
"""
import glob, os, shutil, subprocess, sys

# 1 ---- logos
for f in ("logo.ico", "logo.png"):
    if not os.path.exists(f):
        r = subprocess.run(["git", "checkout", "--", f], capture_output=True)
        print(("restored " if r.returncode == 0 else "COULD NOT restore ") + f)

# 2 ---- curve editor auto-on
P = "curve_editor.py"
src = open(P, encoding="utf-8").read()
if "_ready = [False]" in src:
    print("curve_editor.py: auto-on already applied")
else:
    a1 = "    def changed():\n        k = audio_fx.length_factor(state)\n"
    a2 = "    changed()\n    return win\n"
    assert src.count(a1) == 1 and src.count(a2) == 1, "curve_editor.py anchors not found"
    src = src.replace(a1, "    _ready = [False]\n\n    def changed():\n"
                          "        if _ready[0] and not use_var.get():\n"
                          "            use_var.set(True)  # editing a curve = you want it applied\n"
                          "        k = audio_fx.length_factor(state)\n")
    src = src.replace(a2, "    changed()\n    _ready[0] = True\n    return win\n")
    open(P, "w", encoding="utf-8").write(src)
    print("curve_editor.py: auto-on applied")

# 3 ---- archive clutter
pats = ["main.py.pre_*", "main.py.bak", "patch_*.py", "tidy_*.py", "*.log",
        "vmic_diag*.sh", "dc_test.py.pre_*"]
files = sorted({f for p in pats for f in glob.glob(p) if os.path.isfile(f)})
if os.path.isfile("main") and os.path.getsize("main") == 0:
    files.append("main")        # empty stray file
if files:
    os.makedirs("_archive", exist_ok=True)
    for f in files:
        if f == os.path.basename(__file__):
            continue
        dst = os.path.join("_archive", f)
        if os.path.exists(dst):
            os.remove(dst)
        shutil.move(f, dst)
    print(f"moved {len(files)} files into _archive/")
else:
    print("nothing to archive")

want = ["_archive/", "*.log", "main.py.pre_*", "main.py.bak"]
have = open(".gitignore").read().splitlines() if os.path.exists(".gitignore") else []
add = [w for w in want if w not in have]
if add:
    with open(".gitignore", "a") as g:
        if have and have[-1] != "":
            g.write("\n")
        g.write("\n".join(add) + "\n")
    print("added to .gitignore:", ", ".join(add))
print("done")
