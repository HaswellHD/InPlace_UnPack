"""Platform dispatch for the file-system helpers.

Windows: Win32 / NTFS sparse files (_winfs_nt).
Linux:   fallocate(FALLOC_FL_PUNCH_HOLE) on btrfs/ext4/xfs/... (_winfs_posix).
"""
import os

if os.name == "nt":
    from ._winfs_nt import *  # noqa: F401,F403
else:
    from ._winfs_posix import *  # noqa: F401,F403
