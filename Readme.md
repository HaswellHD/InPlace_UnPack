<p align="center">
  <img src="assets/icon.png" width="96" alt="Inplace-Unpack">
</p>

<h1 align="center">Inplace-Unpack for Linux</h1>

<p align="center">
  Unzip a huge ZIP on Linux even when your disk doesn't have room for the ZIP <i>and</i> the extracted files at the same time.
</p>

<p align="center">
  <img alt="Linux" src="https://img.shields.io/badge/platform-Linux%20(btrfs%20%7C%20ext4%20%7C%20xfs%20%7C%20zfs)-FCC624?logo=linux&logoColor=black">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-green">
  <img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-yellow">
</p>

> **Heads up:** this tool eats the ZIP while it unpacks it. If something goes wrong, the parts that were
> already unpacked are fine and the rest can be resumed, but a broken ZIP can't be "un-eaten".
> Only use it on archives you could download again.

Linux port & optimization fork of [HaswellHD/InPlace_UnPack](https://github.com/HaswellHD/InPlace_UnPack).

---

## What's this?

Suppose you have a 160 GB ZIP and only 130 GB of free space. `unzip`, Ark, File Roller and `7z` all need room
for the archive *and* the extracted files at the same time, so none of them can finish.

**Inplace-Unpack** extracts entries in the exact byte order they sit inside the ZIP. As soon as a batch of
files is safely written, `fsync`ed to disk, and recorded in a crash-safe journal, the corresponding byte range
of the ZIP is punched out with `fallocate(FALLOC_FL_PUNCH_HOLE | FALLOC_FL_KEEP_SIZE)`, returning those blocks
immediately to the filesystem. You only need roughly *(unpacked size − ZIP size)* of free space plus a small
safety reserve.

## Good for

- Google Takeout exports (Photos, Drive, YouTube) on a laptop with a nearly full SSD
- Cloud "Download as ZIP" exports (Nextcloud, Proton Drive, OneDrive, iCloud, Dropbox)
- Restoring large backup ZIPs onto a tight root or `/home` partition
- Big ML, research or GIS datasets distributed as a single giant `.zip` or split `.zip.001, .002, ...`
- Large media collections handed over as ZIP

## Features on Linux

- **Kernel hole punching (`fallocate64`)**: Frees space while extracting on **btrfs, ext4, xfs, f2fs, zfs,
  bcachefs, tmpfs, and ntfs3** — verified dynamically per mount via an anonymous `O_TMPFILE` kernel probe. No
  root privileges required.
- **Btrfs-aware**: Recognizes shared storage pools across Btrfs subvolumes (e.g. Fedora `/` and `/home` on the
  same NVMe partition), handles transparent filesystem compression (`compress=zstd`), and falls back cleanly if
  a target subdirectory crosses a subvolume boundary (`EXDEV`).
- **Split ZIPs (`name.zip.001`, `.002`, ...)**: Each finished volume part is deleted once every entry inside it
  is safely on disk (works even on filesystems without hole punching).
- **Pre-flight safety check**: Verifies encryption flags, compression methods, overlapping/hostile entries,
  symlink collisions, UTF-8 byte-length limits (`NAME_MAX = 255`), and peak disk space *before* touching a
  single byte of the archive.
- **Crash-safe & resumable**: Archive blocks are never punched out before extracted files (`fsync`), the atomic
  checksummed journal (`<zip>.unzip-progress`), and the parent directory entry are flushed to disk. Survives
  power cuts, `SIGKILL`, closed windows, and `ENOSPC` ("disk full").
- **Page-cache friendly**: Uses `POSIX_FADV_SEQUENTIAL` read-ahead on the archive, `fdatasync` steady streaming
  flushes, and `POSIX_FADV_DONTNEED` cache eviction on large extracted files so 100+ GB runs don't flood RAM or
  push desktop apps into swap/zram.
- **Parallel NVMe I/O**: Dedicated per-worker archive handles with 256 KiB read buffers avoid lock/seek
  thrashing across threads (~525 MB/s in Performance mode on Btrfs NVMe).
- **Native Linux Desktop integration**:
  - Automatic **Dark / Light theme** detection (KDE Plasma `kdeglobals` & GNOME `gsettings`) with live **☾/☀**
    and **DE/EN** toggles in the header bar (no restart needed).
  - Native **KDE (`kdialog`)** and **GNOME (`zenity`)** file/folder dialogs when available, with automatic
    fallback to an enhanced Tk dialog.
  - Optional right-click menu entry for **KDE Dolphin** (`~/.local/share/kio/servicemenus`) and **GNOME Files /
    Nautilus** (`~/.local/share/nautilus/scripts`).
  - Optional per-user XDG autostart resume (`~/.config/autostart`) while a job is unfinished.
  - Preserves Unix executable permissions (`+x`) from Unix-created ZIPs while stripping unsafe bits.
- **Zero third-party Python dependencies**, no network access, no telemetry, no root needed.

---

## Install (Linux)

### 1. Install Python 3.11+ and Tkinter

```sh
# Fedora / RHEL
sudo dnf install python3 python3-tkinter git

# Debian / Ubuntu / Linux Mint
sudo apt install python3 python3-tk git

# Arch Linux / CachyOS / EndeavourOS
sudo pacman -S python tk git

# openSUSE
sudo zypper install python3 python3-tk git
```

*(Optional: `kdialog` on KDE or `zenity` on GNOME/GTK is used automatically for native file dialogs — usually pre-installed.)*

### 2. Clone & add to your application launcher

```sh
git clone https://github.com/ezgerazer/InPlace_UnPack-forlinux.git
cd InPlace_UnPack-forlinux
./install-linux.sh
```

This installs (per-user, no `sudo`):
- App menu launcher: `~/.local/share/applications/inplace-unpack.desktop` + icon
- GUI command: `~/.local/bin/inplace-unpack`
- CLI command: `~/.local/bin/inplace-unpack-cli`

*(Make sure `~/.local/bin` is in your `PATH`, or start **Inplace-Unpack** directly from your desktop app launcher.)*

To remove the launcher entries again:

```sh
./install-linux.sh --uninstall
```

Or run directly without installing:

```sh
python3 app_gui.py
```

---

## How to use it

### Graphical interface (`inplace-unpack`)

1. Pick the `.zip` (or `.zip.001` for split archives) and a target folder — or right-click the ZIP in Dolphin /
   Files if you enabled the context-menu option, or paste a path / `file://` URI directly.
2. Choose an extraction mode (**Safe**, **Balanced**, or **Performance**). *Balanced* is great for everyday use.
3. Click **Check** (`F5`). It verifies the archive and tells you whether peak disk usage fits.
4. Click **Start extracting** (`Ctrl+Enter`) and confirm once.
5. Pause any time — the next time you open the app, it picks up right where it left off.

### Command line (`inplace-unpack-cli`)

```sh
inplace-unpack-cli ARCHIVE.zip TARGET_FOLDER [--check] [--yes] [--mode safe|balanced|performance] \
                   [--config settings.json] [--threads N] [--sync-mb N] [--max-cpu PCT] \
                   [--overwrite] [--delete-archive] [--name-encoding cp850] [--ignore-space]

inplace-unpack-cli status ARCHIVE.zip       # inspect an interrupted run's journal
inplace-unpack-cli bench [--size-mb 1024]   # benchmark all modes on your real disk (/var/tmp)
```

Exit codes: `0` done, `1` cancelled by user, `2` pre-flight check failed, `3` stopped cleanly (resumable).

---

## Modes

| | Safe | Balanced *(default)* | Performance |
|---|---|---|---|
| **Goal** | maximum verification | fast, desktop stays responsive | maximum throughput |
| **Worker threads** | 1 | 1 (+ decompression helper for large files) | up to 4 on Linux (+ helpers) |
| **Worker CPU priority** | `nice +5` | `nice +5` | `nice 0` (normal) |
| **Journal & hole-punch every** | 64 MB | 1 GB | 2 GB |
| **Re-reads every file to verify CRC** | yes | no | no |
| **RAM budget** | up to 256 MB | up to 512 MB | up to 1 GB |
| **Damaged entry (CRC error)** | stops | keeps unchanged + logs in `<zip>.damaged.txt` | keeps unchanged + logs |

Regardless of mode, archive bytes are **never** released before the extracted file and the journal commit have
been flushed to disk (`fsync`).

---

## Settings

All options are available under **Advanced settings** in the GUI or via `--config settings.json`
(see [examples/settings.example.json](examples/settings.example.json)). On Linux, settings are stored in
`${XDG_CONFIG_HOME:-~/.config}/Inplace-Unpack/settings.json`. Out-of-range values are automatically clamped to
safe limits.

Key settings:

- `max_write_mb_s` — caps write throughput so other apps keep full disk responsiveness.
- `priority` (`idle` / `below_normal` / `normal`) & `background_mode` (Linux `ioprio` idle class) — applied
  only to worker threads so the GUI thread stays responsive.
- `sync_interval_mb` — how often the journal commits and holes are punched into the ZIP.
- `keep_damaged` — keep CRC-damaged entries and list them in `<zip>.damaged.txt`, or stop immediately.
- `delete_parts` — delete finished `.zip.001, .002, ...` parts of split archives.
- `auto_resume` / `resume_after_reboot` — automatic resume and temporary `~/.config/autostart` entry.
- `explorer_menu` — per-user right-click action in KDE Dolphin / GNOME Files.

---

## Requirements

- **Linux** (64-bit or 32-bit, e.g. Fedora, Ubuntu/Debian, Arch, openSUSE) with **Python 3.11+** and `tkinter`
  *(Windows 10/11 remains supported in the same codebase as well)*.
- Archive located on a filesystem supporting `FALLOC_FL_PUNCH_HOLE`: **btrfs, ext4, xfs, f2fs, zfs, bcachefs,
  ntfs3, or tmpfs** (FAT32 and exFAT do *not* support hole punching, except for split `.zip.001` archives where
  whole parts are deleted).
- Target folder on the **same filesystem / Btrfs storage pool** as the ZIP so freed blocks benefit the target.
- Free space of roughly *(unpacked size − ZIP size)* plus the safety reserve shown by **Check**.

## Performance

Measured on Fedora 45 (`btrfs` with `compress=zstd:1` on NVMe, Python 3.15):

- **Safe / Balanced** (1 worker + pipeline): **~235–245 MB/s** (~3% total CPU)
- **Performance** (4 workers with dedicated read handles): **~525 MB/s** (~10% total CPU)

Run `inplace-unpack-cli bench --size-mb 1024` to measure your own drive (automatically uses `/var/tmp` when
`/tmp` is a RAM-backed `tmpfs`).

---

## Safety & Limitations

- **Path safety**: Every archive path is sanitized (no `..` zip-slip, control characters, or overlong >255-byte
  UTF-8 names). Directory symlinks inside the target folder are never followed, and symlinks are never `chmod`ed.
- **Exclusive archive lock**: `SparseFile` takes an `flock(LOCK_EX | LOCK_NB)` advisory lock while punching
  holes so two instances cannot corrupt each other.
- **Unsupported formats**: Encrypted ZIPs, Deflate64, 7z, RAR, `tar.*`, and `.z01/.z02` spanned archives are
  refused cleanly during the pre-flight check before anything is modified.
- **Btrfs / ZFS snapshots & reflinks**: If a filesystem snapshot (e.g. Snapper / Timeshift) or `cp --reflink`
  copy still references the ZIP's extents, punching holes in the ZIP cannot reclaim physical disk blocks until
  the snapshot/reflink is removed. If free space runs low, Inplace-Unpack pauses cleanly in a resumable state.
- **Logical vs. allocated size**: `ls -lh` continues to show the ZIP's original logical length while it is
  sparse. Use `du -h ARCHIVE.zip` (or `stat -c '%b*512'`) to see its real on-disk block usage shrink toward zero.

---

## Running the tests

```sh
python3 -m venv .venv
.venv/bin/pip install pytest
.venv/bin/python -m pytest tests -q
```

To also run the >4 GB ZIP64 test (requires ~10 GB of free space):

```sh
INPLACE_UNPACK_LARGE=1 .venv/bin/python -m pytest tests/test_zip64.py -q
```

## License & Credits

MIT, see [LICENSE](LICENSE).
Original concept and Windows implementation by [HaswellHD](https://github.com/HaswellHD/InPlace_UnPack); Linux
filesystem engine, performance optimizations, and Linux desktop UI maintained in this repository.
