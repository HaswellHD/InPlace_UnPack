<p align="center">
  <img src="assets/icon.png" width="96" alt="">
</p>

<h1 align="center">Inplace-Unpack</h1>

<p align="center">
  Unzip a huge ZIP even when your disk doesn't have room for the ZIP <i>and</i> the files.
</p>

<p align="center">
  <img alt="Windows" src="https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-blue">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-green">
  <img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-yellow">
</p>

> **Heads up:** this tool eats the ZIP while it unpacks it. If something goes wrong, the parts that were
> already unpacked are fine and the rest can be resumed, but a broken ZIP can't be "un-eaten".
> Only use it on archives you could download again.

## What's this?

I had a 160 GB ZIP and 130 GB of free space. Explorer, 7-Zip and WinRAR all need room for the archive and
the extracted files at the same time, so none of them worked.

Inplace-Unpack unpacks the files in the order they sit inside the ZIP. As soon as a file is safely on disk,
the part of the ZIP it came from is given back to Windows (NTFS sparse files). So you only need about as
much free space as the ZIP itself, not double.

![Main window](docs/screenshots/main-window.png)

## Good for

- Google Takeout exports (photos, Drive, YouTube) on a laptop with a small SSD
- "Download as ZIP" exports from iCloud, OneDrive, Dropbox or social networks
- restoring your own backup ZIPs onto a nearly full disk
- big datasets (ML, research, GIS) that come as one giant ZIP or as `.zip.001, .002, ...`
- photo and video collections handed over as ZIP

## What it does

- Frees space while unpacking (NTFS / ReFS).
- Split ZIPs (`name.zip.001`, `.002`, ... like 7-Zip's "split to volumes"): each part is deleted once
  everything in it is unpacked. You can turn that off.
- Checks everything first: encryption, compression method, broken or malicious entries, file names, and
  whether the space will actually be enough. Nothing is touched before that check passes.
- Crash-safe. A piece of the ZIP is only released after the file is written, flushed and recorded in a
  small journal. Power cut, crash, closed window, full disk: start it again and it continues.
- Resumes on its own when you open it again, and retries after "disk full" or a temporary error.
- Damaged files inside the ZIP (CRC errors) are kept as they are, listed in `<zip>.damaged.txt`, and the
  rest keeps going (Safe mode stops instead).
- Three modes (Safe, Balanced, Performance) and a bunch of advanced settings.
- Live monitor: speed, average speed, time left, CPU, RAM, disk.
- Optional right-click entry in Explorer: *Extract with Inplace-Unpack* (Windows 11: under
  *Show more options*). Per user, no admin rights.
- Handles ZIP64 (files over 4 GB, more than 65,535 entries), Unicode names, Deflate, BZIP2, LZMA,
  Zstandard and Stored.
- English by default, German in the settings.
- No dependencies, no network, no telemetry, no admin rights.

## Install

Grab `Inplace-Unpack.exe` from [Releases](https://github.com/HaswellHD/InPlace_UnPack/releases) and run it.
No Python needed. The file isn't code-signed yet, so Windows SmartScreen will probably warn you the first time
("More info" → "Run anyway").

Or run it from source:

```powershell
git clone https://github.com/HaswellHD/InPlace_UnPack.git
cd InPlace_UnPack
python app_gui.py
```

## Linux (this fork)

This fork adds Linux support next to the unchanged Windows code. Instead of NTFS sparse files it
releases space with `fallocate(FALLOC_FL_PUNCH_HOLE)`, which works on **btrfs, ext4, xfs**, f2fs and
tmpfs without root.

```sh
sudo dnf install python3-tkinter        # Debian/Ubuntu: sudo apt install python3-tk
git clone https://github.com/ezgerazer/InPlace_UnPack-forlinux.git
cd InPlace_UnPack-forlinux
./install-linux.sh                      # app-menu entry + `inplace-unpack` / `inplace-unpack-cli`
```

What is different on Linux:

- **Hole punching & page-cache control** (`inplace_unpack/_winfs_posix.py`): kernel-probed `fallocate64(FALLOC_FL_PUNCH_HOLE)` via `O_TMPFILE` (supports btrfs, ext4, xfs, f2fs, zfs, bcachefs, ntfs3, tmpfs), Btrfs subvolume pool detection, `POSIX_FADV_SEQUENTIAL` read-ahead, `POSIX_FADV_DONTNEED` cache eviction on large files, `fdatasync` streaming flushes, and directory `fsync` on journal commits.
- **Parallel I/O & priority** (`engine.py`, `_sysinfo_posix.py`): dedicated per-worker archive handles (no shared `ZipFile` lock/seek thrashing), `/proc` resource monitor, per-worker `nice` / `SCHED_IDLE` / `ioprio`, and preservation of Unix `+x` permissions.
- **Native desktop UI** (`gui.py`, `shellmenu.py`, `jobs.py`): automatic Dark/Light theme (KDE `kdeglobals` / GNOME `gsettings`) with live `☾/☀` and `DE/EN` toggles, native `kdialog` / `zenity` file pickers, KDE Dolphin ServiceMenu + GNOME Nautilus script, and XDG autostart (`~/.config/autostart`).
- **Full test suite**: all tests pass on Linux (`pytest tests -q`, Fedora 45, KDE, btrfs, Python 3.15).

## How to use it

1. Pick the ZIP (or the first part, `.zip.001`) and a target folder. Or right-click the ZIP in Explorer.
2. Choose a mode if you want. Balanced is fine for most people.
3. Click **Check**. It tells you if it fits and what, if anything, is wrong.
4. Click **Start extracting** and confirm once.
5. You can pause any time. Next time you open the program it carries on by itself.

There's also a command line version:

```powershell
inplace-unpack-cli ARCHIVE.zip TARGET_FOLDER [--check] [--yes] [--mode safe|balanced|performance]
                   [--config settings.json] [--threads N] [--sync-mb N] [--max-cpu PCT]
                   [--overwrite] [--delete-archive] [--name-encoding cp850] [--ignore-space]
inplace-unpack-cli status ARCHIVE.zip      # what an interrupted run left behind
inplace-unpack-cli bench [--size-mb 1024]  # try the modes on your own disk
```

Exit codes: `0` done, `1` cancelled, `2` check failed, `3` stopped but resumable.

## Modes

| | Safe | Balanced (default) | Performance |
|---|---|---|---|
| Idea | as careful as possible | fast, PC stays usable | as fast as it gets |
| Worker threads | 1 | 1 (+1 helper for big files) | 2 (+ helpers) |
| CPU priority | below normal | below normal | normal |
| Journal and space release every | 64 MB | 1 GB | 2 GB |
| Re-reads every file to verify it | yes | no | no |
| RAM it may use | up to 256 MB | up to 512 MB | up to 1 GB |
| Damaged entry | stops | keeps it, continues | keeps it, continues |

No matter which mode you pick, a piece of the ZIP is only freed after the file and the journal entry are on
disk. There's no setting to turn that off.

## Settings

Everything is under **Advanced settings** in the app, or in a JSON file you pass with `--config`
(see [examples/settings.example.json](examples/settings.example.json)). The app keeps its settings in
`%APPDATA%\Inplace-Unpack\settings.json`. Values outside sensible limits get clamped.

The ones you'll most likely care about:

- `max_write_mb_s` caps the write speed. Best option if you want to keep using the PC while it runs.
- `priority` (idle / below_normal / normal) only affects the worker threads; the window stays snappy.
- `sync_interval_mb` sets how often the journal is written and space is released.
- `keep_damaged` decides whether a damaged entry stops the run or is kept and listed.
- `delete_parts` decides whether finished parts of a split ZIP are deleted.
- `auto_resume` / `resume_after_reboot` control what happens after an interruption.
- `explorer_menu` adds or removes the right-click entry.

The rest (threads, CPU cap, RAM budget, temp folder, flush interval, ...) is explained right next to each
option in the app.

## Requirements

- Windows 10 or 11, 64-bit
- The ZIP has to be on an NTFS or ReFS drive (FAT32 and exFAT don't support sparse files). Split ZIPs work
  without that, since whole parts are deleted.
- Target folder on the same drive as the ZIP, otherwise freeing space doesn't help.
- Roughly *(unpacked size − ZIP size)* free, plus the small reserve the check shows you.
- From source: Python 3.11 or newer.

## How fast is it?

On my test PC (6-core CPU, cheap SATA SSD) it ran at 60–80 MB/s and used under 10 % CPU. The disk is the
limit, not the processor, so more threads mostly don't help on a SATA SSD. A faster drive, or having the ZIP
and the target on two different drives, makes a much bigger difference. Details and numbers:
[docs/Performance.md](docs/Performance.md). Run `inplace-unpack-cli bench` to test your own disk.

## Safety

- No admin rights, no network access, no telemetry.
- Defender stays on. The tool never asks for antivirus exceptions.
- Every output path is cleaned up and checked so nothing lands outside the target folder; junctions are never followed.
- Nobody else can write to the ZIP while it's being unpacked.
- The journal (`<zip>.unzip-progress`) is replaced atomically and has a checksum.

More in [docs/Reliability.md](docs/Reliability.md) and [Security.md](Security.md).

## Limitations

- Not supported: encrypted ZIPs, Deflate64 (Windows Explorer uses it for some big files), 7z, RAR, tar.gz,
  and WinZip-style spanned archives (`.z01, .z02, ..., .zip`). They're rejected before anything changes.
  Multi-part 7z/RAR can't be done safely: those formats keep important data at the end or compress "solid".
- With System Restore points on the drive, Windows may hold on to the freed space. The tool notices that and
  stops cleanly.
- Cheap USB sticks that ignore flush commands can lose data on power loss, whatever the software does.
- Explorer keeps showing the ZIP's old size. Check "Size on disk" in its properties to see it shrink.
- The release .exe isn't signed yet, so expect SmartScreen warnings and the occasional false positive from
  an antivirus (common with PyInstaller apps).

## Building it yourself

Double-click `build.cmd`. It sets up a local Python environment (`.venv`), installs the build tools, runs the
tests and drops `Inplace-Unpack.exe` and `inplace-unpack-cli.exe` into `dist\`. You need Python 3.11+.
Use `build.cmd -SkipTests` to skip the roughly 4-minute test run.

By hand:

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
.\build.ps1
```

If Inno Setup 6 is installed you also get an installer. Signing is optional, see [docs/Signing.md](docs/Signing.md).
The big-file test (over 4 GB, needs about 10 GB free) runs with `$env:INPLACE_UNPACK_LARGE="1"; python -m pytest tests/test_zip64.py`.

## Contributing

Bug reports and pull requests are welcome, see [Contributing.md](Contributing.md).

## License

MIT, see [LICENSE](LICENSE). Uses only the Python standard library; the .exe is built with PyInstaller,
whose license explicitly allows that for any project.
