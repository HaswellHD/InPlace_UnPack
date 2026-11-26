import hashlib
import os
import random
import sys
import zipfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["INPLACE_UNPACK_NO_JOBS"] = "1"  # never touch the real job list / autostart
import tempfile  # noqa: E402
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="iu-appdata-")  # never touch real settings

from inplace_unpack import engine, plan as planmod, winfs  # noqa: E402


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha(path: str) -> str:
    h = hashlib.sha256()
    with open(winfs.long_path(path), "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def rand_bytes(n: int, seed: int) -> bytes:
    return random.Random(seed).randbytes(n)


def make_zip(path, members, compression=zipfile.ZIP_STORED):
    """members: list of (name, bytes) ; name ending in '/' = directory."""
    with zipfile.ZipFile(path, "w", compression) as z:
        for name, data in members:
            if name.endswith("/") and not data:
                z.writestr(zipfile.ZipInfo(name), b"")
            else:
                z.writestr(zipfile.ZipInfo(name, date_time=(2021, 6, 15, 12, 30, 0)), data,
                           compress_type=compression)
    return str(path)


def all_files(root):
    out = {}
    for dp, _, fns in os.walk(root):
        for fn in fns:
            p = os.path.join(dp, fn)
            out[os.path.relpath(p, root)] = file_sha(p)
    return out


def extract(archive, target, **kw):
    run_kw = {k: kw.pop(k) for k in list(kw) if k in ("durable", "_fault", "cancel",
                                                     "on_progress", "delete_archive",
                                                     "settings")}
    if "settings" in run_kw:
        kw["settings"] = run_kw["settings"]
    p = planmod.analyze(archive, target, **kw)
    assert p.ok, p.problems
    return engine.run(p, **run_kw)


@pytest.fixture
def every_entry_commits(monkeypatch):
    """Commit (journal + release) after every entry, so crash points are exact."""
    monkeypatch.setattr(engine, "COMMIT_BYTES", 1)
