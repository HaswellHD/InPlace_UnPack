#!/bin/sh
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="${1:-$(python3 -c "import re; print(re.search(r'__version__\s*=\s*\"([^\"]+)\"', open('$ROOT/inplace_unpack/__init__.py').read()).group(1))")}"
VERSION="${VERSION#v}"
OUT="${OUT_DIR:-$ROOT/dist}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

mkdir -p "$OUT" "$WORK/SOURCES" "$WORK/SPECS" "$WORK/BUILD" "$WORK/RPMS" "$WORK/SRPMS"
STAGE="$WORK/inplace-unpack-$VERSION"
mkdir -p "$STAGE"
cp -a "$ROOT/inplace_unpack" "$ROOT/assets" "$ROOT/packaging" "$ROOT/LICENSE" "$ROOT/Readme.md" "$ROOT/Changelog.md" "$STAGE/"
find "$STAGE" -name "__pycache__" -type d -exec rm -rf {} +
tar -C "$WORK" -czf "$WORK/SOURCES/inplace-unpack-$VERSION.tar.gz" "inplace-unpack-$VERSION"

rpmbuild --define "_topdir $WORK" \
         --define "_version $VERSION" \
         --define "dist %{nil}" \
         -bb "$ROOT/packaging/inplace-unpack.spec"

cp "$WORK"/RPMS/noarch/*.rpm "$OUT/"
ls -lh "$OUT"/inplace-unpack-"$VERSION"-*.rpm
