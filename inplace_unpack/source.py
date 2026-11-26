"""The archive as a byte source: one .zip file, or a ZIP split into numbered parts.

Split archives (`name.zip.001`, `name.zip.002`, ...) are plain byte-level splits
(7-Zip "split to volumes", HJSplit, `split`): joined together they are an ordinary
ZIP. They are read through a virtual file, and "releasing" the extracted front of
the archive means deleting every part that lies completely before the release point
(and, on sparse-capable filesystems, punching a hole into the part that contains it).

The same crash-safety rule applies as for a single file: a part is only deleted
after the entries it contains are on disk and recorded in the journal.
"""
from __future__ import annotations

import io
import os
import re
import threading

from . import winfs

_PART_RE = re.compile(r"^(?P<base>.+\.zip)\.(?P<num>\d{3,})$", re.IGNORECASE)
_READ_BUF = 256 * 1024


def split_base(path: str) -> tuple[str, int] | None:
    """('...\\name.zip', number width) if *path* is a part of a split ZIP."""
    m = _PART_RE.match(path)
    return (m.group("base"), len(m.group("num"))) if m else None


def is_split(path: str) -> bool:
    return split_base(path) is not None


def first_part(path: str) -> str:
    """Normalise any part name (…zip.007) to the first part (…zip.001)."""
    sb = split_base(path)
    if not sb:
        return path
    base, width = sb
    return f"{base}.{1:0{width}d}"


def part_paths(path: str, known_sizes: list[int] | None = None) -> list[str]:
    """All part paths. Parts already deleted by an earlier run are included when the
    journal knows how many parts there were (*known_sizes*)."""
    base, width = split_base(path)
    out, i = [], 1
    while True:
        p = f"{base}.{i:0{width}d}"
        if os.path.exists(p) or (known_sizes and i <= len(known_sizes)):
            out.append(p)
            i += 1
            continue
        break
    return out


class _PartsReader(io.RawIOBase):
    """Read-only, seekable view of the concatenated parts. Deleted parts must never be
    read again (the engine only reads entries after the release point)."""

    def __init__(self, paths: list[str], sizes: list[int]):
        super().__init__()
        self.paths, self.sizes = paths, sizes
        self.starts, pos = [], 0
        for s in sizes:
            self.starts.append(pos)
            pos += s
        self.total = pos
        self.pos = 0
        self.cur = -1
        self.fh = None
        self.lock = threading.Lock()

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, off, whence=0):
        if whence == 0:
            self.pos = off
        elif whence == 1:
            self.pos += off
        else:
            self.pos = self.total + off
        if self.pos < 0:
            raise OSError("negative seek position")
        return self.pos

    def _part_of(self, pos: int) -> int:
        lo, hi = 0, len(self.starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.starts[mid] <= pos:
                lo = mid
            else:
                hi = mid - 1
        return lo

    def readinto(self, b):
        n = len(b)
        if n == 0 or self.pos >= self.total:
            return 0
        with self.lock:
            i = self._part_of(self.pos)
            if i != self.cur:
                self._close_fh()
                fd = os.open(winfs.long_path(self.paths[i]),
                             os.O_RDONLY | getattr(os, "O_BINARY", 0)
                             | getattr(os, "O_SEQUENTIAL", 0) | getattr(os, "O_CLOEXEC", 0))
                winfs.advise_sequential(fd)
                self.fh, self.cur = os.fdopen(fd, "rb", buffering=0), i
            off = self.pos - self.starts[i]
            self.fh.seek(off)
            want = min(n, self.sizes[i] - off)
            data = self.fh.read(want)
        b[:len(data)] = data
        self.pos += len(data)
        return len(data)

    def _close_fh(self):
        if self.fh is not None:
            self.fh.close()
            self.fh, self.cur = None, -1

    def drop(self, i: int) -> None:
        """Close our handle if it belongs to part *i* (so the part can be deleted)."""
        with self.lock:
            if self.cur == i:
                self._close_fh()

    def close(self):
        with self.lock:
            self._close_fh()
        super().close()


class ArchiveSource:
    """Common interface for a single ZIP and a split ZIP."""

    def __init__(self, archive: str, journal: dict | None = None):
        self.archive = archive
        self.split = is_split(archive)
        self._readers: list[_PartsReader] = []
        self._readers_lock = threading.Lock()
        if not self.split:
            self.paths = [archive]
            self.sizes = [os.path.getsize(archive)] if os.path.exists(archive) else [0]
            return
        known = (journal or {}).get("part_sizes")
        self.paths = part_paths(archive, known)
        self.sizes = []
        for i, p in enumerate(self.paths):
            if os.path.exists(p):
                self.sizes.append(os.path.getsize(p))
            elif known and i < len(known):
                self.sizes.append(int(known[i]))
            else:
                raise FileNotFoundError(p)

    # ------------------------------------------------------------------ info
    @property
    def size(self) -> int:
        return sum(self.sizes)

    @property
    def existing(self) -> list[str]:
        return [p for p in self.paths if os.path.exists(p)]

    @property
    def probe_path(self) -> str:
        """A file that still exists (for volume / attribute checks)."""
        ex = self.existing
        return ex[-1] if ex else self.archive

    def allocated(self) -> int:
        total = 0
        for p in self.paths:
            try:
                total += winfs.allocated_size(p)
            except FileNotFoundError:
                pass
        return total

    def part_start(self, i: int) -> int:
        return sum(self.sizes[:i])

    # ------------------------------------------------------------------ io
    def open(self):
        """Binary, seekable file object for zipfile (with 256 KiB read buffering)."""
        if not self.split:
            fd = os.open(winfs.long_path(self.archive),
                         os.O_RDONLY | getattr(os, "O_BINARY", 0)
                         | getattr(os, "O_SEQUENTIAL", 0) | getattr(os, "O_CLOEXEC", 0))
            winfs.advise_sequential(fd)
            return os.fdopen(fd, "rb", buffering=_READ_BUF)
        r = _PartsReader(self.paths, self.sizes)
        with self._readers_lock:
            self._readers.append(r)
        return io.BufferedReader(r, buffer_size=_READ_BUF)

    def drop_part(self, i: int) -> None:
        with self._readers_lock:
            readers = list(self._readers)
        for r in readers:
            r.drop(i)

    def releaser(self, punch: bool):
        return _SingleReleaser(self.archive) if not self.split else _PartsReleaser(self, punch)

    def remove_all(self) -> None:
        for p in self.paths:
            try:
                os.remove(p)
            except FileNotFoundError:
                pass


class _SingleReleaser:
    def __init__(self, path: str):
        self.sp = winfs.SparseFile(path)

    def release(self, start: int, end: int) -> None:
        self.sp.release(start, end)

    def close(self) -> None:
        self.sp.close()


class _PartsReleaser:
    """Deletes parts that lie completely before *end*; punches the rest (optional)."""

    def __init__(self, src: ArchiveSource, punch: bool):
        self.src, self.punch = src, punch
        self.sparse: dict[int, winfs.SparseFile] = {}

    def release(self, start: int, end: int) -> None:
        src = self.src
        for i, p in enumerate(src.paths):
            ps = src.part_start(i)
            pe = ps + src.sizes[i]
            if pe <= end:
                if os.path.exists(p):
                    sp = self.sparse.pop(i, None)
                    if sp:
                        sp.close()
                    src.drop_part(i)
                    try:
                        os.remove(winfs.long_path(p))
                    except FileNotFoundError:
                        pass
            elif ps < end and self.punch and os.path.exists(p):
                if i not in self.sparse:
                    self.sparse[i] = winfs.SparseFile(p)
                self.sparse[i].release(max(0, start - ps), end - ps)
                break
            else:
                break

    def close(self) -> None:
        for sp in self.sparse.values():
            sp.close()
        self.sparse.clear()
