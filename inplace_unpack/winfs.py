"""Platform dispatch for the file-system helpers.

Windows: Win32 / NTFS sparse files (_winfs_nt).
Linux:   fallocate(FALLOC_FL_PUNCH_HOLE) on btrfs/ext4/xfs/... (_winfs_posix).
"""
import os

if os.name == "nt":
    from ._winfs_nt import *  # noqa: F401,F403

    def same_pool(a: str, b: str) -> bool:
        return same_volume(a, b)  # noqa: F405

    def advise_sequential(fd: int) -> None:
        pass

    def drop_cache(fd: int, offset: int = 0, length: int = 0) -> None:
        pass

    fdatasync = os.fsync

    def fsync_dir(path: str) -> None:
        pass
else:
    from ._winfs_posix import *  # noqa: F401,F403
