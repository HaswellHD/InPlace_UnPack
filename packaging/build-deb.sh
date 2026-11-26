#!/bin/sh
# Builds a Debian/Ubuntu .deb package (architecture: all).
# Uses dpkg-deb if available, otherwise falls back to standard ar + tar + gzip.
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="${1:-$(python3 -c "import re; print(re.search(r'__version__\s*=\s*\"([^\"]+)\"', open('$ROOT/inplace_unpack/__init__.py').read()).group(1))")}"
VERSION="${VERSION#v}"
OUT="${OUT_DIR:-$ROOT/dist}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

PKG="$WORK/pkg"
mkdir -p "$OUT" "$PKG/DEBIAN" \
         "$PKG/usr/bin" \
         "$PKG/usr/share/inplace-unpack" \
         "$PKG/usr/share/applications" \
         "$PKG/usr/share/icons/hicolor/512x512/apps" \
         "$PKG/usr/share/doc/inplace-unpack"

cp -a "$ROOT/inplace_unpack" "$ROOT/assets" "$PKG/usr/share/inplace-unpack/"
find "$PKG/usr/share/inplace-unpack" -name "__pycache__" -type d -exec rm -rf {} +
cp "$ROOT/LICENSE" "$PKG/usr/share/doc/inplace-unpack/copyright"
cp "$ROOT/Readme.md" "$PKG/usr/share/doc/inplace-unpack/Readme.md"
cp "$ROOT/packaging/inplace-unpack.desktop" "$PKG/usr/share/applications/inplace-unpack.desktop"
cp "$ROOT/assets/icon.png" "$PKG/usr/share/icons/hicolor/512x512/apps/inplace-unpack.png"

cat > "$PKG/usr/bin/inplace-unpack" << 'EOF'
#!/bin/sh
PYTHONPATH=/usr/share/inplace-unpack exec python3 -m inplace_unpack.gui "$@"
EOF
cat > "$PKG/usr/bin/inplace-unpack-cli" << 'EOF'
#!/bin/sh
PYTHONPATH=/usr/share/inplace-unpack exec python3 -m inplace_unpack.cli "$@"
EOF
chmod 0755 "$PKG/usr/bin/inplace-unpack" "$PKG/usr/bin/inplace-unpack-cli"

SIZE_KB="$(du -sk "$PKG/usr" | awk '{print $1}')"
cat > "$PKG/DEBIAN/control" << EOF
Package: inplace-unpack
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Installed-Size: $SIZE_KB
Depends: python3 (>= 3.11), python3-tk
Maintainer: ezgerazer <ezgerazer@users.noreply.github.com>
Homepage: https://github.com/ezgerazer/InPlace_UnPack-forlinux
Description: Extract huge ZIPs on a nearly full disk via hole punching
 Inplace-Unpack extracts ZIP entries in file-offset order and frees the
 already-extracted byte ranges of the archive back to the filesystem using
 fallocate(FALLOC_FL_PUNCH_HOLE) on btrfs, ext4, xfs, f2fs, zfs, and ntfs3.
 Supports split ZIPs (.zip.001, .002, ...), crash-safe journaled resume,
 and includes both GUI and CLI.
EOF

cat > "$PKG/DEBIAN/postinst" << 'EOF'
#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t /usr/share/icons/hicolor >/dev/null 2>&1 || true
fi
EOF
cat > "$PKG/DEBIAN/postrm" << 'EOF'
#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications || true
fi
EOF
chmod 0755 "$PKG/DEBIAN/postinst" "$PKG/DEBIAN/postrm"

DEB_FILE="$OUT/inplace-unpack_${VERSION}_all.deb"
rm -f "$DEB_FILE"
if command -v dpkg-deb >/dev/null 2>&1; then
    dpkg-deb --root-owner-group --build "$PKG" "$DEB_FILE"
else
    printf '2.0\n' > "$WORK/debian-binary"
    (cd "$PKG/DEBIAN" && tar --owner=0 --group=0 --numeric-owner -czf "$WORK/control.tar.gz" .)
    (cd "$PKG" && tar --owner=0 --group=0 --numeric-owner --exclude=./DEBIAN -czf "$WORK/data.tar.gz" ./usr)
    ar rcs "$DEB_FILE" "$WORK/debian-binary" "$WORK/control.tar.gz" "$WORK/data.tar.gz"
fi
ls -lh "$DEB_FILE"
