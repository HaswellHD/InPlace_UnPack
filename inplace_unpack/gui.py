"""The window. Windows and Linux each get their own look, everything else is shared.

Windows: the classic native look (_gui_nt).
Linux:   KDE/GNOME file dialogs, dark/light theme, language button (_gui_posix).

This module *becomes* the platform module (sys.modules swap), so
`from inplace_unpack import gui`, `gui.App` and monkeypatching in tests all
work on the real implementation.
"""
import os
import sys

if os.name == "nt":
    from . import _gui_nt as _impl
else:
    from . import _gui_posix as _impl

if __name__ == "__main__":
    _impl.main()
else:
    sys.modules[__name__] = _impl
