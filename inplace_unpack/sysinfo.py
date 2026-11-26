"""Platform dispatch for system information / resource monitoring."""
import os

if os.name == "nt":
    from ._sysinfo_nt import *  # noqa: F401,F403
else:
    from ._sysinfo_posix import *  # noqa: F401,F403
