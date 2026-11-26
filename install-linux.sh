#!/bin/sh
# Installs Inplace-Unpack for the current user on Linux (no root needed):
# launcher scripts in ~/.local/bin, app-menu entry and icon.
# Requires: python3 (>= 3.11) and tkinter (Fedora: sudo dnf install python3-tkinter).
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
BIN="$HOME/.local/bin"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICONS="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/512x512/apps"

if ! python3 -c "import tkinter" 2>/dev/null; then
    echo "tkinter missing. Fedora: sudo dnf install python3-tkinter | Debian/Ubuntu: sudo apt install python3-tk" >&2
    exit 1
fi

mkdir -p "$BIN" "$APPS" "$ICONS"
cp "$DIR/assets/icon.png" "$ICONS/inplace-unpack.png"

printf '#!/bin/sh\nexec python3 "%s/app_gui.py" "$@"\n' "$DIR" > "$BIN/inplace-unpack"
printf '#!/bin/sh\nexec python3 "%s/app_cli.py" "$@"\n' "$DIR" > "$BIN/inplace-unpack-cli"
chmod +x "$BIN/inplace-unpack" "$BIN/inplace-unpack-cli"

cat > "$APPS/inplace-unpack.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Inplace-Unpack
GenericName=ZIP extractor (space-saving)
GenericName[de]=ZIP-Entpacker (platzsparend)
Comment=Extract huge ZIPs even without room for the ZIP and its contents
Comment[de]=Riesige ZIPs entpacken, auch wenn kein Platz für ZIP und Inhalt gleichzeitig ist
Exec=$BIN/inplace-unpack %f
Icon=inplace-unpack
Terminal=false
Categories=Utility;Archiving;Compression;
MimeType=application/zip;application/x-zip-compressed;
StartupWMClass=inplace-unpack
Keywords=zip;unzip;extract;entpacken;
EOF

update-desktop-database "$APPS" 2>/dev/null || true
gtk-update-icon-cache -f -t "$(dirname "$(dirname "$ICONS")")" 2>/dev/null || true
command -v kbuildsycoca6 >/dev/null && kbuildsycoca6 >/dev/null 2>&1 || true
echo "Installed. Start 'Inplace-Unpack' from the app menu or run: inplace-unpack"
