"""List of unfinished jobs (for automatic resume) and the optional
per-user autostart entry that resumes them after a reboot.

The autostart entry (HKCU\\...\\Run, no admin rights) only exists while a job
is unfinished and only if the user enabled "resume after reboot".
"""
from __future__ import annotations

import json
import os
import sys

from . import journal
from . import settings as settingsmod

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "Inplace-Unpack-Resume"
DISABLED = os.environ.get("INPLACE_UNPACK_NO_JOBS") == "1"  # tests


def _path() -> str:
    return os.path.join(settingsmod.config_dir(), "jobs.json")


def _load() -> dict:
    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    os.makedirs(settingsmod.config_dir(), exist_ok=True)
    tmp = _path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, _path())


def register(archive: str, target: str, s) -> None:
    if DISABLED:
        return
    try:
        data = _load()
        data[os.path.abspath(archive)] = {"target": target}
        _save(data)
        set_autostart(bool(s.resume_after_reboot))
    except OSError:
        pass  # the journal next to the archive is what matters; this is a convenience


def unregister(archive: str) -> None:
    if DISABLED:
        return
    try:
        data = _load()
        data.pop(os.path.abspath(archive), None)
        _save(data)
        if not pending():
            set_autostart(False)
    except OSError:
        pass


def pending() -> list[dict]:
    """Unfinished jobs whose archive and journal still exist."""
    if DISABLED:
        return []
    out = []
    for archive, info in _load().items():
        if os.path.exists(archive) and os.path.exists(journal.journal_path(archive)):
            out.append({"archive": archive, "target": info.get("target", "")})
    return out


def _linux_autostart_file() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "autostart", "inplace-unpack-resume.desktop")


def _launch_command() -> str:
    if os.name != "nt":
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return f'"{sys.executable}" "{os.path.join(root, "app_gui.py")}" --resume-pending'
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --resume-pending'
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    exe = pyw if os.path.exists(pyw) else sys.executable
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return f'"{exe}" "{os.path.join(root, "app_gui.py")}" --resume-pending'


def set_autostart(enabled: bool) -> None:
    if DISABLED:
        return
    if os.name != "nt":
        f = _linux_autostart_file()
        try:
            if enabled:
                os.makedirs(os.path.dirname(f), exist_ok=True)
                with open(f, "w", encoding="utf-8") as fh:
                    fh.write("[Desktop Entry]\nType=Application\nName=Inplace-Unpack (resume)\n"
                             f"Exec={_launch_command()}\nIcon=inplace-unpack\n"
                             "X-GNOME-Autostart-enabled=true\n")
            elif os.path.exists(f):
                os.remove(f)
        except OSError:
            pass
        return
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE) as k:
            if enabled:
                winreg.SetValueEx(k, RUN_VALUE, 0, winreg.REG_SZ, _launch_command())
            else:
                try:
                    winreg.DeleteValue(k, RUN_VALUE)
                except FileNotFoundError:
                    pass
    except OSError:
        pass


def autostart_enabled() -> bool:
    if os.name != "nt":
        return os.path.exists(_linux_autostart_file())
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_VALUE)
            return True
    except OSError:
        return False
