"""System information and resource monitoring (no third-party packages).

Uses GetSystemTimes / GetProcessTimes / GlobalMemoryStatusEx /
GetProcessMemoryInfo / GetProcessIoCounters.
"""
from __future__ import annotations

import ctypes
import os
import threading
import time
from ctypes import wintypes

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_psapi = ctypes.WinDLL("psapi", use_last_error=True)


class _MEMSTATUS(ctypes.Structure):
    _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


class _PMC(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


class _IOC(ctypes.Structure):
    _fields_ = [(n, ctypes.c_ulonglong) for n in
                ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                 "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


_k32.GetCurrentProcess.restype = wintypes.HANDLE
_k32.GetCurrentThread.restype = wintypes.HANDLE
_FT = wintypes.FILETIME
_PFT = ctypes.POINTER(_FT)
_k32.GetProcessTimes.argtypes = [wintypes.HANDLE, _PFT, _PFT, _PFT, _PFT]
_k32.GetSystemTimes.argtypes = [_PFT, _PFT, _PFT]
_k32.GetProcessIoCounters.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
_k32.SetThreadPriority.argtypes = [wintypes.HANDLE, ctypes.c_int]
_k32.GlobalMemoryStatusEx.argtypes = [ctypes.c_void_p]
_psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]


def _ft(ft) -> float:
    return ((ft.dwHighDateTime << 32) | ft.dwLowDateTime) / 1e7


def _mem() -> _MEMSTATUS:
    m = _MEMSTATUS()
    m.dwLength = ctypes.sizeof(m)
    _k32.GlobalMemoryStatusEx(ctypes.byref(m))
    return m


def total_ram() -> int:
    return _mem().ullTotalPhys or 4 * 1024 ** 3


def available_ram() -> int:
    return _mem().ullAvailPhys


def memory_load() -> int:
    """System memory load in percent (0-100)."""
    return _mem().dwMemoryLoad


def process_cpu_seconds() -> float:
    c, e, k, u = _FT(), _FT(), _FT(), _FT()
    _k32.GetProcessTimes(_k32.GetCurrentProcess(), ctypes.byref(c), ctypes.byref(e),
                         ctypes.byref(k), ctypes.byref(u))
    return _ft(k) + _ft(u)


def system_times() -> tuple[float, float]:
    """(idle, total) CPU seconds summed over all cores."""
    i, k, u = _FT(), _FT(), _FT()
    _k32.GetSystemTimes(ctypes.byref(i), ctypes.byref(k), ctypes.byref(u))
    return _ft(i), _ft(k) + _ft(u)  # kernel time includes idle time


def process_memory() -> int:
    pmc = _PMC()
    pmc.cb = ctypes.sizeof(pmc)
    _psapi.GetProcessMemoryInfo(_k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
    return pmc.WorkingSetSize


def process_io() -> tuple[int, int]:
    """(bytes read, bytes written) by this process since it started."""
    io = _IOC()
    _k32.GetProcessIoCounters(_k32.GetCurrentProcess(), ctypes.byref(io))
    return io.ReadTransferCount, io.WriteTransferCount


# --- thread priority ---------------------------------------------------------
_THREAD_PRIORITY = {"idle": -15, "below_normal": -1, "normal": 0}
THREAD_MODE_BACKGROUND_BEGIN = 0x00010000
THREAD_MODE_BACKGROUND_END = 0x00020000


def apply_thread_priority(priority: str, background: bool) -> None:
    """Applies to the *calling* thread only, so the GUI thread stays responsive.

    Background mode lowers the thread's CPU, disk-I/O and memory priority:
    other programs get the disk first, the extraction uses what is left.
    """
    h = _k32.GetCurrentThread()
    if background:
        _k32.SetThreadPriority(h, THREAD_MODE_BACKGROUND_BEGIN)
    _k32.SetThreadPriority(h, _THREAD_PRIORITY.get(priority, -1))


def end_thread_background() -> None:
    _k32.SetThreadPriority(_k32.GetCurrentThread(), THREAD_MODE_BACKGROUND_END)


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
        m = _mem()
        return {"proc_cpu": proc_cpu, "sys_cpu": max(0.0, min(100.0, sys_cpu)),
                "proc_ram": ram, "sys_ram_load": m.dwMemoryLoad, "sys_ram_avail": m.ullAvailPhys,
                "sys_ram_total": m.ullTotalPhys, "read_bps": (r1 - r0) / dt,
                "write_bps": (w1 - w0) / dt, "read_total": r1, "write_total": w1}
