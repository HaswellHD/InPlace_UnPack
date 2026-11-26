"""Thin ctypes wrappers around the Win32 file-system calls the tool needs.

Everything here works without administrator rights.
"""
from __future__ import annotations

import ctypes
import os
import struct
from ctypes import wintypes

FSCTL_SET_SPARSE = 0x000900C4
FSCTL_SET_ZERO_DATA = 0x000980C8
FILE_SUPPORTS_SPARSE_FILES = 0x00000040

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x1
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
INVALID_FILE_SIZE = 0xFFFFFFFF

FILE_ATTRIBUTE_READONLY = 0x1
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000

ERROR_DISK_FULL = 112
ERROR_HANDLE_DISK_FULL = 39

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)

_k32.CreateFileW.restype = wintypes.HANDLE
_k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                             wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                             wintypes.HANDLE]
_k32.CloseHandle.argtypes = [wintypes.HANDLE]
_k32.CloseHandle.restype = wintypes.BOOL
_k32.DeviceIoControl.restype = wintypes.BOOL
_k32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID,
                                 wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                                 ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
_k32.GetVolumeInformationW.restype = wintypes.BOOL
_k32.GetVolumeInformationW.argtypes = [
    wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR, wintypes.DWORD]
_k32.GetVolumePathNameW.restype = wintypes.BOOL
_k32.GetVolumePathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
_k32.GetCompressedFileSizeW.restype = wintypes.DWORD
_k32.GetCompressedFileSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
_k32.GetDiskFreeSpaceExW.restype = wintypes.BOOL
_k32.GetDiskFreeSpaceExW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_ulonglong),
                                     ctypes.POINTER(ctypes.c_ulonglong),
                                     ctypes.POINTER(ctypes.c_ulonglong)]
_k32.GetDiskFreeSpaceW.restype = wintypes.BOOL
_k32.GetDiskFreeSpaceW.argtypes = [wintypes.LPCWSTR] + [ctypes.POINTER(wintypes.DWORD)] * 4


def _err():
    return ctypes.WinError(ctypes.get_last_error())


def long_path(path: str) -> str:
    r"""Absolute path with the \\?\ prefix so that paths > 260 chars work."""
    p = os.path.abspath(path)
    if p.startswith("\\\\?\\"):
        return p
    if p.startswith("\\\\"):
        return "\\\\?\\UNC\\" + p[2:]
    return "\\\\?\\" + p


def is_disk_full(exc: BaseException) -> bool:
    if isinstance(exc, OSError):
        if getattr(exc, "winerror", None) in (ERROR_DISK_FULL, ERROR_HANDLE_DISK_FULL):
            return True
        import errno
        return exc.errno == errno.ENOSPC
    return False


def _existing_dir(path: str) -> str:
    """Nearest existing directory at or above *path*."""
    p = os.path.abspath(path)
    while not os.path.isdir(p):
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    return p


def volume_root(path: str) -> str:
    buf = ctypes.create_unicode_buffer(1024)
    if not _k32.GetVolumePathNameW(os.path.abspath(path), buf, len(buf)):
        raise _err()
    root = buf.value
    return root if root.endswith("\\") else root + "\\"


def volume_info(path: str) -> tuple[str, int, int]:
    """(file system name, flags, serial number) of the volume holding *path*."""
    root = volume_root(_existing_dir(path))
    serial = wintypes.DWORD(0)
    flags = wintypes.DWORD(0)
    fsname = ctypes.create_unicode_buffer(64)
    if not _k32.GetVolumeInformationW(root, None, 0, ctypes.byref(serial), None,
                                      ctypes.byref(flags), fsname, len(fsname)):
        raise _err()
    return fsname.value, flags.value, serial.value


def supports_sparse(path: str) -> bool:
    try:
        return bool(volume_info(path)[1] & FILE_SUPPORTS_SPARSE_FILES)
    except OSError:
        return False


def same_volume(a: str, b: str) -> bool:
    try:
        return (volume_root(_existing_dir(a)).lower() == volume_root(_existing_dir(b)).lower()
                and volume_info(a)[2] == volume_info(b)[2])
    except OSError:
        return False


def cluster_size(path: str) -> int:
    root = volume_root(_existing_dir(path))
    spc, bps, nfree, ntotal = (wintypes.DWORD() for _ in range(4))
    if not _k32.GetDiskFreeSpaceW(root, ctypes.byref(spc), ctypes.byref(bps),
                                  ctypes.byref(nfree), ctypes.byref(ntotal)):
        return 4096
    return max(512, spc.value * bps.value)


def free_bytes(path: str) -> int:
    """Free bytes available to the current user (respects disk quotas)."""
    avail, total, tfree = ctypes.c_ulonglong(), ctypes.c_ulonglong(), ctypes.c_ulonglong()
    if not _k32.GetDiskFreeSpaceExW(_existing_dir(path), ctypes.byref(avail),
                                    ctypes.byref(total), ctypes.byref(tfree)):
        raise _err()
    return avail.value


def allocated_size(path: str) -> int:
    """Bytes really allocated on disk for *path* (shrinks as ranges are freed)."""
    high = wintypes.DWORD(0)
    ctypes.set_last_error(0)
    low = _k32.GetCompressedFileSizeW(long_path(path), ctypes.byref(high))
    if low == INVALID_FILE_SIZE and ctypes.get_last_error() != 0:
        raise _err()
    return (high.value << 32) | low


def file_attributes(path: str) -> int:
    return getattr(os.lstat(long_path(path)), "st_file_attributes", 0)


def is_reparse_point(path: str) -> bool:
    return bool(file_attributes(path) & FILE_ATTRIBUTE_REPARSE_POINT)


def is_cloud_placeholder(path: str) -> bool:
    a = file_attributes(path)
    return bool(a & (FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_OPEN
                     | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS))


class SparseFile:
    """Handle on the archive used to release ranges.

    Opened with FILE_SHARE_READ only: other programs may read the archive
    (our own zipfile reader does), but nobody can write, rename or delete it
    while we work on it.
    """

    def __init__(self, path: str):
        self.h = _k32.CreateFileW(long_path(path), GENERIC_READ | GENERIC_WRITE,
                                  FILE_SHARE_READ, None, OPEN_EXISTING, 0, None)
        if self.h == INVALID_HANDLE_VALUE or self.h is None:
            raise _err()
        ret = wintypes.DWORD(0)
        if not _k32.DeviceIoControl(self.h, FSCTL_SET_SPARSE, None, 0, None, 0,
                                    ctypes.byref(ret), None):
            e = _err()
            self.close()
            raise e

    def release(self, start: int, end: int) -> None:
        """Zero the byte range [start, end) and deallocate whole sparse units."""
        if end <= start:
            return
        buf = ctypes.create_string_buffer(struct.pack("<qq", start, end), 16)
        ret = wintypes.DWORD(0)
        if not _k32.DeviceIoControl(self.h, FSCTL_SET_ZERO_DATA, buf, 16,
                                    None, 0, ctypes.byref(ret), None):
            raise _err()

    def close(self) -> None:
        if self.h not in (None, INVALID_HANDLE_VALUE):
            _k32.CloseHandle(self.h)
            self.h = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
