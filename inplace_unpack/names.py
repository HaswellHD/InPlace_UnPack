"""Turning archive member names into safe, unique Windows paths.

Rules (all applied before anything is written):
* "/" and "\\" are both separators; empty, "." and ".." parts are dropped,
  as are drive letters ("C:") - nothing can escape the target folder.
* characters Windows forbids (<>:"|?* and control characters) become "_",
  trailing dots and spaces are stripped.
* reserved device names (CON, NUL, COM1, ...) get a "_" prefix.
* overlong names are shortened with a hash so they stay unique.
* names that clash on Windows (case-insensitive, or a file where a folder
  must go) get " (2)", " (3)", ... appended. The result is deterministic, so
  a resumed run computes exactly the same names.
"""
from __future__ import annotations

import hashlib
import re

_SEP = re.compile(r"[\\/]+")
_ILLEGAL = re.compile(r'[<>:"|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
_RESERVED |= {f"{p}{n}" for p in ("COM", "LPT") for n in list("123456789") + ["¹", "²", "³"]}
MAX_COMPONENT = 200  # NTFS allows 255 UTF-16 units; keep room for " (n)" and ".part"


def sanitize_component(part: str) -> str | None:
    c = _ILLEGAL.sub("_", part).rstrip(" .")
    if not c or c in (".", ".."):
        return None
    stem = c.split(".", 1)[0].rstrip(" ").upper()
    if stem in _RESERVED:
        c = "_" + c
    if len(c) > MAX_COMPONENT:
        digest = hashlib.sha1(part.encode("utf-8", "surrogatepass")).hexdigest()[:10]
        base, dot, ext = c.rpartition(".")
        ext = (dot + ext) if dot and len(ext) <= 20 else ""
        c = c[:MAX_COMPONENT - len(ext) - 11] + "~" + digest + ext
    return c


def split_safe(name: str) -> list[str]:
    parts = _SEP.split(name)
    out: list[str] = []
    for i, p in enumerate(parts):
        if p in ("", ".", ".."):
            continue
        if i == 0 and len(p) == 2 and p[1] == ":":  # drive letter
            continue
        s = sanitize_component(p)
        if s is not None:
            out.append(s)
    return out


def _key(parts) -> str:
    return "\\".join(parts).casefold()


def _numbered(parts: list[str], n: int) -> list[str]:
    last = parts[-1]
    base, dot, ext = last.rpartition(".")
    if dot and base:
        new = f"{base} ({n}).{ext}"
    else:
        new = f"{last} ({n})"
    return parts[:-1] + [new]


def assign_paths(members: list[tuple[str, bool]]) -> list[tuple[list[str] | None, bool]]:
    """For each (name, is_dir) return (safe path parts or None, renamed?).

    None means "nothing to create" (e.g. an entry that was only "../").
    """
    split = [split_safe(n) for n, _ in members]
    dirs: set[str] = set()
    for parts, (_, is_dir) in zip(split, members):
        upto = len(parts) if is_dir else len(parts) - 1
        for k in range(1, upto + 1):
            dirs.add(_key(parts[:k]))

    files: set[str] = set()
    result: list[tuple[list[str] | None, bool]] = []
    for parts, (orig, is_dir) in zip(split, members):
        if not parts:
            if is_dir:
                result.append((None, False))
                continue
            parts = ["_unnamed"]
        if is_dir:
            result.append((parts, False))
            continue
        cand, n = parts, 1
        while _key(cand) in dirs or _key(cand) in files:
            n += 1
            cand = _numbered(parts, n)
        files.add(_key(cand))
        result.append((cand, n > 1 or "/".join(cand) != orig.replace("\\", "/").strip("/")))
    return result
