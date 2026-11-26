# How it's built

```
app_gui.py / app_cli.py   entry points (what PyInstaller builds)
inplace_unpack/
  plan.py       the check before starting, never changes anything
  engine.py     unpacking, worker threads, commits, freeing space
  source.py     the archive as one file or as split parts (.zip.001 ...)
  journal.py    progress file (<zip>.unzip-progress), atomic, with checksum
  names.py      safe and unique Windows file names (deterministic, so resuming works)
  settings.py   modes, advanced settings, limits, saving
  sysinfo.py    CPU / RAM / disk numbers, thread priority
  winfs.py      sparse files, free space, links (Win32 via ctypes)
  jobs.py       list of unfinished jobs, optional autostart
  shellmenu.py  the Explorer right-click entry
  gui.py        the window (Tk)
  cli.py        command line, plus `status` and `bench`
  bench.py      benchmark for the modes
  i18n.py       English and German texts
```

## The one rule everything depends on

For each file in the ZIP, always in this order:

1. Unpack it into a `.part` file. The CRC gets checked along the way.
2. Flush that file to disk (Safe mode also reads it back and checks it again), then rename it to its real name.
3. Every `sync_interval_mb`, write the journal ("N files done"): temp file, flush, rename.
4. Only after that, free the ZIP range `[0, start of file N)` with `FSCTL_SET_ZERO_DATA`. For split ZIPs,
   parts that lie completely before that point are deleted.

Crash before step 3? That file just gets unpacked again, its data is still in the ZIP. Crash between 3 and 4?
Some space isn't freed yet, and the next run frees it. The central directory at the end of the ZIP is never
touched, so the rest of the archive stays readable.

Freeing happens in 256 MB steps with tiny pauses. One huge TRIM can freeze cheap SSDs for seconds.

## Doing several things at once

A coordinator hands consecutive files to a thread pool. How many run at once depends on the thread setting,
`max_temp_gb`, free space and RAM. It always waits for the oldest unfinished file, and commits only ever cover
the unbroken run of finished files at the start. If one fails, nothing new starts, running ones are stopped,
and only that finished run is committed.

Big files go through a little pipeline (one thread reads and decompresses, the other writes) so the CPU and
the disk work at the same time. Small files can be decompressed straight into RAM, within a budget.

## Resuming

The journal stores a fingerprint of the ZIP (SHA-256 over the central directory and the file size), the target
folder and how many files are done. For split ZIPs it also stores the size of every part, so a run can continue
after the first parts are gone. Because `names.py` always produces the same names, a resumed run writes to
exactly the same places. Journals from 0.2 (format 1) still work.

## Planning the space

`plan.py` plays the run through in advance: bytes written (rounded to clusters, plus file system overhead)
minus what gets freed at each commit, plus whatever can be in flight in parallel. The highest point of that
curve plus a reserve is what the check asks for. During the run, free space is checked again before every file,
so it stops cleanly instead of running out halfway through one.
