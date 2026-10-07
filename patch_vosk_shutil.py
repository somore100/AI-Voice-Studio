import sys, shutil as _sh
src = open("main.py", encoding="utf-8").read()
anchor = "def _vosk_model_ok(path):"
assert src.count(anchor) == 1, f"anchor matches {src.count(anchor)} times"
if "import shutil  # vosk download" in src:
    sys.exit("Already applied")
_sh.copy2("main.py", "main.py.pre_shutil")
src = src.replace(anchor, "import shutil  # vosk download\n\n" + anchor)
open("main.py", "w", encoding="utf-8").write(src)
print("OK: import shutil added. Backup: main.py.pre_shutil")
