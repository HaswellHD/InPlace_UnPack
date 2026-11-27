#!/bin/sh
# Builds dist/Inplace-Unpack-x86_64.AppImage (window + command line in one file).
# Needs: Python 3.11+ with tkinter and PyInstaller (pip install pyinstaller), curl, x86_64 Linux.
# Build on an old distro (the release workflow uses Ubuntu 22.04) so the AppImage
# also runs on older systems: it works on glibc versions >= the build system's.
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-python3}"
OUT="${OUT_DIR:-$ROOT/dist}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$OUT"

"$PY" -c "import tkinter" || { echo "tkinter missing for $PY" >&2; exit 1; }

# 1. the program itself (one folder, no Python needed on the target system)
"$PY" -m PyInstaller --noconfirm --clean --onedir --name inplace-unpack \
    --add-data "$ROOT/assets/icon.png:assets" \
    --paths "$ROOT" --workpath "$WORK/build" --specpath "$WORK" --distpath "$WORK/dist" \
    "$ROOT/packaging/appimage_entry.py"

# 2. AppDir layout
APPDIR="$WORK/AppDir"
mkdir -p "$APPDIR/usr/lib"
cp -a "$WORK/dist/inplace-unpack" "$APPDIR/usr/lib/inplace-unpack"
cp "$ROOT/assets/icon.png" "$APPDIR/inplace-unpack.png"
cp "$ROOT/assets/icon.png" "$APPDIR/.DirIcon"
cp "$ROOT/packaging/inplace-unpack.desktop" "$APPDIR/inplace-unpack.desktop"
cat > "$APPDIR/AppRun" << 'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/inplace-unpack/inplace-unpack" "$@"
EOF
chmod 0755 "$APPDIR/AppRun"

# 3. pack it
TOOL="${APPIMAGETOOL:-$WORK/appimagetool}"
if [ ! -x "$TOOL" ]; then
    curl -fsSL -o "$TOOL" \
        https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
    chmod +x "$TOOL"
fi
# extract-and-run: works without FUSE (CI runners, containers)
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$TOOL" --no-appstream "$APPDIR" "$OUT/Inplace-Unpack-x86_64.AppImage"
ls -lh "$OUT/Inplace-Unpack-x86_64.AppImage"
