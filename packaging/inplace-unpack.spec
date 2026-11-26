Name:           inplace-unpack
Version:        %{?_version:%{_version}}%{!?_version:0.4.0}
Release:        1%{?dist}
Summary:        Extract huge ZIPs on a nearly full disk via fallocate hole punching
License:        MIT
URL:            https://github.com/ezgerazer/InPlace_UnPack-forlinux
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch

Requires:       python3 >= 3.11
Requires:       (python3-tkinter or python3-tk)

%description
Inplace-Unpack extracts ZIP entries in file-offset order and releases the
already-extracted byte ranges of the archive back to the filesystem using
fallocate(FALLOC_FL_PUNCH_HOLE | FALLOC_FL_KEEP_SIZE) on btrfs, ext4, xfs,
f2fs, zfs, and ntfs3. Supports split ZIPs (.zip.001, .002, ...), crash-safe
journaled resume, and includes both GUI and CLI.

%prep
%setup -q

%build
# Pure Python, no compilation needed

%install
rm -rf %{buildroot}
install -d %{buildroot}%{_datadir}/inplace-unpack
cp -a inplace_unpack assets %{buildroot}%{_datadir}/inplace-unpack/
find %{buildroot}%{_datadir}/inplace-unpack -name "__pycache__" -type d -exec rm -rf {} +

install -d %{buildroot}%{_bindir}
cat > %{buildroot}%{_bindir}/inplace-unpack << 'EOF'
#!/bin/sh
PYTHONPATH=/usr/share/inplace-unpack exec python3 -m inplace_unpack.gui "$@"
EOF
cat > %{buildroot}%{_bindir}/inplace-unpack-cli << 'EOF'
#!/bin/sh
PYTHONPATH=/usr/share/inplace-unpack exec python3 -m inplace_unpack.cli "$@"
EOF
chmod 0755 %{buildroot}%{_bindir}/inplace-unpack %{buildroot}%{_bindir}/inplace-unpack-cli

install -Dm0644 packaging/inplace-unpack.desktop %{buildroot}%{_datadir}/applications/inplace-unpack.desktop
install -Dm0644 assets/icon.png %{buildroot}%{_datadir}/icons/hicolor/512x512/apps/inplace-unpack.png

%post
update-desktop-database %{_datadir}/applications >/dev/null 2>&1 || :
gtk-update-icon-cache -f -t %{_datadir}/icons/hicolor >/dev/null 2>&1 || :

%postun
update-desktop-database %{_datadir}/applications >/dev/null 2>&1 || :
gtk-update-icon-cache -f -t %{_datadir}/icons/hicolor >/dev/null 2>&1 || :

%files
%license LICENSE
%doc Readme.md Changelog.md
%{_bindir}/inplace-unpack
%{_bindir}/inplace-unpack-cli
%{_datadir}/inplace-unpack/
%{_datadir}/applications/inplace-unpack.desktop
%{_datadir}/icons/hicolor/512x512/apps/inplace-unpack.png
