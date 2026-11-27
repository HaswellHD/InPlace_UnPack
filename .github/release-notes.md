## Download

### Windows 10 / 11

- **Inplace-Unpack-Setup.exe**: installer. Adds a Start menu entry and, if you want, the right-click entry
  for ZIP files. No admin rights needed.
- **Inplace-Unpack.exe**: same program without installing. Just double-click it.
- inplace-unpack-cli.exe: command line version, only if you want it.

The files aren't code-signed yet, so Windows SmartScreen will probably warn you the first time:
click "More info" → "Run anyway".

### Linux

**AppImage** (any distro, nothing to install, window and command line in one file):

```sh
chmod +x Inplace-Unpack-x86_64.AppImage
./Inplace-Unpack-x86_64.AppImage                      # window
./Inplace-Unpack-x86_64.AppImage cli big.zip target/  # command line
```

Or straight from the terminal into `~/.local/bin`:

```sh
mkdir -p ~/.local/bin
curl -fL -o ~/.local/bin/inplace-unpack https://github.com/HaswellHD/InPlace_UnPack/releases/download/v{VERSION}/Inplace-Unpack-x86_64.AppImage
chmod +x ~/.local/bin/inplace-unpack
inplace-unpack
```

**Packages** (use your system's Python, get updates through the package):

```sh
sudo apt install ./inplace-unpack_{VERSION}_all.deb        # Debian, Ubuntu, Mint
sudo dnf install ./inplace-unpack-{VERSION}-1.noarch.rpm   # Fedora, RHEL
sudo zypper install ./inplace-unpack-{VERSION}-1.noarch.rpm   # openSUSE
```

After that, `inplace-unpack` opens the window and `inplace-unpack-cli` is the command line.

`inplace-unpack-{VERSION}-linux.tar.gz` is the plain source for everything else: unpack it and run
`./install-linux.sh`. `SHA256SUMS.txt` lets you check the downloads (`sha256sum -c SHA256SUMS.txt`).

## What's new

See [Changelog.md](https://github.com/HaswellHD/InPlace_UnPack/blob/v{VERSION}/Changelog.md).
