"""Linux implementation of the file-system helpers (same API as _winfs_nt).

Space is released with fallocate(FALLOC_FL_PUNCH_HOLE | FALLOC_FL_KEEP_SIZE),
which btrfs, ext4, xfs, f2fs, tmpfs, zfs, bcachefs, ntfs3, etc. support without root.
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
_PUNCH_FS = {
    "btrfs", "ext4", "xfs", "f2fs", "tmpfs", "zfs", "bcachefs",
    "ocfs2", "gfs2", "ntfs3", "fuseblk", "ceph",
}

_libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)
_fallocate_fn = getattr(_libc, "fallocate64", _libc.fallocate)
_fallocate_fn.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int64, ctypes.c_int64]
_fallocate_fn.restype = ctypes.c_int

_punch_cache: dict[int, bool] = {}


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
    return (s.replace("\\040", " ").replace("\\011", "\t")
             .replace("\\012", "\n").replace("\\134", "\\"))


def _mount_detail(path: str) -> tuple[str, str, str, str]:
    """(mount point, fs type, dev major:minor, mount source) for *path*."""
    p = os.path.realpath(_existing_dir(path))
    best, fstype, devid, source = "/", "?", "", ""
    try:
        with open("/proc/self/mountinfo", encoding="utf-8", errors="replace") as f:
            for line in f:
                left, sep, right = line.partition(" - ")
                if not sep:
                    continue
                lparts = left.split()
                rparts = right.split()
                if len(lparts) < 5 or len(rparts) < 2:
                    continue
                mp = _unescape(lparts[4])
                if (p == mp or p.startswith(mp.rstrip("/") + "/")) and len(mp) >= len(best):
                    best = mp
                    fstype = rparts[0]
                    devid = lparts[2]
                    source = _unescape(rparts[1])
    except OSError:
        pass
    return best, fstype, devid, source


def volume_root(path: str) -> str:
    return _mount_detail(path)[0]


def _probe_punch(dirpath: str, fstype: str, dev: int) -> bool:
    cached = _punch_cache.get(dev)
    if cached is not None:
        return cached
    o_tmpfile = getattr(os, "O_TMPFILE", 0)
    if o_tmpfile:
        fd = -1
        try:
            fd = os.open(dirpath, o_tmpfile | os.O_RDWR | os.O_CLOEXEC, 0o600)
            os.ftruncate(fd, 4096)
            rc = _fallocate_fn(fd, _FALLOC_FL_PUNCH_HOLE | _FALLOC_FL_KEEP_SIZE, 0, 4096)
            if rc == 0:
                _punch_cache[dev] = True
                return True
            if ctypes.get_errno() in (errno.EOPNOTSUPP, errno.ENOSYS):
                _punch_cache[dev] = False
                return False
        except OSError:
            pass
        finally:
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
    ok = fstype.lower() in _PUNCH_FS
    _punch_cache[dev] = ok
    return ok


def volume_info(path: str) -> tuple[str, int, int]:
    """(file system name, flags, device id) of the volume holding *path*."""
    d = _existing_dir(path)
    fs = _mount_detail(d)[1]
    dev = os.stat(d).st_dev
    flags = FILE_SUPPORTS_SPARSE_FILES if _probe_punch(d, fs, dev) else 0
    return fs, flags, dev


def supports_sparse(path: str) -> bool:
    try:
        return bool(volume_info(path)[1] & FILE_SUPPORTS_SPARSE_FILES)
    except OSError:
        return False


def same_volume(a: str, b: str) -> bool:
    """True when os.replace(a, b) works atomically without EXDEV (same st_dev)."""
    try:
        return os.stat(_existing_dir(a)).st_dev == os.stat(_existing_dir(b)).st_dev
    except OSError:
        return False


def same_pool(a: str, b: str) -> bool:
    """True when freeing blocks in *a* increases free space for *b* (includes Btrfs subvolumes)."""
    if same_volume(a, b):
        return True
    try:
        _, fs_a, dev_a, src_a = _mount_detail(a)
        _, fs_b, dev_b, src_b = _mount_detail(b)
        if dev_a and dev_a == dev_b:
            return True
        if fs_a == fs_b == "btrfs" and src_a and src_a == src_b and src_a.startswith("/dev/"):
            return True
    except OSError:
        pass
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


def advise_sequential(fd: int) -> None:
    if hasattr(os, "posix_fadvise") and hasattr(os, "POSIX_FADV_SEQUENTIAL"):
        try:
            os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_SEQUENTIAL)
        except OSError:
            pass


def drop_cache(fd: int, offset: int = 0, length: int = 0) -> None:
    if hasattr(os, "posix_fadvise") and hasattr(os, "POSIX_FADV_DONTNEED"):
        try:
            os.posix_fadvise(fd, offset, length, os.POSIX_FADV_DONTNEED)
        except OSError:
            pass


def fdatasync(fd: int) -> None:
    os.fdatasync(fd)


def fsync_dir(path: str) -> None:
    fd = -1
    try:
        fd = os.open(_existing_dir(path), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_CLOEXEC)
        os.fsync(fd)
    except OSError:
        pass
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass


class SparseFile:
    """Read/write handle on the archive used to punch holes into it.

    Takes an exclusive advisory lock so a second Inplace-Unpack can't work on it.
    """

    def __init__(self, path: str):
        self.fd: int | None = os.open(long_path(path), os.O_RDWR | os.O_CLOEXEC)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(self.fd)
            self.fd = None
            raise

    def release(self, start: int, end: int) -> None:
        """Zero the byte range [start, end) and deallocate whole blocks."""
        if end <= start or self.fd is None:
            return
        if _fallocate_fn(self.fd, _FALLOC_FL_PUNCH_HOLE | _FALLOC_FL_KEEP_SIZE,
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
