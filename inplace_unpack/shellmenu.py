"""Explorer right-click entry ("Extract with Inplace-Unpack") for .zip and .zip.001.

Written to HKEY_CURRENT_USER\\Software\\Classes\\SystemFileAssociations\\<ext>\\shell,
so it needs no administrator rights, does not change the default program for ZIP
files, and only affects the current user. On Windows 11 the entry appears under
"Show more options" (the classic menu).
"""
from __future__ import annotations

import os
import sys

KEY_NAME = "InplaceUnpack"
EXTENSIONS = (".zip", ".001")
_BASE = "Software\\Classes\\SystemFileAssociations\\{ext}\\shell\\" + KEY_NAME


def command_line() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" "%1"'
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return f'"{pyw if os.path.exists(pyw) else exe}" -m inplace_unpack.gui "%1"'


def icon_path() -> str:
    return sys.executable if getattr(sys, "frozen", False) else ""


def _kde_menu_file() -> str:
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "kio", "servicemenus", "inplace-unpack.desktop")


def _linux_install(label: str) -> None:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    f = _kde_menu_file()
    os.makedirs(os.path.dirname(f), exist_ok=True)
    with open(f, "w", encoding="utf-8") as fh:
        fh.write("[Desktop Entry]\nType=Service\n"
                 "MimeType=application/zip;application/x-zip-compressed;application/octet-stream;\n"
                 "Actions=inplaceUnpack;\nX-KDE-Priority=TopLevel\n\n"
                 f"[Desktop Action inplaceUnpack]\nName={label}\nIcon=inplace-unpack\n"
                 f'Exec="{sys.executable}" "{os.path.join(root, "app_gui.py")}" %f\n')
    os.chmod(f, 0o755)


def install(label: str) -> None:
    if os.name != "nt":
        return _linux_install(label)
    import winreg
    for ext in EXTENSIONS:
        key = _BASE.format(ext=ext)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as k:
            winreg.SetValueEx(k, None, 0, winreg.REG_SZ, label)
            ico = icon_path()
            if ico:
                winreg.SetValueEx(k, "Icon", 0, winreg.REG_SZ, ico)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key + r"\command") as k:
            winreg.SetValueEx(k, None, 0, winreg.REG_SZ, command_line())


def uninstall() -> None:
    if os.name != "nt":
        if os.path.exists(_kde_menu_file()):
            os.remove(_kde_menu_file())
        return
    import winreg
    for ext in EXTENSIONS:
        key = _BASE.format(ext=ext)
        for sub in (key + r"\command", key):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
            except FileNotFoundError:
                pass


def installed() -> bool:
    if os.name != "nt":
        return os.path.exists(_kde_menu_file())
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _BASE.format(ext=".zip") + r"\command"):
            return True
    except OSError:
        return False
