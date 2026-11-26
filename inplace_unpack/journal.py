"""Crash-safe progress journal stored next to the archive.

The journal records *how many* entries (in file-offset order) are finished,
plus information for inspection (bytes done, last entry, mode, time).
It is always replaced atomically: write temp file -> fsync -> os.replace
(-> directory fsync on Linux), so after a crash it holds either the old or
the new state.

Format 2 adds a SHA-256 checksum over its own content (integrity check).
Format 1 journals (written by version 0.2.x) are still accepted, so a run
started with an older version can be resumed by a newer one.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os

from . import winfs

FORMAT = "inplace-unzip/2"
ACCEPTED = ("inplace-unzip/1", "inplace-unzip/2")
SUFFIX = ".unzip-progress"  # unchanged since 0.2.0 - do not rename (resume compatibility)


def journal_path(archive: str) -> str:
    return os.path.abspath(archive) + SUFFIX


class JournalError(Exception):
    pass


def _checksum(data: dict) -> str:
    body = {k: v for k, v in data.items() if k != "checksum"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False)
                          .encode("utf-8")).hexdigest()


def load(archive: str) -> dict | None:
    p = journal_path(archive)
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise JournalError(str(e)) from e
    if not isinstance(data, dict) or data.get("format") not in ACCEPTED:
        raise JournalError("unknown format")
    if data["format"] != "inplace-unzip/1" and data.get("checksum") != _checksum(data):
        raise JournalError("checksum mismatch")
    for k, typ in (("fingerprint", str), ("target", str), ("done", int)):
        if not isinstance(data.get(k), typ):
            raise JournalError(f"missing field {k}")
    return data


def save(archive: str, data: dict, durable: bool = True) -> None:
    p = journal_path(archive)
    tmp = p + ".tmp"
    data = dict(data, format=FORMAT,
                updated=_dt.datetime.now().isoformat(timespec="seconds"))
    data["checksum"] = _checksum(data)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
        f.flush()
        if durable:
            os.fsync(f.fileno())
    os.replace(tmp, p)
    if durable:
        winfs.fsync_dir(os.path.dirname(p))


def remove(archive: str) -> None:
    for p in (journal_path(archive), journal_path(archive) + ".tmp"):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass


def describe(archive: str) -> dict:
    """Recovery information for display. Never raises."""
    p = journal_path(archive)
    if not os.path.exists(p):
        return {"exists": False, "path": p}
    try:
        j = load(archive)
        return {"exists": True, "valid": True, "path": p, **j}
    except JournalError as e:
        return {"exists": True, "valid": False, "path": p, "error": str(e)}
