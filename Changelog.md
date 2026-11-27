# Changelog

## 0.5.0 (2026-11-27), now also for Linux

New:
- Linux support: frees space with hole punching on btrfs, ext4, xfs, f2fs, zfs,
  bcachefs and tmpfs (tested per drive, no root), btrfs subvolumes, dark/light theme, KDE/GNOME file
  dialogs, right-click entry in Dolphin and GNOME Files, autostart resume, keeps the executable bit.
- Releases now come with ready-made downloads: a Windows installer (`Inplace-Unpack-Setup.exe`) next to the
  portable `.exe`, and for Linux an AppImage, `.deb`, `.rpm`, a source tarball and a Nix flake.
  All of it is built automatically by GitHub Actions.
- Each worker thread reads the archive through its own handle (faster in Performance mode).
- Windows keeps its classic window; the Linux window has its own look (theme, language button).

Fixed:
- The command line version crashed with `UnicodeEncodeError` on Windows when its output was redirected to
  a file or another program (older Python versions use the console code page there).
- Long Unicode file names are also shortened to fit Linux' 255-byte limit.
- A temp folder on another drive failed on Windows ("Bad file descriptor") after the copy logic was
  reworked for Linux.

## 0.4.0 (2026-11-26), first public release

New:
- Split ZIPs (`name.zip.001`, `.002`, ...). They're unpacked as one archive and each part is deleted once
  everything in it is done (`delete_parts`, on by default). Still resumable after parts are gone.
- Right-click entry "Extract with Inplace-Unpack" for `.zip` / `.zip.001` (setting `explorer_menu`, per user,
  also an option in the installer).
- Average speed next to the current speed. Time left is based on the average now, so it jumps around less.
- Damaged files (CRC errors) no longer stop Balanced/Performance. They're kept as they are and listed in
  `<zip>.damaged.txt`.
- Optional code signing in `build.ps1`, and `build.cmd` so you can build with a double-click.

Changed:
- Resuming is fully automatic: no countdown, no extra confirmation.
- The reason for the last stop stays visible instead of being overwritten by the automatic re-check.
- Writing is steadier: flushes run in the background but never more than one block ahead.
  Performance mode flushes every 64 MB like the others.
- The next file starts before the previous one is committed and its space is freed.
- Space is freed in 256 MB steps with short pauses. Huge single TRIMs froze cheap SSDs for seconds.
- English by default (German in the settings), no more extra confirmation checkbox, the mode panel folds away.

## 0.3.0 (2026-11-25)

- Three modes: Safe, Balanced (default) and Performance, plus advanced settings for CPU, RAM, storage,
  journal and recovery. Everything is checked and clamped, saved in `%APPDATA%\Inplace-Unpack\settings.json`.
  The CLI got `--mode`, `--config`, `--threads`, `--sync-mb` and `--max-cpu`.
- Several files can be unpacked at once; commits only cover the unbroken run of finished files.
- Big files go through a read/write pipeline, small ones can be decompressed in RAM.
- CPU and write-speed limits, worker thread priority (the window stays at normal priority).
- Regular flushing while writing big files.
- Safe mode reads every file back and checks it.
- Optional temp folder for unfinished files.
- Journal format 2 with a checksum. Format 1 still works.
- Automatic resume, optional resume after reboot, retries after "disk full" and temporary errors.
- Live monitor, recovery info, `status` and `bench` commands, an icon.
- Renamed to Inplace-Unpack.
- Runs started with 0.2 can be continued (tested with the real 0.2.0 build).

## 0.2.0 (2026-11-25)

First solid version: check before starting, crash-safe order (write, flush, rename, journal, free), resumable
journal, protection against nasty file names, window and command line, tests, .exe build.

## 0.1.0

The original prototype script.
