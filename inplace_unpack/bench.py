"""Benchmark the three extraction modes on identical archives.

    inplace-unpack bench [--dir FOLDER] [--size-mb 1024] [--small 3000] [--runs 1]
                         [--compression deflate|stored] [--json results.json]

A test archive (a few large files + many small ones, partly compressible) is
generated once. Every run works on a fresh byte-identical copy of it (the
tool destroys the archive), and the output is deleted afterwards. Runs are
done in rotating order to spread out disk-cache effects.
Needs about 3x --size-mb of free space in --dir.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import tempfile
import time
import zipfile

from . import engine, plan as planmod, settings as st, sysinfo, winfs
from .i18n import fmt_bytes, fmt_duration

MiB = 1024 * 1024


def make_archive(path: str, size_mb: int, small: int, compression: int) -> int:
    rnd = random.Random(42)
    block = rnd.randbytes(MiB)
    total = 0
    small_bytes = min(size_mb * MiB // 5, small * 64 * 1024)
    big_total = size_mb * MiB - small_bytes
    with zipfile.ZipFile(path, "w", compression, compresslevel=1 if compression else None) as z:
        nbig = 4
        for i in range(nbig):
            with z.open(zipfile.ZipInfo(f"large/file{i}.bin"), "w", force_zip64=True) as w:
                left = big_total // nbig
                k = 0
                while left > 0:
                    n = min(MiB, left)
                    # half random, half zeros -> ~2:1 compressible
                    chunk = (block[: n // 2] + bytes(n - n // 2)) if k % 2 else block[:n]
                    w.write(chunk[:n])
                    left -= n
                    k += 1
                total += big_total // nbig
        per = max(1, small_bytes // max(small, 1))
        for i in range(small):
            sz = max(100, int(per * (0.2 + 1.6 * rnd.random())))
            z.writestr(f"small/{i // 500:03}/f{i:05}.dat", rnd.randbytes(sz // 2) + bytes(sz - sz // 2))
            total += sz
    return total


def run_one(src: str, workdir: str, mode: str, settings: st.Settings | None = None) -> dict:
    arc = os.path.join(workdir, f"bench-{mode}.zip")
    out = os.path.join(workdir, f"out-{mode}")
    shutil.copyfile(src, arc)
    try:
        s = settings or st.for_mode(mode)
        p = planmod.analyze(arc, out, settings=s)
        if not p.ok:
            raise RuntimeError(f"plan failed: {p.problems}")
        samples = []
        sampler = sysinfo.Sampler()
        last = [0.0]

        def prog(pr):
            now = time.monotonic()
            if now - last[0] >= 0.5:
                last[0] = now
                samples.append(sampler.sample())
        r = engine.run(p, prog, settings=s)
        cpu = [x["proc_cpu"] for x in samples] or [0.0]
        sys_cpu = [x["sys_cpu"] for x in samples] or [0.0]
        wr = [x["write_bps"] for x in samples] or [0.0]
        return {"mode": mode, "threads": st.effective_threads(s), "seconds": r.elapsed,
                "bytes": r.written, "mb_s": r.written / MiB / max(r.elapsed, 1e-6),
                "avg_cpu": sum(cpu) / len(cpu), "max_cpu": max(cpu),
                "avg_sys_cpu": sum(sys_cpu) / len(sys_cpu),
                "peak_ram": sampler.peak_ram, "avg_write_mb_s": sum(wr) / len(wr) / MiB}
    finally:
        shutil.rmtree(out, ignore_errors=True)
        for f in (arc, arc + ".unzip-progress"):
            try:
                os.remove(f)
            except OSError:
                pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="inplace-unpack bench")
    ap.add_argument("--dir", default=None, help="working folder (NTFS); default: %%TEMP%%")
    ap.add_argument("--size-mb", type=int, default=1024)
    ap.add_argument("--small", type=int, default=3000, help="number of small files")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--compression", choices=("deflate", "stored"), default="deflate")
    ap.add_argument("--modes", default=",".join(st.MODES))
    ap.add_argument("--json", help="write results to this JSON file")
    a = ap.parse_args(argv)
    modes = [m for m in a.modes.split(",") if m in st.MODES]

    base = a.dir or tempfile.gettempdir()
    work = tempfile.mkdtemp(prefix="inplace-unpack-bench-", dir=base)
    need = a.size_mb * MiB * 3
    if winfs.free_bytes(work) < need:
        print(f"Not enough free space in {work}: need ~{fmt_bytes(need)}")
        return 2
    try:
        src = os.path.join(work, "source.zip")
        print(f"Creating test archive ({a.size_mb} MB, {a.small} small files, {a.compression}) ...")
        total = make_archive(src, a.size_mb, a.small,
                             zipfile.ZIP_DEFLATED if a.compression == "deflate" else zipfile.ZIP_STORED)
        print(f"  {fmt_bytes(total)} uncompressed, archive {fmt_bytes(os.path.getsize(src))}")
        results = []
        for run in range(a.runs):
            order = modes[run % len(modes):] + modes[:run % len(modes)]
            for m in order:
                print(f"run {run + 1}/{a.runs}: {m} ...", flush=True)
                results.append(run_one(src, work, m))
        print()
        print(f"{'mode':<12}{'threads':>8}{'time':>9}{'MB/s':>9}{'CPU avg':>9}{'CPU max':>9}"
              f"{'sys CPU':>9}{'peak RAM':>11}{'write MB/s':>12}")
        for m in modes:
            rs = [r for r in results if r["mode"] == m]
            avg = {k: sum(r[k] for r in rs) / len(rs) for k in rs[0] if k != "mode"}
            print(f"{m:<12}{int(avg['threads']):>8}{fmt_duration(avg['seconds']):>9}"
                  f"{avg['mb_s']:>9.1f}{avg['avg_cpu']:>8.0f}%{avg['max_cpu']:>8.0f}%"
                  f"{avg['avg_sys_cpu']:>8.0f}%{fmt_bytes(int(avg['peak_ram'])):>11}"
                  f"{avg['avg_write_mb_s']:>12.1f}")
        print("\nCPU = this process, % of all cores. Results depend heavily on the disk.")
        if a.json:
            with open(a.json, "w", encoding="utf-8") as f:
                json.dump({"cpu_count": os.cpu_count(), "results": results}, f, indent=2)
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)
