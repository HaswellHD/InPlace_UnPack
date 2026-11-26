"""Extraction modes and advanced settings.

Every field here is read by the engine (see engine.py); nothing is cosmetic.
All values are clamped by `validate()` so that no configuration can cause
uncontrolled memory use, unbounded disk use or an unusable system.

Data-integrity rule that no setting can switch off: the archive bytes of an
entry are only released after the extracted file has been flushed to disk
(fsync) and the journal that records it has been flushed too.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields

from . import sysinfo

MODES = ("safe", "balanced", "performance")
DEFAULT_MODE = "balanced"
PRIORITIES = ("idle", "below_normal", "normal")


@dataclass
class Settings:
    mode: str = DEFAULT_MODE
    # --- CPU -----------------------------------------------------------------
    auto_threads: bool = True
    max_threads: int = 1            # used when auto_threads is off
    max_cpu_percent: int = 75       # of the whole machine; enforced by a throttle
    background_mode: bool = False   # Windows background mode: low I/O + memory priority
    priority: str = "below_normal"  # CPU priority of the worker threads
    # --- RAM -----------------------------------------------------------------
    max_ram_mb: int = 512           # buffers + small files held in RAM
    ram_threshold_percent: int = 85  # above this system memory load: stop using RAM path
    auto_memory: bool = True        # shrink the RAM budget when the system has little free
    auto_ram_disk: bool = True      # small files in RAM, large files streamed to disk
    # --- storage ---------------------------------------------------------------
    temp_dir: str = ""              # "" = next to the final file (fastest, recommended)
    max_temp_gb: float = 8.0        # max. bytes of unfinished (.part) files at once
    max_write_mb_s: int = 0         # 0 = unlimited
    flush_interval_mb: int = 64     # flush long files to disk every N MB while writing
    low_space_warn_gb: float = 2.0
    # --- journal & recovery ----------------------------------------------------
    sync_interval_mb: int = 1024    # journal commit + archive release every N MB
    verify_written: bool = False    # read every finished file back and check its CRC
    auto_resume: bool = True        # resume unfinished jobs / retry after a recoverable stop
    resume_after_reboot: bool = False  # register a per-user autostart entry while a job runs
    keep_damaged: bool = True       # entry with wrong CRC: keep its bytes, list it, continue
    delete_parts: bool = True       # split ZIP (.zip.001 ...): delete each part once extracted
    explorer_menu: bool = False     # "Inplace-Unpack" entry in the Explorer right-click menu
    # --- other -------------------------------------------------------------------
    auto_optimize: bool = True      # adapt workers to RAM pressure and free space at runtime
    show_monitor: bool = True
    language: str = "en"


# Presets are based on measurements (see docs/Performance.md): on a typical
# SATA SSD more worker threads did NOT make extraction faster, and Windows
# background mode made other programs wait *longer* (priority inversion on
# flushes). Regular flushing every 64 MB was the most effective way to avoid
# "hangs" and to keep the PC responsive.
PRESETS = {
    "safe": dict(auto_threads=False, max_threads=1, max_cpu_percent=50, background_mode=False,
                 priority="below_normal", max_ram_mb=256, sync_interval_mb=64,
                 flush_interval_mb=64, verify_written=True, max_temp_gb=2.0,
                 keep_damaged=False),
    "balanced": dict(auto_threads=True, max_threads=1, max_cpu_percent=75, background_mode=False,
                     priority="below_normal", max_ram_mb=512, sync_interval_mb=1024,
                     flush_interval_mb=64, verify_written=False, max_temp_gb=8.0,
                     keep_damaged=True),
    "performance": dict(auto_threads=True, max_threads=2, max_cpu_percent=100,
                        background_mode=False, priority="normal", max_ram_mb=1024,
                        sync_interval_mb=2048, flush_interval_mb=64, verify_written=False,
                        max_temp_gb=16.0, keep_damaged=True),
}
LANGUAGES = ("en", "de")
CHOICES = {"priority": PRIORITIES, "language": LANGUAGES}

# (min, max) for numeric fields. Upper RAM bound also depends on installed RAM.
LIMITS = {
    "max_threads": (1, 32),
    "max_cpu_percent": (10, 100),
    "max_ram_mb": (64, 8192),
    "ram_threshold_percent": (50, 95),
    "max_temp_gb": (0.25, 1024.0),
    "max_write_mb_s": (0, 100000),
    "flush_interval_mb": (0, 8192),
    "low_space_warn_gb": (0.0, 1024.0),
    "sync_interval_mb": (16, 8192),
}


def for_mode(mode: str) -> Settings:
    s = Settings(mode=mode if mode in MODES else DEFAULT_MODE)
    for k, v in PRESETS[s.mode].items():
        setattr(s, k, v)
    return s


def validate(s: Settings) -> tuple[Settings, list[str]]:
    """Clamp every value into a safe range. Returns (settings, list of fixed fields)."""
    fixed = []
    if s.mode not in MODES:
        s.mode, _ = DEFAULT_MODE, fixed.append("mode")
    if s.priority not in PRIORITIES:
        s.priority, _ = "below_normal", fixed.append("priority")
    if s.language not in LANGUAGES:
        s.language, _ = "en", fixed.append("language")
    ram_cap = max(64, min(LIMITS["max_ram_mb"][1], sysinfo.total_ram() // (4 * 1024 * 1024)))
    cpu_cap = max(1, min(LIMITS["max_threads"][1], os.cpu_count() or 1))
    for f in fields(s):
        v = getattr(s, f.name)
        if f.type in ("bool", bool):
            if not isinstance(v, bool):
                setattr(s, f.name, bool(v))
                fixed.append(f.name)
            continue
        if f.name not in LIMITS:
            continue
        lo, hi = LIMITS[f.name]
        if f.name == "max_ram_mb":
            hi = ram_cap        # never more than 1/4 of installed RAM
        if f.name == "max_threads":
            hi = cpu_cap
        try:
            num = type(lo)(v)
        except (TypeError, ValueError):
            num = getattr(Settings(), f.name)
        clamped = min(max(num, lo), hi)
        if clamped != v:
            fixed.append(f.name)
        setattr(s, f.name, clamped)
    if not isinstance(s.temp_dir, str):
        s.temp_dir, _ = "", fixed.append("temp_dir")
    return s, fixed


def effective_threads(s: Settings) -> int:
    n = os.cpu_count() or 1
    if not s.auto_threads:
        return s.max_threads
    # The disk, not the CPU, is the limit (decompression runs at >1 GB/s per
    # core). Measured: 2+ workers were not faster on a SATA SSD, even for
    # thousands of small files, but disturbed other programs more. Large
    # entries still use 2 threads each (decompress + write pipeline).
    if s.mode in ("safe", "balanced"):
        return 1
    return min(2, n)


def ram_budget(s: Settings) -> int:
    """Bytes the engine may use for buffers and in-RAM files right now."""
    budget = s.max_ram_mb * 1024 * 1024
    if s.auto_memory:
        budget = min(budget, sysinfo.available_ram() // 4)
    return max(16 * 1024 * 1024, budget)


# --- persistence ---------------------------------------------------------------
def config_dir() -> str:
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "Inplace-Unpack")


def config_path() -> str:
    return os.path.join(config_dir(), "settings.json")


def load(path: str | None = None) -> Settings:
    path = path or config_path()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return for_mode(DEFAULT_MODE)
    s = for_mode(data.get("mode", DEFAULT_MODE))
    known = {f.name for f in fields(Settings)}
    for k, v in data.items():
        if k in known:
            setattr(s, k, v)
    # 0.3.0 shipped Performance with a 256 MB flush interval, which caused stalls;
    # move users who kept that old default to the new one
    if s.mode == "performance" and s.flush_interval_mb == 256:
        s.flush_interval_mb = PRESETS["performance"]["flush_interval_mb"]
    return validate(s)[0]


def save(s: Settings, path: str | None = None) -> None:
    path = path or config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(asdict(s), f, indent=2)
    os.replace(tmp, path)


def as_dict(s: Settings) -> dict:
    return asdict(s)
