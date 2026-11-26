"""Linux implementation of the file-system helpers (same API as _winfs_nt).

Space is released with fallocate(FALLOC_FL_PUNCH_HOLE | FALLOC_FL_KEEP_SIZE),
which btrfs, ext4, xfs, f2fs, tmpfs, zfs and bcachefs support. No root needed.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import errno
import fcntl
import os
import stat

FILE_SUPPORTS_SPARSE_FILES = 0x00000040
FILE_ATTRIBUTE_READONLY = 0x1
FILE_ATTRIBUTE_REPARSE_POINT = 0x400

_FALLOC_FL_KEEP_SIZE = 0x01
_FALLOC_FL_PUNCH_HOLE = 0x02
_PUNCH_FS = {"btrfs", "ext4", "xfs", "f2fs", "tmpfs", "zfs", "bcachefs", "ocfs2", "gfs2"}

_libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)
_libc.fallocate.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_long, ctypes.c_long]
_libc.fallocate.restype = ctypes.c_int


def long_path(path: str) -> str:
    return os.path.abspath(path)


def is_disk_full(exc: BaseException) -> bool:
    return isinstance(exc, OSError) and exc.errno in (errno.ENOSPC, errno.EDQUOT)


def _existing_dir(path: str) -> str:
    p = os.path.abspath(path)
    while not os.path.isdir(p):
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    return p


def _unescape(s: str) -> str:
    return s.replace("\\040", " ").replace("\\011", "\t").replace("\\012", "\n").replace("\\134", "\\")


def _mount_of(path: str) -> tuple[str, str]:
    """(mount point, fs type) of the mount holding *path* (longest prefix match)."""
    p = os.path.realpath(_existing_dir(path))
    best, fstype = "/", "?"
    try:
        with open("/proc/self/mountinfo", encoding="utf-8", errors="replace") as f:
            for line in f:
                left, _, right = line.partition(" - ")
                mp = _unescape(left.split()[4])
                if (p == mp or p.startswith(mp.rstrip("/") + "/")) and len(mp) >= len(best):
                    best, fstype = mp, right.split()[0]
    except OSError:
        pass
    return best, fstype


def volume_root(path: str) -> str:
    return _mount_of(path)[0]


def volume_info(path: str) -> tuple[str, int, int]:
    """(file system name, flags, device id) of the volume holding *path*."""
    fs = _mount_of(path)[1]
    flags = FILE_SUPPORTS_SPARSE_FILES if fs.lower() in _PUNCH_FS else 0
    return fs, flags, os.stat(_existing_dir(path)).st_dev


def supports_sparse(path: str) -> bool:
    try:
        return bool(volume_info(path)[1] & FILE_SUPPORTS_SPARSE_FILES)
    except OSError:
        return False


def same_volume(a: str, b: str) -> bool:
    try:
        return os.stat(_existing_dir(a)).st_dev == os.stat(_existing_dir(b)).st_dev
    except OSError:
        return False


def cluster_size(path: str) -> int:
    try:
        return max(512, os.statvfs(_existing_dir(path)).f_bsize)
    except OSError:
        return 4096


def free_bytes(path: str) -> int:
    v = os.statvfs(_existing_dir(path))
    return v.f_bavail * v.f_frsize


def allocated_size(path: str) -> int:
    return os.stat(path).st_blocks * 512


def file_attributes(path: str) -> int:
    a = 0
    st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode):
        a |= FILE_ATTRIBUTE_REPARSE_POINT
    if not os.access(path, os.W_OK):
        a |= FILE_ATTRIBUTE_READONLY
    return a


def is_reparse_point(path: str) -> bool:
    return os.path.islink(path)


def is_cloud_placeholder(path: str) -> bool:
    return False


class SparseFile:
    """Read/write handle on the archive used to punch holes into it.

    Takes an exclusive advisory lock so a second Inplace-Unpack can't work on it.
    """

    def __init__(self, path: str):
        self.fd = os.open(long_path(path), os.O_RDWR | os.O_CLOEXEC)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(self.fd)
            self.fd = None
            raise

    def release(self, start: int, end: int) -> None:
        """Zero the byte range [start, end) and deallocate whole blocks."""
        if end <= start:
            return
        if _libc.fallocate(self.fd, _FALLOC_FL_PUNCH_HOLE | _FALLOC_FL_KEEP_SIZE,
                           start, end - start) != 0:
            e = ctypes.get_errno()
            raise OSError(e, os.strerror(e))

    def close(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
