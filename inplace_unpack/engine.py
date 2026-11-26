"""Extraction engine.

Order of operations for every entry (this order is what makes it crash-safe,
and no setting can change it):

  1. extract the entry into a .part file (CRC is verified while reading)
  2. fsync the .part file (optionally read it back and verify the CRC),
     then os.replace() it to its final name
  3. every `sync_interval` MB: write the journal ("N entries done") atomically
  4. only then release the archive bytes of the committed entries

A crash before 3 means the entry is extracted again on resume (its source is
still intact). A crash between 3 and 4 only leaks space, which the resume
releases again. The archive bytes of an entry are never released before the
extracted file is safely on disk.

Parallelism: up to N worker threads extract consecutive entries at the same
time, each with its own independent archive reader handle so workers do not
contend on ZipFile locks or invalidate each other's read-ahead buffers.
Commits only ever cover the *contiguous* prefix of finished entries, so
the rule above still holds. Large entries are streamed through a two-stage
pipeline (decompress thread -> bounded queue -> writer), small entries can be
decompressed completely in RAM and written with one write call.
"""
from __future__ import annotations

import errno
import os
import queue
import shutil
import stat
import threading
import time
import zipfile
import zlib
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import wait as wait_futures
from dataclasses import dataclass, field
from typing import Callable

from . import __version__, journal, jobs, source, sysinfo, winfs
from . import settings as settingsmod
from .plan import MiB, Plan, align_down, round_up

CHUNK = 256 * 1024          # measured: faster than 1 MiB (fits CPU caches)
PIPELINE_MIN = 8 * MiB     # entries at least this big use the decompress/write pipeline
SPACE_GUARD = 32 * MiB
COMMIT_BYTES: int | None = None  # tests only: overrides settings.sync_interval_mb

if os.name != "nt":
    _UMASK = os.umask(0o022)
    os.umask(_UMASK)
else:
    _UMASK = 0


class RunStopped(Exception):
    """The run stopped in a clean, resumable state (unless resumable=False)."""

    def __init__(self, key: str, resumable: bool = True, **params):
        super().__init__(key, params)
        self.key = key
        self.params = params
        self.resumable = resumable


class SimulatedCrash(BaseException):
    """Only used by tests: behaves like the process dying (no cleanup)."""


class _Abort(Exception):
    """Internal: a worker was asked to stop (pause, error elsewhere, crash)."""


@dataclass
class Progress:
    entries_done: int
    entries_total: int
    bytes_done: int
    bytes_total: int
    current: str
    archive_allocated: int
    free: int
    elapsed: float = 0.0
    speed: float = 0.0           # bytes/s, smoothed
    avg_speed: float = 0.0       # bytes/s, average since this run started
    eta: float | None = None     # seconds
    threads: int = 1
    active: int = 0
    stats: dict = field(default_factory=dict)
    low_space: bool = False
    phase: str = "extract"


@dataclass
class Result:
    entries: int
    bytes: int
    archive_deleted: bool
    elapsed: float = 0.0
    avg_cpu: float = 0.0
    peak_ram: int = 0
    written: int = 0
    damaged: list = field(default_factory=list)   # entries kept although their CRC was wrong
    damaged_report: str = ""                      # file that lists them


class Throttle:
    """Keeps process CPU use and write speed under the configured limits."""

    def __init__(self, max_cpu_percent: int, max_write_mb_s: int):
        self.ncpu = os.cpu_count() or 1
        self.cpu_budget = max_cpu_percent / 100.0 * self.ncpu  # in "cores"
        self.cpu_on = max_cpu_percent < 100
        self.wbps = max_write_mb_s * MiB
        self.lock = threading.Lock()
        self.t0 = time.monotonic()
        self.c0 = sysinfo.process_cpu_seconds()
        self.written = 0

    def wrote(self, n: int) -> None:
        if not self.cpu_on and not self.wbps:
            return
        delay = 0.0
        with self.lock:
            now = time.monotonic()
            el = now - self.t0
            if self.cpu_on and el >= 0.05:
                used = sysinfo.process_cpu_seconds() - self.c0
                over = used - el * self.cpu_budget
                if over > 0:
                    delay = over / self.cpu_budget
            if self.wbps:
                self.written += n
                ahead = self.written / self.wbps - el
                delay = max(delay, ahead)
            if el > 2.0:  # sliding window
                self.t0, self.c0, self.written = now, sysinfo.process_cpu_seconds(), 0
        if delay > 0:
            time.sleep(min(delay, 0.5))


class _Budget:
    """Byte budget for data held in RAM; never blocks (caller falls back to streaming)."""

    def __init__(self, total: int):
        self.total, self.used, self.lock = total, 0, threading.Lock()

    def try_take(self, n: int) -> bool:
        with self.lock:
            if self.used + n > self.total:
                return False
            self.used += n
            return True

    def give(self, n: int) -> None:
        with self.lock:
            self.used -= n


RELEASE_STEP = 256 * MiB    # release big ranges in steps: huge TRIMs can stall cheap SSDs
RELEASE_PAUSE = 0.02        # seconds between steps, lets other disk I/O through


def _open_archive(src: source.ArchiveSource, name_encoding):
    # Sequential read-ahead (FILE_FLAG_SEQUENTIAL_SCAN on Windows,
    # POSIX_FADV_SEQUENTIAL on Linux) + 256 KiB buffering.
    f = src.open()
    try:
        return zipfile.ZipFile(f, "r", metadata_encoding=name_encoding), f
    except BaseException:
        f.close()
        raise


def _copy_to_local_part(part: str, local_part: str, durable: bool) -> None:
    shutil.copyfile(part, local_part)
    if durable:
        with open(local_part, "rb") as dst:
            os.fsync(dst.fileno())
    shutil.copystat(part, local_part)
    os.remove(part)


def run(plan: Plan, on_progress: Callable[[Progress], None] | None = None,
        cancel: threading.Event | None = None, *, durable: bool = True,
        delete_archive: bool = False, settings: settingsmod.Settings | None = None,
        _fault: Callable[[str, int], None] | None = None) -> Result:
    if not plan.ok:
        raise ValueError("plan has problems; refusing to run")
    s = settingsmod.validate(settings or plan.settings
                             or settingsmod.for_mode(settingsmod.DEFAULT_MODE))[0]
    fault = _fault or (lambda phase, i: None)
    archive, target, entries = plan.archive, plan.target, plan.entries
    n = len(entries)
    unit = plan.punch_unit
    threads = settingsmod.effective_threads(s)
    sync_bytes = COMMIT_BYTES if COMMIT_BYTES is not None else s.sync_interval_mb * MiB
    chunk = CHUNK
    flush_bytes = s.flush_interval_mb * MiB  # overlapped flushes beat one big flush at the end
    max_temp = int(s.max_temp_gb * 1024 ** 3)
    budget = _Budget(settingsmod.ram_budget(s))
    small_limit = min(64 * MiB, budget.total // (2 * threads))
    stream_depth = max(2, min(16, budget.total // (threads * chunk * 4)))
    throttle = Throttle(s.max_cpu_percent, s.max_write_mb_s)
    sampler = sysinfo.Sampler()
    temp_dir = os.path.abspath(s.temp_dir) if s.temp_dir else ""
    temp_same_vol = (not temp_dir) or winfs.same_volume(temp_dir, target)
    fp12 = plan.fingerprint[:12]
    abort = threading.Event()        # tells workers to stop now
    stop_submit = threading.Event()  # a worker failed: do not start more entries

    state = {"fingerprint": plan.fingerprint, "target": target,
             "name_encoding": plan.name_encoding, "overwrite": plan.overwrite,
             "entries": n, "done": plan.done, "archive": archive, "mode": s.mode,
             "app_version": __version__, "total_bytes": plan.total_bytes}
    if plan.split:
        state["part_sizes"] = plan.part_sizes  # needed to resume after parts were deleted

    if not plan.resuming:
        journal.save(archive, state, durable)  # before anything is touched
    jobs.register(archive, target, s)
    os.makedirs(winfs.long_path(target), exist_ok=True)
    if temp_dir:  # remove leftovers of an earlier crash of this job
        for fn in os.listdir(temp_dir):
            if fn.startswith(f"iu-{fp12}-") and fn.endswith(".part"):
                try:
                    os.remove(os.path.join(temp_dir, fn))
                except OSError:
                    pass

    verified_dirs: set[str] = set()
    dir_lock = threading.Lock()
    live: dict[int, int] = {}        # entry index -> bytes written so far

    def check_abort():
        if abort.is_set() or (cancel is not None and cancel.is_set()):
            raise _Abort()

    def ensure_dir(parts) -> None:
        cur = target
        for part in parts:
            cur = os.path.join(cur, part)
            key = os.path.normcase(cur)
            if key in verified_dirs:
                continue
            with dir_lock:
                lp = winfs.long_path(cur)
                try:
                    st = os.lstat(lp)
                except FileNotFoundError:
                    try:
                        os.mkdir(lp)
                    except FileExistsError:
                        pass
                    st = os.lstat(lp)
                if (stat.S_ISLNK(st.st_mode)
                        or (getattr(st, "st_file_attributes", 0) & winfs.FILE_ATTRIBUTE_REPARSE_POINT)):
                    raise RunStopped("link_in_target", path=cur)
                if not stat.S_ISDIR(st.st_mode):
                    raise RunStopped("conflict_type", name=cur)
                verified_dirs.add(key)

    def write_all(dst, data, idx) -> None:
        view = memoryview(data)
        for off in range(0, len(view), chunk):
            check_abort()
            piece = view[off:off + chunk]
            dst.write(piece)
            live[idx] = off + len(piece)
            throttle.wrote(len(piece))

    damaged: list[str] = []
    damaged_lock = threading.Lock()
    damaged_report = archive + ".damaged.txt"

    def open_entry(e, z, nocrc: bool):
        src_entry = z.open(e.info)
        if nocrc:
            # Keep a damaged entry exactly as stored: zipfile skips the CRC check
            # when the expected CRC is None (CPython ZipExtFile._update_crc).
            src_entry._expected_crc = None
        return src_entry

    def note_damaged(e) -> None:
        with damaged_lock:
            damaged.append(e.info.filename)
            try:
                with open(winfs.long_path(damaged_report), "a", encoding="utf-8") as f:
                    f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\tCRC mismatch\t{e.info.filename}\n")
                    f.flush()
                    os.fsync(f.fileno())
            except OSError:
                pass

    def stream(e, z, dst, nocrc=False) -> int:
        """Decompress in a helper thread, write here. Returns bytes written."""
        q: queue.Queue = queue.Queue(maxsize=stream_depth)
        done_marker = object()
        stop_local = threading.Event()

        def producer():
            sysinfo.apply_thread_priority(s.priority, s.background_mode)
            try:
                with open_entry(e, z, nocrc) as src_entry:
                    while True:
                        if (stop_local.is_set() or abort.is_set()
                                or (cancel is not None and cancel.is_set())):
                            q.put(_Abort())
                            return
                        block = src_entry.read(chunk)
                        if not block:
                            break
                        q.put(block)
                q.put(done_marker)
            except BaseException as ex:  # includes CRC errors
                q.put(ex)

        t = threading.Thread(target=producer, daemon=True)
        t.start()
        written = since_flush = 0
        first = True
        flusher: threading.Thread | None = None

        def bg_flush(fd):
            try:
                winfs.fdatasync(fd)
            except OSError:
                pass  # the final fsync in extract() reports real errors

        try:
            while True:
                item = q.get()
                if item is done_marker:
                    break
                if isinstance(item, BaseException):
                    raise item
                dst.write(item)
                written += len(item)
                since_flush += len(item)
                live[e.index] = written
                if first:
                    fault("mid_write", e.index)
                    first = False
                throttle.wrote(len(item))
                if flush_bytes and since_flush >= flush_bytes and durable:
                    # Small steady flushes instead of one huge one at the end. Each flush runs
                    # in the background while the next block is written; if the disk has not
                    # finished the previous one yet we wait for it. So writing never gets
                    # more than one block ahead of the disk: steady progress instead of
                    # bursts into the page cache followed by long stalls.
                    if flusher is not None:
                        flusher.join()
                    dst.flush()
                    flusher = threading.Thread(target=bg_flush, args=(dst.fileno(),), daemon=True)
                    flusher.start()
                    since_flush = 0
                check_abort()
        finally:
            if flusher is not None:
                flusher.join()  # never close the file while a flush is running
            stop_local.set()
            while t.is_alive():  # drain so a producer blocked on a full queue can exit
                try:
                    q.get(timeout=0.05)
                except queue.Empty:
                    pass
            t.join()
        return written

    def verify(path: str, crc: int, drop: bool) -> None:
        c = 0
        with open(path, "rb") as f:
            while blk := f.read(4 * MiB):
                c = zlib.crc32(blk, c)
            if drop:
                winfs.drop_cache(f.fileno())
        if c != crc:
            raise zipfile.BadZipFile("verification of the written file failed")

    def extract(e, z) -> None:
        try:
            extract_once(e, z, False)
        except zipfile.BadZipFile as ex:
            if not (s.keep_damaged and "CRC" in str(ex)):
                raise
            # The entry is damaged inside the ZIP. Its bytes are written out unchanged
            # (nothing more is lost than what is already broken) and listed in a report.
            extract_once(e, z, True)
            note_damaged(e)

    def extract_once(e, z, nocrc: bool) -> None:
        out = e.out_path(target)
        if out is None:
            return
        if e.is_dir:
            ensure_dir(e.parts)
            return
        ensure_dir(e.parts[:-1])
        final = winfs.long_path(out)
        local_part = f"{final}.~iu{e.index}.part"
        part = (winfs.long_path(os.path.join(temp_dir, f"iu-{fp12}-{e.index}.part"))
                if temp_dir else local_part)
        held = 0
        will_verify = s.verify_written and not nocrc
        large = e.size >= PIPELINE_MIN
        try:
            data = None
            use_ram = (s.auto_ram_disk and 0 < e.size <= small_limit
                       and sysinfo.memory_load() < s.ram_threshold_percent
                       and budget.try_take(e.size))
            if use_ram:
                held = e.size
                with open_entry(e, z, nocrc) as src_entry:
                    data = src_entry.read()  # CRC checked by zipfile
                check_abort()
            with open(part, "wb") as dst:
                if data is not None:
                    fault("mid_write", e.index)
                    write_all(dst, data, e.index)
                    written = len(data)
                elif large:
                    written = stream(e, z, dst, nocrc)
                else:
                    written = 0
                    first = True
                    with open_entry(e, z, nocrc) as src_entry:
                        while block := src_entry.read(chunk):
                            dst.write(block)
                            written += len(block)
                            live[e.index] = written
                            if first:
                                fault("mid_write", e.index)
                                first = False
                            throttle.wrote(len(block))
                            check_abort()
                if written != e.info.file_size:
                    raise zipfile.BadZipFile(f"size mismatch {written} != {e.info.file_size}")
                dst.flush()
                if durable:
                    os.fsync(dst.fileno())
                if large and not will_verify:
                    winfs.drop_cache(dst.fileno())
            if held:
                budget.give(held)
                held = 0
                data = None
            if will_verify:
                verify(part, e.info.CRC, large)
            if os.name != "nt" and e.info.create_system == 3:
                unix_exec = (e.info.external_attr >> 16) & 0o111
                if unix_exec:
                    try:
                        cur_mode = stat.S_IMODE(os.lstat(part).st_mode)
                        os.chmod(part, cur_mode | (unix_exec & ~_UMASK))
                    except OSError:
                        pass
            try:
                t = time.mktime(e.info.date_time + (0, 0, -1))
                os.utime(part, (t, t))
            except (OverflowError, ValueError, OSError):
                pass
            if not temp_same_vol:  # temp dir on another drive/subvolume: copy, then rename
                _copy_to_local_part(part, local_part, durable)
                part = local_part
            if os.name == "nt" and os.path.lexists(final):
                os.chmod(final, stat.S_IWRITE)  # clear Windows read-only attribute so replace works
            try:
                os.replace(part, final)
            except OSError as ex:
                if ex.errno != errno.EXDEV or part == local_part:
                    raise
                _copy_to_local_part(part, local_part, durable)
                part = local_part
                os.replace(part, final)
        except SimulatedCrash:
            raise
        except BaseException:
            for pth in {part, local_part}:
                try:
                    os.remove(pth)
                except OSError:
                    pass
            raise
        finally:
            if held:
                budget.give(held)
            live.pop(e.index, None)

    src = source.ArchiveSource(archive, state)
    z, zf = _open_archive(src, plan.name_encoding)
    worker_tls = threading.local()
    extra_archives: list[tuple[zipfile.ZipFile, object]] = []
    extra_lock = threading.Lock()

    def get_worker_zip() -> zipfile.ZipFile:
        if threads <= 1:
            return z
        wz = getattr(worker_tls, "z", None)
        if wz is None:
            wz, wzf = _open_archive(src, plan.name_encoding)
            with extra_lock:
                extra_archives.append((wz, wzf))
            worker_tls.z = wz
        return wz

    frees = not plan.split or s.delete_parts
    sp = src.releaser(plan.punch) if frees else None
    released = 0
    committed = plan.done
    start_time = time.monotonic()
    bytes_done = sum(e.size for e in entries[:plan.done])
    base_bytes = bytes_done
    speed_ema = 0.0
    last_sample = (start_time, bytes_done)
    last_report = 0.0
    stats: dict = {}
    sysinfo.apply_thread_priority(s.priority, s.background_mode)

    def safe_end(k: int) -> int:
        return entries[k].start if k < n else plan.cd_start

    def release(k: int) -> None:
        nonlocal released
        if sp is None:
            return
        end = plan.cd_start if k >= n else align_down(safe_end(k), unit)
        first = True
        while end > released:
            if not first:
                time.sleep(RELEASE_PAUSE)
            first = False
            step = min(end, released + RELEASE_STEP)
            sp.release(released, step)
            released = step

    def commit(k: int) -> None:
        nonlocal committed
        if k != committed:
            journal.save(archive, dict(state, done=k, bytes_done=bytes_done,
                                       last_entry=entries[k - 1].info.filename if k else ""),
                         durable)
            committed = k
            fault("after_commit", k - 1)   # index of the last committed entry
        release(k)
        fault("after_release", k - 1)

    def safe_commit(k: int) -> None:
        try:
            commit(k)
        except SimulatedCrash:
            raise
        except Exception:
            pass  # nothing released -> still consistent

    def report(i: int, name: str, active: int, force: bool = False, phase="extract"):
        nonlocal last_report, speed_ema, last_sample, stats
        now = time.monotonic()
        if not force and now - last_report < 0.25:
            return
        last_report = now
        cur = bytes_done + sum(live.values())
        t0, b0 = last_sample
        if now - t0 >= 0.5:
            inst = (cur - b0) / (now - t0)
            speed_ema = inst if speed_ema == 0 else 0.7 * speed_ema + 0.3 * inst
            last_sample = (now, cur)
            stats = sampler.sample()
        if on_progress is None:
            return
        try:
            alloc = src.allocated()
            free = winfs.free_bytes(target)
        except OSError:
            alloc = free = -1
        el = now - start_time
        avg = (cur - base_bytes) / el if el > 1 else 0.0
        # ETA from the average speed: much steadier than the momentary speed
        rate = avg if avg > 0 else speed_ema
        eta = (plan.total_bytes - cur) / rate if rate > 0 else None
        on_progress(Progress(i, n, cur, plan.total_bytes, name, alloc, free,
                             elapsed=el, speed=speed_ema, avg_speed=avg, eta=eta,
                             threads=threads, active=active, stats=stats,
                             low_space=0 <= free < s.low_space_warn_gb * 1024 ** 3, phase=phase))

    def map_error(ex: BaseException, e) -> RunStopped:
        if isinstance(ex, RunStopped):
            return ex
        if isinstance(ex, (_Abort, KeyboardInterrupt)):
            return RunStopped("cancelled")
        if isinstance(ex, (zipfile.BadZipFile, zlib.error, EOFError)):
            return RunStopped("crc", name=e.info.filename, error=str(ex))
        if isinstance(ex, MemoryError):
            return RunStopped("out_of_memory", name=e.info.filename)
        if isinstance(ex, PermissionError):
            return RunStopped("permission", name=e.info.filename, error=str(ex))
        if winfs.is_disk_full(ex):
            return RunStopped("out_of_space", name=e.info.filename, need=e.size,
                              free=winfs.free_bytes(target))
        return RunStopped("io_error", name=e.info.filename, error=str(ex))

    def task(e):
        try:
            extract(e, get_worker_zip())
        except SimulatedCrash:
            abort.set()
            raise
        except BaseException:
            stop_submit.set()
            raise

    pool = ThreadPoolExecutor(max_workers=threads, thread_name_prefix="unpack",
                              initializer=sysinfo.apply_thread_priority,
                              initargs=(s.priority, s.background_mode))
    futures: dict = {}
    inflight = 0
    prefix = next_submit = plan.done
    try:
        if plan.done:
            release(plan.done)  # a crash may have happened between journal and release
        pending = 0
        report(plan.done, "", 0, force=True)
        while prefix < n:
            # ---- start more entries (bounded by threads, temp space, free space, RAM)
            while (next_submit < n and len(futures) < threads and not stop_submit.is_set()
                   and not (cancel is not None and cancel.is_set())):
                e = entries[next_submit]
                if futures and inflight + e.size > max_temp:
                    break
                if futures and s.auto_optimize and sysinfo.memory_load() >= s.ram_threshold_percent:
                    break  # RAM is tight: run fewer entries in parallel
                if e.size:
                    need = round_up(e.size, plan.cluster) + inflight + SPACE_GUARD
                    if winfs.free_bytes(target) < need:
                        if futures:
                            break  # wait: finishing entries lets us commit and free space
                        commit(prefix)
                        pending = 0
                        free = winfs.free_bytes(target)
                        if free < need:
                            raise RunStopped("out_of_space", name=e.info.filename,
                                             need=need, free=free)
                futures[next_submit] = pool.submit(task, e)
                inflight += e.size
                next_submit += 1
            # commit only now, after the next entry was started: the worker keeps
            # extracting while the journal is written and the archive space is released
            if pending >= sync_bytes:
                commit(prefix)
                pending = 0
            if prefix not in futures:  # cancelled before the next entry was started
                raise RunStopped("cancelled")

            # ---- wait for the oldest entry, reporting progress meanwhile
            e = entries[prefix]
            fut = futures[prefix]
            while not wait_futures([fut], timeout=0.25).done:
                report(prefix, e.info.filename, len(futures))
                if cancel is not None and cancel.is_set():
                    abort.set()
            ex = fut.exception()
            if ex is not None:
                if isinstance(ex, SimulatedCrash):
                    raise ex
                raise map_error(ex, e)
            del futures[prefix]
            inflight -= e.size
            fault("after_extract", prefix)
            bytes_done += e.size
            pending += e.end - e.start
            prefix += 1
            report(prefix, e.info.filename, len(futures))
        commit(n)
        report(n, "", 0, force=True)
    except SimulatedCrash:
        raise
    except BaseException as ex:
        stop_submit.set()
        abort.set()
        for f in futures.values():   # let workers finish aborting before we commit
            try:
                f.exception()
            except BaseException:
                pass
        safe_commit(prefix)  # only the contiguous, finished prefix is committed
        if isinstance(ex, RunStopped):
            raise
        raise map_error(ex, entries[min(prefix, n - 1)]) from ex
    finally:
        abort.set()  # a crash (SimulatedCrash) commits nothing, like a dead process
        pool.shutdown(wait=True, cancel_futures=True)
        if sp is not None:
            sp.close()
        for wz, wzf in extra_archives:
            wz.close()
            wzf.close()
        z.close()
        zf.close()
        sysinfo.end_thread_background()

    journal.remove(archive)
    jobs.unregister(archive)
    deleted = False
    if delete_archive:
        src.remove_all()
        deleted = True
    avg_cpu = (sum(sampler.cpu_samples) / len(sampler.cpu_samples)) if sampler.cpu_samples else 0.0
    return Result(n, bytes_done, deleted, elapsed=time.monotonic() - start_time,
                  avg_cpu=avg_cpu, peak_ram=sampler.peak_ram, written=bytes_done - base_bytes,
                  damaged=damaged,
                  damaged_report=damaged_report if os.path.exists(damaged_report) else "")
