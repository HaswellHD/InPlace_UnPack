# Performance

Short version: your disk decides how fast this goes, not your CPU.

Everything below was measured on one machine: Windows 11, a 6-core desktop CPU, 32 GB RAM and a cheap
SATA SSD. Cheap SSDs are moody (SLC cache, garbage collection), so the same test can vary a lot between
runs. Take the numbers as rough hints and run the benchmark on your own drive:

```powershell
python -m inplace_unpack bench --size-mb 1024 --runs 2 --json results.json
```

## Where the time goes

Decompressing Deflate in RAM runs at around 1,300–1,900 MB/s on a single core, and CRC-32 at about
9,000 MB/s. Extracting to disk ran at 60–80 MB/s with CPU usage under 10 %. The same drive has to read
the archive, write the output and flush, and that's the limit. More threads don't help with that.

256 KiB chunks beat 1 MiB chunks in RAM, so that's what the engine uses.

## The modes (1.5 GB archive, average of 2 runs)

| Mode | Time | MB/s | CPU | Peak RAM |
|---|---|---|---|---|
| v0.2.0 (old) | 27.5 s | 58.6 | – | – |
| Safe (reads every file back) | 50.7 s | 30.3 | 2 % | 39 MB |
| Balanced | 24.3 s | 63.9 | 3 % | 51 MB |
| Performance | 18.6 s | 82.9 | 6 % | 52 MB |

These were measured with an early draft of the presets. The final ones use fewer threads (see below).

## How much it slows down everything else

While extracting a 1 GB archive, a small probe kept writing, flushing and reading a 64 KB file. Lower
numbers mean the PC stays snappier.

| While running | Extraction | Probe avg | Probe p95 |
|---|---|---|---|
| nothing | – | 9–21 ms | 12–92 ms |
| v0.2.0 | 14–22 s | 10–38 ms | 17–127 ms |
| Safe | 28–30 s | 11–12 ms | 15–17 ms |
| Balanced | 13–19 s | 16–31 ms | 23–99 ms |
| Performance | 13–21 s | 27–63 ms | 149–201 ms |

## Things I tried

- **More threads.** With 8,000 small files, 1–2 workers were fastest. 4 and 8 were slower. With big
  files, extra workers weren't reliably faster but made other programs lag more. So Safe and Balanced use
  1 worker, Performance uses 2.
- **Flushing every 64 MB** instead of only at the end of a file. Other programs stay smoother and you
  don't get those multi-second freezes at the end of huge files.
- **Windows background mode.** About 1.8× slower, and other programs actually lagged *more* (probably
  priority inversion while flushing). Off by default.
- **A write-speed limit** (`max_write_mb_s`, say 60). The gentlest option on the rest of the system
  (probe p95 around 17 ms) for a moderate speed cost. Good if you need to keep using the PC.
- **A "turbo" mode** with 4 MiB blocks, deeper read-ahead and output files sized up front. On the SATA
  SSD it was slower (65–87 MB/s vs. 115 MB/s for the normal path on a 7 GB stored archive), with or
  without intermediate flushes. It didn't make it into a release.

Fast NVMe drives may behave differently. I haven't measured one yet, and more threads might pay off there.
