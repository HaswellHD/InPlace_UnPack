"""Linux implementation of system information (same API as _sysinfo_nt), via /proc."""
from __future__ import annotations

import ctypes
import os
import threading
import time

_CLK_TCK = os.sysconf("SC_CLK_TCK") or 100
_PAGE_SIZE = os.sysconf("SC_PAGE_SIZE") or 4096


def _meminfo() -> dict[str, int]:
    out: dict[str, int] = {}
    try:
        with open("/proc/meminfo", encoding="ascii", errors="replace") as f:
            for line in f:
                k, _, v = line.partition(":")
                if k in ("MemTotal", "MemAvailable"):
                    out[k] = int(v.split()[0]) * 1024
                    if len(out) == 2:
                        break
    except (OSError, ValueError, IndexError):
        pass
    return out


def total_ram() -> int:
    return _meminfo().get("MemTotal") or 4 * 1024 ** 3


def available_ram() -> int:
    return _meminfo().get("MemAvailable", 0)


def memory_load() -> int:
    m = _meminfo()
    tot = m.get("MemTotal", 0)
    return int(100 * (1 - m.get("MemAvailable", 0) / tot)) if tot else 0


def process_cpu_seconds() -> float:
    t = os.times()
    return t.user + t.system


def system_times() -> tuple[float, float]:
    """(idle, total) CPU seconds summed over all cores."""
    try:
        with open("/proc/stat", encoding="ascii", errors="replace") as f:
            vals = [int(x) for x in f.readline().split()[1:]]
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
        return idle / _CLK_TCK, sum(vals[:8]) / _CLK_TCK
    except (OSError, ValueError, IndexError):
        return 0.0, 0.0


def process_memory() -> int:
    try:
        with open("/proc/self/statm", encoding="ascii", errors="replace") as f:
            return int(f.read().split()[1]) * _PAGE_SIZE
    except (OSError, ValueError, IndexError):
        return 0


def process_io() -> tuple[int, int]:
    """(bytes read, bytes written) by this process since it started."""
    r = w = 0
    try:
        with open("/proc/self/io", encoding="ascii", errors="replace") as f:
            for line in f:
                k, _, v = line.partition(":")
                if k == "rchar":
                    r = int(v)
                elif k == "wchar":
                    w = int(v)
    except (OSError, ValueError):
        pass
    return r, w


# --- thread priority ---------------------------------------------------------
_NICE = {"idle": 19, "below_normal": 5, "normal": 0}
_NR_IOPRIO_SET = {"x86_64": 251, "aarch64": 30, "riscv64": 30}.get(os.uname().machine)
_IOPRIO_WHO_PROCESS = 1
_IOPRIO_CLASS_BE, _IOPRIO_CLASS_IDLE = 2, 3
try:
    _libc = ctypes.CDLL(None, use_errno=True)
except OSError:
    _libc = None


def _ioprio(cls: int, data: int = 4) -> None:
    if _libc is not None and _NR_IOPRIO_SET is not None:
        try:
            _libc.syscall(
                ctypes.c_long(_NR_IOPRIO_SET),
                ctypes.c_long(_IOPRIO_WHO_PROCESS),
                ctypes.c_long(threading.get_native_id()),
                ctypes.c_long((cls << 13) | data),
            )
        except Exception:
            pass


def apply_thread_priority(priority: str, background: bool) -> None:
    """Applies to disposable worker/helper threads only.

    On Linux, unprivileged threads cannot raise their nice value back once lowered,
    and child threads inherit the creator's nice value. Leaving the main/GUI/CLI
    orchestrator thread at its original priority keeps the UI snappy and lets
    subsequent runs (e.g. bench 'performance' after 'safe') run at full priority.
    """
    if threading.current_thread() is threading.main_thread():
        return
    tid = threading.get_native_id()
    try:
        cur = os.getpriority(os.PRIO_PROCESS, tid)
        want = _NICE.get(priority, 5)
        if want > cur:
            os.setpriority(os.PRIO_PROCESS, tid, want)
    except OSError:
        pass
    if priority == "idle" and hasattr(os, "SCHED_IDLE"):
        try:
            os.sched_setscheduler(tid, os.SCHED_IDLE, os.sched_param(0))
        except OSError:
            pass
    if background:
        _ioprio(_IOPRIO_CLASS_IDLE, 0)


def end_thread_background() -> None:
    if threading.current_thread() is not threading.main_thread():
        _ioprio(_IOPRIO_CLASS_BE)


class Sampler:
    """Computes rates between two calls of sample()."""

    def __init__(self):
        self.ncpu = os.cpu_count() or 1
        self._lock = threading.Lock()
        self._last = self._raw()
        self.peak_ram = 0
        self.cpu_samples: list[float] = []

    def _raw(self):
        return (time.monotonic(), process_cpu_seconds(), *system_times(), *process_io())

    def sample(self) -> dict:
        with self._lock:
            now = self._raw()
            t0, pc0, si0, st0, r0, w0 = self._last
            t1, pc1, si1, st1, r1, w1 = now
            self._last = now
        dt = max(t1 - t0, 1e-3)
        proc_cpu = min(100.0, 100.0 * (pc1 - pc0) / dt / self.ncpu)
        dtot = st1 - st0
        sys_cpu = 100.0 * (1 - (si1 - si0) / dtot) if dtot > 0 else 0.0
        ram = process_memory()
        self.peak_ram = max(self.peak_ram, ram)
        self.cpu_samples.append(proc_cpu)
        m = _meminfo()
        tot = m.get("MemTotal", 0)
        avail = m.get("MemAvailable", 0)
        return {
            "proc_cpu": proc_cpu,
            "sys_cpu": max(0.0, min(100.0, sys_cpu)),
            "proc_ram": ram,
            "sys_ram_load": int(100 * (1 - avail / tot)) if tot else 0,
            "sys_ram_avail": avail,
            "sys_ram_total": tot,
            "read_bps": max(0.0, (r1 - r0) / dt),
            "write_bps": max(0.0, (w1 - w0) / dt),
            "read_total": r1,
            "write_total": w1,
        }
