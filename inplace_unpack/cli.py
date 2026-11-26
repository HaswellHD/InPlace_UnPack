"""Command line interface (also used by the tests for hard-kill scenarios)."""
from __future__ import annotations

import argparse
import os
import shutil
import sys

from . import __version__, engine, i18n, journal, plan as planmod
from . import settings as st
from .i18n import fmt_bytes, fmt_duration, msg, t


def _kill_fault():
    """INPLACE_UNPACK_TEST_KILL=phase:index makes the process die instantly
    (TerminateProcess-like, no cleanup) at that point. Used by tests only."""
    spec = os.environ.get("INPLACE_UNPACK_TEST_KILL")
    if not spec:
        return None
    phase, idx = spec.split(":")
    idx = int(idx)

    def fault(p, i):
        if p == phase and i >= idx:  # first time this phase reaches entry >= idx
            os._exit(99)
    return fault


def print_plan(p) -> None:
    print(t("summary", entries=len(p.entries), total=p.total_bytes, size=p.archive_size,
            free=p.free, need=p.peak_need + p.reserve))
    for w in p.warnings:
        print("  ! " + msg(w))
    if p.ok:
        print(t("fits"))
    else:
        print(t("not_ok"))
        for pr in p.problems:
            print("  - " + msg(pr))


def build_settings(a) -> st.Settings:
    if a.config:
        s = st.load(a.config)
        if a.mode:
            s.mode = a.mode
    else:
        s = st.load() if not a.mode else st.for_mode(a.mode)
    if a.threads:
        s.auto_threads, s.max_threads = False, a.threads
    if a.sync_mb:
        s.sync_interval_mb = a.sync_mb
    if a.max_cpu:
        s.max_cpu_percent = a.max_cpu
    return st.validate(s)[0]


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "bench":
        from . import bench
        return bench.main(argv[1:])
    if argv and argv[0] == "status":
        return status(argv[1:])
    ap = argparse.ArgumentParser(prog="inplace-unpack",
                                 description="Extract a ZIP while releasing its disk space (destroys the ZIP). "
                                             "Subcommands: 'bench' (benchmark the modes), 'status ARCHIVE'.")
    ap.add_argument("archive")
    ap.add_argument("target")
    ap.add_argument("--check", action="store_true", help="only run the pre-flight check")
    ap.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    ap.add_argument("--overwrite", action="store_true", help="overwrite existing files")
    ap.add_argument("--delete-archive", action="store_true", help="delete the ZIP when finished")
    ap.add_argument("--name-encoding", help="code page for names without UTF-8 flag, e.g. cp850")
    ap.add_argument("--ignore-space", action="store_true", help="start even if the space check fails")
    ap.add_argument("--mode", choices=st.MODES, help="extraction mode (default: saved setting / balanced)")
    ap.add_argument("--config", help="settings JSON file (see examples/settings.example.json)")
    ap.add_argument("--threads", type=int, help="fixed number of worker threads")
    ap.add_argument("--sync-mb", type=int, help="journal/release interval in MB")
    ap.add_argument("--max-cpu", type=int, help="maximum CPU usage in percent")
    ap.add_argument("--version", action="version", version=__version__)
    a = ap.parse_args(argv)
    s = build_settings(a)
    i18n.set_lang(s.language)

    p = planmod.analyze(a.archive, a.target, overwrite=a.overwrite,
                        name_encoding=a.name_encoding, ignore_space=a.ignore_space, settings=s)
    print(f"Mode: {s.mode} · threads: {st.effective_threads(s)} · sync: {s.sync_interval_mb} MB")
    print_plan(p)
    if not p.ok:
        return 2
    if a.check:
        return 0
    if not a.yes:
        print(t("warning_box"))
        if input("YES / JA? ").strip().upper() not in ("YES", "JA"):
            return 1

    is_tty = sys.stdout.isatty()

    def progress(pr: engine.Progress):
        if not is_tty:
            return
        line = (t("status_running", done=pr.entries_done, ntotal=pr.entries_total,
                  bytes=fmt_bytes(pr.bytes_done), btotal=fmt_bytes(pr.bytes_total),
                  speed=fmt_bytes(int(pr.speed)), avg=fmt_bytes(int(pr.avg_speed)),
                  alloc=fmt_bytes(pr.archive_allocated),
                  free=fmt_bytes(pr.free)) + f" · ETA {fmt_duration(pr.eta)}")
        cols = max(40, shutil.get_terminal_size((120, 20)).columns - 1)
        if len(line) > cols:
            line = line[:cols - 1] + "…"
        sys.stdout.write("\r" + line.ljust(cols))
        sys.stdout.flush()

    try:
        r = engine.run(p, progress, durable=True, delete_archive=a.delete_archive,
                       settings=s, _fault=_kill_fault())
    except engine.RunStopped as e:
        if is_tty:
            print()
        print(msg((e.key, e.params)))
        return 3
    if is_tty:
        print()
    print(t("done_msg", entries=r.entries, total=r.bytes))
    print(t("done_deleted") if r.archive_deleted else t("done_keep"))
    if r.damaged_report:
        print("  ! " + t("done_damaged", count=len(r.damaged) or "?", path=r.damaged_report))
    print(f"{fmt_duration(r.elapsed)} · {fmt_bytes(int(r.written / max(r.elapsed, 1e-6)))}/s · "
          f"avg CPU {r.avg_cpu:.0f} % · peak RAM {fmt_bytes(r.peak_ram)}")
    return 0


def status(argv) -> int:
    """Print recovery information of an archive's journal."""
    i18n.set_lang(st.load().language)
    if not argv:
        print("usage: inplace-unpack status ARCHIVE")
        return 2
    d = journal.describe(argv[0])
    if not d["exists"]:
        print(t("no_journal"))
        return 1
    if not d["valid"]:
        print(t("journal_invalid", error=d["error"]))
        return 2
    print(t("journal_view", path=d["path"], target=d.get("target"), done=d.get("done"),
            entries=d.get("entries", "?"), last=d.get("last_entry", "–"),
            mode=d.get("mode", "–"), updated=d.get("updated", "–"), format=d.get("format")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
