"""File-manager right-click entry ("Extract with Inplace-Unpack") for .zip and .zip.001.

Windows: HKCU\\Software\\Classes\\SystemFileAssociations\\<ext>\\shell (no admin rights).
Linux:   KDE Dolphin ServiceMenu (~/.local/share/kio/servicemenus) and, when GNOME
         Files (Nautilus) is present, ~/.local/share/nautilus/scripts.
"""
from __future__ import annotations

import os
import shutil
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


def _data_home() -> str:
    return os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")


def _kde_menu_file() -> str:
    return os.path.join(_data_home(), "kio", "servicemenus", "inplace-unpack.desktop")


def _nautilus_script_dir() -> str:
    return os.path.join(_data_home(), "nautilus", "scripts")


def _linux_exec_prefix() -> str:
    if os.environ.get("APPIMAGE"):  # running from an AppImage: its mount point is temporary
        return f'"{os.environ["APPIMAGE"]}"'
    for cand in (os.path.expanduser("~/.local/bin/inplace-unpack"), shutil.which("inplace-unpack")):
        if cand and os.path.isfile(cand) and os.access(cand, os.X_OK):
            return f'"{cand}"'
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app_gui = os.path.join(root, "app_gui.py")
    if os.path.exists(app_gui):
        return f'"{sys.executable}" "{app_gui}"'
    return f'"{sys.executable}" -m inplace_unpack.gui'


def _linux_install(label: str) -> None:
    cmd = _linux_exec_prefix()
    f = _kde_menu_file()
    os.makedirs(os.path.dirname(f), exist_ok=True)
    # Note: split ZIP first parts (.zip.001) begin with PK\x03\x04, which shared-mime-info
    # already classifies as application/zip (no application/octet-stream pollution!).
    with open(f, "w", encoding="utf-8") as fh:
        fh.write("[Desktop Entry]\nType=Service\n"
                 "MimeType=application/zip;application/x-zip-compressed;\n"
                 "Actions=inplaceUnpack;\nX-KDE-Priority=TopLevel\n"
                 "X-KDE-RequiredNumberOfUrls=1\n\n"
                 f"[Desktop Action inplaceUnpack]\nName={label}\nIcon=inplace-unpack\n"
                 f"Exec={cmd} %f\n")
    os.chmod(f, 0o755)
    naut_parent = os.path.join(_data_home(), "nautilus")
    if os.path.isdir(naut_parent):
        sdir = _nautilus_script_dir()
        os.makedirs(sdir, exist_ok=True)
        sf = os.path.join(sdir, "Inplace-Unpack")
        with open(sf, "w", encoding="utf-8") as fh:
            fh.write('#!/bin/sh\nfirst=$(printf "%s" "$NAUTILUS_SCRIPT_SELECTED_FILE_PATHS" | head -n 1)\n'
                     f'[ -n "$first" ] && exec {cmd} "$first"\n')
        os.chmod(sf, 0o755)


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
        for p in (_kde_menu_file(), os.path.join(_nautilus_script_dir(), "Inplace-Unpack")):
            try:
                os.remove(p)
            except FileNotFoundError:
                pass
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
