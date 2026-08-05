"""
Blockline Build Script (cross-platform)
=========================================
Builds a distributable binary for whichever OS it's run on:

  - Windows -> Blockline.exe                (PyInstaller --onefile --windowed)
  - Linux   -> dist/Blockline (ELF binary)   (PyInstaller --onefile)
              + Blockline-x86_64.AppImage    (wraps the binary)
  - macOS   -> dist/Blockline (onefile binary; .app bundling is a separate step)

Usage:
    python build.py                  # auto: best default for this OS
    python build.py --target exe     # force PyInstaller onefile build only
    python build.py --target appimage  # Linux only: binary + AppImage
    python build.py --target binary-only  # skip AppImage step on Linux

Run this from inside your activated venv (see setup_venv.sh / setup_venv.bat).
"""

import argparse
import os
import platform
import shutil
import stat
import subprocess
import sys
import urllib.request
from pathlib import Path

# Windows' console defaults to a legacy codepage (cp1252 etc.) that
# can't print characters like ✓/⚠/✗ used throughout this script's
# progress messages - this crashed the GitHub Actions Windows build
# with UnicodeEncodeError the moment it tried to print a checkmark.
# Forcing stdout/stderr to UTF-8 fixes it regardless of platform.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

APP_NAME = "Blockline"
MAIN_SCRIPT = "main.py"
LOGO_CANDIDATES = ["logo.png", "logo.jpg", "logo.jpeg"]

# Folders that get bundled into the built binary alongside main.py.
# Add more here as the project grows (e.g. "themes", "templates").
EXTRA_DATA_DIRS = ["languages", "blocks"]

ROOT = Path(__file__).parent.resolve()
DIST_DIR = ROOT / "dist"
BUILD_TOOLS_DIR = ROOT / "build_tools"
APPIMAGE_TOOL = BUILD_TOOLS_DIR / "appimagetool.AppImage"
APPIMAGETOOL_URL = (
    "https://github.com/AppImage/AppImageKit/releases/download/"
    "continuous/appimagetool-x86_64.AppImage"
)


def find_logo():
    """Find whichever logo file exists next to build.py. PIL opens any
    of these regardless of extension, so a JPG works everywhere a PNG
    would for icon conversion - the AppImage icon specifically needs a
    real .png on disk though, so that one spot converts if needed."""
    for name in LOGO_CANDIDATES:
        p = ROOT / name
        if p.exists():
            return p
    return None


def banner(text):
    print("\n" + "=" * 60)
    print(f" {text}")
    print("=" * 60)


def ensure_pyinstaller():
    try:
        import PyInstaller  # noqa: F401
        print("✓ PyInstaller found")
    except ImportError:
        print("✗ PyInstaller not found, installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        print("✓ PyInstaller installed")


def existing_data_dirs():
    """Only bundle data dirs that actually exist, and warn about the rest."""
    found = []
    for name in EXTRA_DATA_DIRS:
        p = ROOT / name
        if p.is_dir():
            found.append(name)
        else:
            print(f"⚠ Data folder '{name}' not found next to build.py, skipping")
    return found


def make_windows_icon():
    """Convert the logo -> logo.ico for the Windows exe. Returns path or None."""
    logo_path = find_logo()
    icon_path = ROOT / "logo.ico"
    if not logo_path:
        print(f"⚠ No logo file found ({', '.join(LOGO_CANDIDATES)}) - building without an icon")
        return None
    if icon_path.exists():
        return icon_path
    try:
        from PIL import Image
        img = Image.open(logo_path)
        img.save(icon_path, format="ICO", sizes=[(256, 256)])
        print(f"✓ Created {icon_path.name}")
        return icon_path
    except Exception as e:
        print(f"⚠ Could not create .ico: {e}")
        return None


def run_pyinstaller(windowed: bool, icon_path: Path | None):
    """Run PyInstaller --onefile and return the path to the built binary."""
    ensure_pyinstaller()

    sep = ";" if platform.system() == "Windows" else ":"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        f"--name={APP_NAME}",
        "--clean",
        "--noconfirm",
    ]
    if windowed:
        cmd.append("--windowed")

    if icon_path and icon_path.exists():
        cmd.append(f"--icon={icon_path}")

    # Bundle top-level helper module and data folders, using the
    # correct separator for this OS (this is what broke on Linux before).
    ui_py = ROOT / "ui.py"
    if ui_py.exists():
        cmd.append(f"--add-data={ui_py}{sep}.")

    for d in existing_data_dirs():
        cmd.append(f"--add-data={ROOT / d}{sep}{d}")

    logo_path = find_logo()
    if logo_path:
        cmd.append(f"--add-data={logo_path}{sep}.")

    cmd.extend([
        "--hidden-import=tkinter",
        "--hidden-import=tkinter.ttk",
        "--hidden-import=PIL",
        "--hidden-import=PIL.Image",
        "--hidden-import=PIL.ImageTk",
    ])

    cmd.append(str(ROOT / MAIN_SCRIPT))

    banner("Running PyInstaller")
    print("Command:", " ".join(cmd))
    subprocess.check_call(cmd, cwd=ROOT)

    binary_name = f"{APP_NAME}.exe" if platform.system() == "Windows" else APP_NAME
    binary_path = DIST_DIR / binary_name
    if not binary_path.exists():
        raise RuntimeError(f"Expected build output at {binary_path} but it's missing")

    size_mb = binary_path.stat().st_size / (1024 * 1024)
    print(f"✓ Built {binary_path}  ({size_mb:.1f} MB)")
    return binary_path


def has_libfuse2():
    """Check whether libfuse.so.2 is available (required by appimagetool
    itself, since it's also an AppImage). Newer Ubuntu/Mint/Pop!_OS bases
    (22.04+) don't ship it by default."""
    try:
        result = subprocess.run(
            ["ldconfig", "-p"], capture_output=True, text=True, check=False
        )
        return "libfuse.so.2" in result.stdout
    except FileNotFoundError:
        # ldconfig itself missing - assume unknown, let it try normally
        return True


def ensure_appimagetool():
    if APPIMAGE_TOOL.exists():
        return APPIMAGE_TOOL
    BUILD_TOOLS_DIR.mkdir(exist_ok=True)
    print(f"Downloading appimagetool from {APPIMAGETOOL_URL} ...")
    try:
        urllib.request.urlretrieve(APPIMAGETOOL_URL, APPIMAGE_TOOL)
    except Exception as e:
        raise RuntimeError(
            "Could not download appimagetool (no network access?). "
            "Download it manually from "
            "https://github.com/AppImage/AppImageKit/releases and place it at "
            f"{APPIMAGE_TOOL}"
        ) from e
    APPIMAGE_TOOL.chmod(APPIMAGE_TOOL.stat().st_mode | stat.S_IEXEC)
    print("✓ appimagetool ready")
    return APPIMAGE_TOOL


def build_appimage(binary_path: Path):
    """Wrap the already-built Linux binary into a .AppImage."""
    banner("Building AppImage")

    appdir = DIST_DIR / "AppDir"
    if appdir.exists():
        shutil.rmtree(appdir)
    (appdir / "usr" / "bin").mkdir(parents=True)

    # 1. Copy the PyInstaller binary in.
    target_bin = appdir / "usr" / "bin" / APP_NAME
    shutil.copy2(binary_path, target_bin)
    target_bin.chmod(target_bin.stat().st_mode | stat.S_IEXEC)

    # 2. Icon - AppImage requires one at the AppDir root, and
    # conventionally expects a real .png regardless of what format the
    # source logo is in, so convert if it's a JPG.
    logo_path = find_logo()
    icon_dest = appdir / f"{APP_NAME.lower()}.png"
    if logo_path and logo_path.suffix.lower() == ".png":
        shutil.copy2(logo_path, icon_dest)
    elif logo_path:
        try:
            from PIL import Image
            Image.open(logo_path).convert("RGBA").save(icon_dest, format="PNG")
            print(f"✓ Converted {logo_path.name} -> {icon_dest.name} for the AppImage icon")
        except Exception as e:
            print(f"⚠ Could not convert {logo_path.name} to PNG: {e}")
            icon_dest = None
    else:
        print(f"⚠ No logo file found ({', '.join(LOGO_CANDIDATES)}) - AppImage will build without a custom icon")
        icon_dest = None

    # 3. .desktop file (required by appimagetool).
    desktop_content = f"""[Desktop Entry]
Type=Application
Name={APP_NAME}
Exec={APP_NAME}
Icon={APP_NAME.lower()}
Categories=Development;
Terminal=false
"""
    (appdir / f"{APP_NAME}.desktop").write_text(desktop_content)

    # 4. AppRun - the entrypoint appimagetool executes.
    apprun_content = f"""#!/bin/sh
HERE="$(dirname "$(readlink -f "${{0}}")")"
exec "$HERE/usr/bin/{APP_NAME}" "$@"
"""
    apprun_path = appdir / "AppRun"
    apprun_path.write_text(apprun_content)
    apprun_path.chmod(apprun_path.stat().st_mode | stat.S_IEXEC)

    # 5. Run appimagetool.
    tool = ensure_appimagetool()
    output_path = DIST_DIR / f"{APP_NAME}-x86_64.AppImage"
    cmd = [str(tool), str(appdir), str(output_path)]
    env = dict(os.environ)
    env["ARCH"] = "x86_64"

    # appimagetool is itself an AppImage, so it needs libfuse.so.2 to run.
    # Ubuntu/Mint/Pop!_OS 22.04+ don't ship it by default -> fall back to
    # extract-and-run instead of failing outright.
    if not has_libfuse2():
        print(
            "⚠ libfuse2 not found - appimagetool would normally fail to launch.\n"
            "  Falling back to APPIMAGE_EXTRACT_AND_RUN=1 for this build.\n"
            "  To avoid this fallback in future, install it with one of:\n"
            "    sudo apt install libfuse2      (Mint / older Pop!_OS)\n"
            "    sudo apt install libfuse2t64   (Ubuntu 24.04+ based systems)"
        )
        env["APPIMAGE_EXTRACT_AND_RUN"] = "1"

    try:
        subprocess.check_call(cmd, env=env)
    except subprocess.CalledProcessError as e:
        print(
            "⚠ appimagetool failed. If the error mentions FUSE, either:\n"
            "  - install libfuse2 or libfuse2t64 (see above), or\n"
            "  - re-run with: APPIMAGE_EXTRACT_AND_RUN=1 python build.py --target appimage"
        )
        raise e

    print(f"✓ Built {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Build Blockline for this platform.")
    parser.add_argument(
        "--target",
        choices=["auto", "exe", "appimage", "binary-only"],
        default="auto",
        help="auto: best default for this OS. exe: Windows onefile exe. "
             "appimage: Linux onefile binary + .AppImage. "
             "binary-only: just the raw PyInstaller onefile binary.",
    )
    args = parser.parse_args()

    system = platform.system()  # "Windows", "Linux", "Darwin"
    banner(f"Building {APP_NAME} - detected OS: {system}")

    if args.target == "auto":
        target = "exe" if system == "Windows" else (
            "appimage" if system == "Linux" else "binary-only"
        )
        print(f"--target auto -> using '{target}' for {system}")
    else:
        target = args.target

    if target == "appimage" and system != "Linux":
        print("✗ --target appimage is only supported on Linux")
        sys.exit(1)

    windowed = True  # GUI app, no console window
    icon_path = make_windows_icon() if system == "Windows" else None

    binary_path = run_pyinstaller(windowed=windowed, icon_path=icon_path)

    if target == "appimage":
        build_appimage(binary_path)

    banner("✓ Build complete")
    print(f"Output directory: {DIST_DIR}")
    for f in sorted(DIST_DIR.iterdir()):
        if f.is_file():
            print(f"  - {f.name}")


if __name__ == "__main__":
    main()
