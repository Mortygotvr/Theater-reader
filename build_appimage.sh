#!/bin/bash
set -e

echo "=== Building Theater Reader AppImage ==="

# 1. Ensure PyInstaller executable is built
if [ ! -f "dist/TheaterReader" ]; then
    echo "Building PyInstaller single-file binary..."
    pyinstaller --noconfirm TheaterReader.spec
fi

APP_DIR="AppDir"
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR"

# 2. Copy binary and HTML assets into AppDir
cp dist/TheaterReader "$APP_DIR/TheaterReader"
chmod +x "$APP_DIR/TheaterReader"

cp settings.html "$APP_DIR/settings.html"
if [ -f "chat_overlay.html" ]; then
    cp chat_overlay.html "$APP_DIR/chat_overlay.html"
fi

if [ -d "settings" ]; then
    cp -r settings "$APP_DIR/settings"
fi

# 3. Create Desktop Entry & Icon
cat << 'EOF' > "$APP_DIR/org.theater.TheaterReader.desktop"
[Desktop Entry]
Name=Theater Reader
Comment=Multi-platform Chat & Overlay Reader for Twitch, Kick, and YouTube
Exec=TheaterReader
Icon=org.theater.TheaterReader
Type=Application
Categories=Utility;Network;
Terminal=false
EOF

if [ -f "org.theater.TheaterReader.png" ]; then
    cp org.theater.TheaterReader.png "$APP_DIR/org.theater.TheaterReader.png"
    cp org.theater.TheaterReader.png "$APP_DIR/.DirIcon"
else
    # Create simple PNG icon
    python3 -c "
from PIL import Image, ImageDraw
img = Image.new('RGB', (128, 128), color=(30, 30, 30))
d = ImageDraw.Draw(img)
d.rectangle([(32,32), (96,96)], fill=(0, 122, 204))
d.ellipse([(56,56), (72,72)], fill='white')
img.save('$APP_DIR/org.theater.TheaterReader.png')
img.save('$APP_DIR/.DirIcon')
"
fi

# 4. Create AppRun launcher script
cat << 'EOF' > "$APP_DIR/AppRun"
#!/bin/sh
HERE="$(dirname "$(readlink -f "${0}")")"
export PATH="${HERE}:${PATH}"
export LD_LIBRARY_PATH="${HERE}:${LD_LIBRARY_PATH}"
cd "${HERE}"
exec "${HERE}/TheaterReader" "$@"
EOF
chmod +x "$APP_DIR/AppRun"

# 5. Build AppImage
ARCH=x86_64 ARCH=x86_64 /tmp/squashfs-root/AppRun "$APP_DIR" TheaterReader-x86_64.AppImage --no-appstream

echo "=== AppImage Created Successfully: TheaterReader-x86_64.AppImage ==="
