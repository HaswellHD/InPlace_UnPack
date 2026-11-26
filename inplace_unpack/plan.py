"""Pre-flight check: everything that can go wrong is detected here, before a
single byte of the archive is destroyed."""
from __future__ import annotations

import hashlib
import os
import struct
import zipfile
from dataclasses import dataclass, field

from . import journal, names, source, winfs
from . import settings as settingsmod

SUPPORTED_METHODS = {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED, zipfile.ZIP_BZIP2,
                     zipfile.ZIP_LZMA}
if hasattr(zipfile, "ZIP_ZSTANDARD"):
    SUPPORTED_METHODS.add(zipfile.ZIP_ZSTANDARD)
METHOD_NAMES = {0: "Stored", 8: "Deflate", 9: "Deflate64", 12: "BZIP2", 14: "LZMA",
                93: "Zstandard", 98: "PPMd", 99: "AES", 6: "Implode", 1: "Shrink"}

MiB = 1024 * 1024
COMMIT_BYTES = 64 * MiB      # journal + release at least this often
COMMIT_SECONDS = 2.0
LOCAL_HEADER = b"PK\x03\x04"

Msg = tuple  # (key, {params})


def align_down(x: int, unit: int) -> int:
    return x - (x % unit)


def round_up(x: int, unit: int) -> int:
    return -(-x // unit) * unit


@dataclass
class Entry:
    index: int
    info: zipfile.ZipInfo
    start: int              # offset of the local header
    end: int                # start of the next entry (or of the central directory)
    parts: list | None      # safe output path below target; None = nothing to create
    is_dir: bool
    renamed: bool

    @property
    def size(self) -> int:
        return 0 if self.is_dir else self.info.file_size

    def out_path(self, target: str) -> str | None:
        return os.path.join(target, *self.parts) if self.parts else None


@dataclass
class Plan:
    archive: str
    target: str
    entries: list = field(default_factory=list)
    cd_start: int = 0
    fingerprint: str = ""
    name_encoding: str | None = None
    overwrite: bool = False
    done: int = 0
    resuming: bool = False
    archive_size: int = 0
    archive_allocated: int = 0
    total_bytes: int = 0
    remaining_bytes: int = 0
    free: int = 0
    same_volume: bool = True
    peak_need: int = 0
    reserve: int = 0
    cluster: int = 4096
    punch_unit: int = 65536
    problems: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    conflicts: list = field(default_factory=list)
    renamed: list = field(default_factory=list)
    settings: object = None
    journal_info: dict | None = None
    split: bool = False             # archive is a split ZIP (name.zip.001, .002, ...)
    part_sizes: list | None = None  # sizes of all parts (also of parts already deleted)
    punch: bool = True              # holes can be punched (NTFS/ReFS or btrfs/ext4/xfs/...)

    @property
    def ok(self) -> bool:
        return not self.problems

    @property
    def fits(self) -> bool:
        return self.free >= self.peak_need + self.reserve

    @property
    def remaining(self) -> int:
        return len(self.entries) - self.done


class _Collector:
    """Groups repeated problems ("37 encrypted entries, e.g. a.txt")."""

    def __init__(self):
        self.items: dict = {}

    def add(self, key, name="", **kw):
        if key in self.items:
            self.items[key][1]["count"] += 1
        else:
            self.items[key] = (key, dict(kw, name=name, count=1))

    def as_list(self):
        return list(self.items.values())


def _fingerprint(f, cd_start: int, size: int) -> str:
    h = hashlib.sha256(str(size).encode())
    f.seek(cd_start)
    while chunk := f.read(4 * MiB):
        h.update(chunk)
    return h.hexdigest()


def releasable(sizes: list[int] | None, offset: int, unit: int, punch: bool) -> int:
    """Bytes that are freed when the archive range [0, offset) is released."""
    if sizes is None:  # single file: sparse holes in whole units
        return align_down(offset, unit)
    freed, pos = 0, 0
    for sz in sizes:
        if pos + sz <= offset:
            freed += sz            # whole part deleted
        elif pos < offset and punch:
            freed += align_down(offset - pos, unit)
            break
        else:
            break
        pos += sz
    return freed


def _same_target_dir(a: str, b: str) -> bool:
    if os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b)):
        return True
    return os.path.realpath(a) == os.path.realpath(b)


def analyze(archive: str, target: str, *, overwrite: bool = False,
            name_encoding: str | None = None, ignore_space: bool = False,
            settings: "settingsmod.Settings | None" = None) -> Plan:
    archive = source.first_part(os.path.abspath(archive))
    target = os.path.abspath(target)
    p = Plan(archive=archive, target=target, overwrite=overwrite, name_encoding=name_encoding)
    p.settings = settingsmod.validate(settings or settingsmod.for_mode(settingsmod.DEFAULT_MODE))[0]
    p.split = source.is_split(archive)
    probs = _Collector()

    def finish():
        p.problems = probs.as_list() + p.problems
        return p

    # --- journal (resume) ------------------------------------------------------
    jpath = journal.journal_path(archive)
    try:
        j = journal.load(archive)
    except journal.JournalError as e:
        probs.add("journal_corrupt", jpath, error=str(e))
        return finish()

    # --- the archive file(s) ---------------------------------------------------
    try:
        src = source.ArchiveSource(archive, j)
    except FileNotFoundError as e:
        probs.add("archive_missing", str(e))
        return finish()
    if not src.existing:
        probs.add("archive_missing", archive)
        return finish()
    probe = src.probe_path
    try:
        for part in src.existing:
            if winfs.is_reparse_point(part):
                probs.add("archive_link", part)
            if winfs.is_cloud_placeholder(part):
                probs.add("archive_cloud", part)
            if winfs.file_attributes(part) & winfs.FILE_ATTRIBUTE_READONLY:
                probs.add("archive_readonly", part)
    except OSError as e:
        probs.add("archive_unreadable", archive, error=str(e))
        return finish()
    p.punch = winfs.supports_sparse(probe)
    if not p.punch and not p.split:  # split archives work without sparse files
        try:
            fs = winfs.volume_info(probe)[0]
        except OSError:
            fs = "?"
        probs.add("no_sparse", archive, fs=fs)
    if p.split:
        p.part_sizes = list(src.sizes)
    if os.path.exists(target) and not os.path.isdir(target):
        probs.add("target_not_dir", target)
        return finish()

    if j:
        p.resuming = True
        p.journal_info = j
        if not _same_target_dir(j["target"], target):
            probs.add("journal_other_target", j["target"])
            return finish()
        p.name_encoding = j.get("name_encoding")
        p.overwrite = bool(j.get("overwrite", False))

    # --- read the central directory -------------------------------------------
    f = src.open()
    try:
        z = zipfile.ZipFile(f, "r", metadata_encoding=p.name_encoding)
    except (zipfile.BadZipFile, OSError, NotImplementedError, ValueError, LookupError) as e:
        f.close()
        probs.add("bad_zip", archive, error=str(e))
        return finish()

    with z, f:
        p.archive_size = src.size
        p.archive_allocated = src.allocated()
        p.cd_start = z.start_dir
        p.fingerprint = _fingerprint(f, p.cd_start, p.archive_size)
        if j and j["fingerprint"] != p.fingerprint:
            probs.add("journal_mismatch", jpath)
            return finish()

        infos = sorted(z.infolist(), key=lambda i: i.header_offset)
        n = len(infos)
        p.done = j["done"] if j else 0
        if not 0 <= p.done <= n:
            probs.add("journal_corrupt", jpath, error="done out of range")
            return finish()

        assigned = names.assign_paths([(i.filename, i.is_dir()) for i in infos])
        for idx, (info, (parts, renamed)) in enumerate(zip(infos, assigned)):
            start = info.header_offset
            end = infos[idx + 1].header_offset if idx + 1 < n else p.cd_start
            e = Entry(idx, info, start, end, parts, info.is_dir(), renamed)
            p.entries.append(e)
            p.total_bytes += e.size
            if renamed and parts:
                p.renamed.append((info.filename, os.sep.join(parts)))
            if idx < p.done:
                continue  # already extracted; its local header is gone
            p.remaining_bytes += e.size

            if info.flag_bits & 0x41:
                probs.add("encrypted", info.filename)
            if info.compress_type not in SUPPORTED_METHODS:
                probs.add("method", info.filename,
                          method=METHOD_NAMES.get(info.compress_type, str(info.compress_type)))
            if start < 0 or end > p.cd_start:
                probs.add("overlap", info.filename)
                continue
            f.seek(start)
            hdr = f.read(30)
            if len(hdr) < 30 or hdr[:4] != LOCAL_HEADER:
                probs.add("local_header_missing" if idx == p.done else "bad_entry",
                          info.filename)
                continue
            nlen, xlen = struct.unpack("<HH", hdr[26:30])
            if start + 30 + nlen + xlen + info.compress_size > end:
                probs.add("overlap", info.filename)

    # --- output paths ------------------------------------------------------------
    raw_protected = (archive, jpath, jpath + ".tmp", *src.paths)
    protected = ({os.path.normcase(x).casefold() for x in raw_protected}
                 | {os.path.realpath(x).casefold() for x in raw_protected})
    real_target = os.path.realpath(target)
    for e in p.entries[p.done:]:
        out = e.out_path(target)
        if out is None:
            continue
        if os.path.commonpath([target, out]) != target:  # paranoia; names.py prevents it
            probs.add("path_escape", e.info.filename)
            continue
        out_cf = os.path.normcase(out).casefold()
        real_out_cf = os.path.join(real_target, *e.parts).casefold() if e.parts else out_cf
        if (out_cf in protected or real_out_cf in protected
                or any(x.startswith(out_cf + os.sep) or x.startswith(real_out_cf + os.sep)
                       for x in protected)):
            probs.add("collides_archive", e.info.filename)
            continue
        if p.resuming:
            continue
        lp = winfs.long_path(out)
        if os.path.lexists(lp):
            if e.is_dir:
                if not os.path.isdir(lp):
                    probs.add("conflict_type", e.info.filename)
            elif os.path.isdir(lp):
                probs.add("conflict_type", e.info.filename)
            else:
                p.conflicts.append(out)
    if p.conflicts and not p.overwrite:
        probs.add("conflicts", p.conflicts[0])
        probs.items["conflicts"][1]["count"] = len(p.conflicts)

    # --- space -------------------------------------------------------------------
    p.same_volume = winfs.same_pool(probe, target)
    p.cluster = winfs.cluster_size(target)
    a_cluster = winfs.cluster_size(probe)
    fs = winfs.volume_info(probe)[0].upper() if p.punch else ""
    p.punch_unit = max(65536, a_cluster * 16) if fs == "NTFS" else max(65536, a_cluster)
    p.free = winfs.free_bytes(target)

    ratio = 1.0
    if not p.resuming and p.archive_size and p.archive_allocated < p.archive_size * 0.95:
        ratio = p.archive_allocated / p.archive_size
        p.warnings.append(("archive_compressed", {}))
    s = p.settings
    sync_bytes = s.sync_interval_mb * MiB
    threads = settingsmod.effective_threads(s)
    max_temp = int(s.max_temp_gb * 1024 ** 3)
    rest = p.entries[p.done:]
    if rest:
        # Simulate the run: archive space is only released at commit points
        # (every sync_interval), and up to `threads` entries (max. max_temp
        # bytes) can be in flight at the same time.
        frees = p.same_volume and (not p.split or s.delete_parts)
        base = releasable(p.part_sizes, rest[0].start, p.punch_unit, p.punch)
        sizes = [round_up(e.size, p.cluster) + 1024 for e in rest]  # + inode / MFT record
        written = peak = freed = pending = 0
        for k, e in enumerate(rest):
            written += sizes[k]
            ahead, j_idx = 0, k + 1
            while j_idx < len(rest) and j_idx - k < threads and ahead + sizes[j_idx] <= max_temp:
                ahead += sizes[j_idx]
                j_idx += 1
            peak = max(peak, written + ahead - freed)
            pending += e.end - e.start
            if pending >= sync_bytes and frees:
                nxt = rest[k + 1].start if k + 1 < len(rest) else p.cd_start
                freed = int((releasable(p.part_sizes, nxt, p.punch_unit, p.punch) - base) * ratio)
                pending = 0
        p.peak_need = peak
    p.reserve = 32 * MiB + max(64 * MiB, min(1024 * MiB, p.remaining_bytes // 100))

    if s.temp_dir:
        if not os.path.isdir(s.temp_dir):
            probs.add("temp_missing", s.temp_dir)
        elif not winfs.same_volume(s.temp_dir, target):
            p.warnings.append(("temp_other_volume", {}))
            biggest = max((e.size for e in rest), default=0)
            if winfs.free_bytes(s.temp_dir) < biggest + 64 * MiB:
                probs.add("temp_space", s.temp_dir, need=biggest)

    if not p.same_volume:
        p.warnings.append(("other_volume", {}))
    if p.renamed:
        p.warnings.append(("renamed", {"count": len(p.renamed), "name": p.renamed[0][0],
                                       "new": p.renamed[0][1]}))
    if p.resuming:
        p.warnings.append(("resuming", {"done": p.done, "total": len(p.entries)}))
    if p.conflicts and p.overwrite:
        p.warnings.append(("will_overwrite", {"count": len(p.conflicts)}))
    if not p.fits and not ignore_space:
        p.problems.append(("space", {"need": p.peak_need + p.reserve, "free": p.free,
                                     "missing": p.peak_need + p.reserve - p.free}))
    return finish()
