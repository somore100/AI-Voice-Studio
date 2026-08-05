#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
#  AI Voice Studio — Linux AppImage build script
#
#  Prereqs (one-time):
#    - Working venv per README (python3.10 -m venv venv --system-site-packages)
#    - pip install pyinstaller  (inside that venv)
#    - fuse2 installed: sudo apt install libfuse2
#
#  Usage:
#    source venv/bin/activate
#    ./build_appimage.sh
# ─────────────────────────────────────────────────────────────
set -e

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$BASE_DIR"

APP_NAME="AI_Voice_Studio"
DIST_DIR="$BASE_DIR/dist/$APP_NAME"
APPDIR="$BASE_DIR/AppDir"
TOOLS_DIR="$BASE_DIR/.appimage_tools"

echo "── Step 1: PyInstaller build ─────────────────────────────"
python -m PyInstaller ai_voice_studio_linux.spec --clean --noconfirm

if [ ! -f "$DIST_DIR/$APP_NAME" ]; then
    echo "ERROR: PyInstaller output not found at $DIST_DIR/$APP_NAME"
    exit 1
fi

echo "── Step 2: Download AppImage tools (cached after first run) ─"
mkdir -p "$TOOLS_DIR"

LINUXDEPLOY="$TOOLS_DIR/linuxdeploy-x86_64.AppImage"
if [ ! -f "$LINUXDEPLOY" ]; then
    curl -L -o "$LINUXDEPLOY" \
      "https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/linuxdeploy-x86_64.AppImage"
    chmod +x "$LINUXDEPLOY"
fi

APPIMAGETOOL="$TOOLS_DIR/appimagetool-x86_64.AppImage"
if [ ! -f "$APPIMAGETOOL" ]; then
    curl -L -o "$APPIMAGETOOL" \
      "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
    chmod +x "$APPIMAGETOOL"
fi

echo "── Step 3: Assemble AppDir ────────────────────────────────"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
mkdir -p "$APPDIR/usr/share/applications"
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"

# Copy the whole PyInstaller onedir output (exe + all bundled libs/data)
cp -r "$DIST_DIR/." "$APPDIR/usr/bin/"

# Desktop entry (linuxdeploy also wants a copy at the AppDir root)
cp "$BASE_DIR/ai-voice-studio.desktop" "$APPDIR/usr/share/applications/"
cp "$BASE_DIR/ai-voice-studio.desktop" "$APPDIR/"

# Resize icon to a valid square resolution (linuxdeploy rejects arbitrary sizes like 1920px)
if ! command -v convert &>/dev/null; then
    echo "ImageMagick 'convert' not found — installing..."
    sudo apt-get install -y imagemagick
fi
convert "$BASE_DIR/logo.png" -resize 256x256 -gravity center -background none -extent 256x256 "$BASE_DIR/icon_256.png"
cp "$BASE_DIR/icon_256.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/ai-voice-studio.png"
cp "$BASE_DIR/icon_256.png" "$APPDIR/ai-voice-studio.png"

echo "── Step 4: Run linuxdeploy to bundle shared libs + build AppImage ─"
export NO_STRIP=1   # keep symbols; some torch/numpy .so files break if stripped
export ARCH=x86_64  # appimagetool can't reliably auto-detect arch with mixed ML .so files bundled
"$LINUXDEPLOY" \
    --appdir "$APPDIR" \
    --executable "$APPDIR/usr/bin/$APP_NAME" \
    --desktop-file "$BASE_DIR/ai-voice-studio.desktop" \
    --icon-file "$BASE_DIR/icon_256.png" \
    --output appimage

echo "── Done ────────────────────────────────────────────────────"
ls -la "$BASE_DIR"/*.AppImage
