"""Zip-slip, hostile names, and every pre-flight refusal must leave the ZIP untouched."""
import hashlib
import os
import struct
import subprocess
import zipfile

import pytest

from conftest import all_files, extract, file_sha, make_zip, rand_bytes, sha
from inplace_unpack import engine, plan as planmod


def keys(p):
    return {k for k, _ in p.problems}


def cd_entries(data: bytes):
    """Offsets of the central directory headers in a zip byte string."""
    out, i = [], data.find(b"PK\x01\x02")
    while i != -1:
        out.append(i)
        i = data.find(b"PK\x01\x02", i + 4)
    return out


def patch_cd(path, entry_no, offset, fmt, value):
    data = bytearray(open(path, "rb").read())
    pos = cd_entries(bytes(data))[entry_no] + offset
    struct.pack_into(fmt, data, pos, value)
    open(path, "wb").write(data)


def test_zip_slip_stays_inside(tmp_path):
    evil = ["../evil1.txt", "..\\evil2.txt", "C:/evil3.txt", "/evil4.txt",
            "a/../../evil5.txt", "\\\\server\\share\\evil6.txt", "../evildir/",
            "C:\\Windows\\evil7.txt"]
    members = [(n, b"" if n.endswith("/") else n.encode()) for n in evil]
    z = make_zip(tmp_path / "evil.zip", members)
    extract(z, tmp_path / "out")
    assert sorted(os.listdir(tmp_path)) == ["evil.zip", "out"]
    files = all_files(tmp_path / "out")
    assert len(files) == 7  # every file entry landed inside "out"
    for _, s in files.items():
        assert s in {sha(n.encode()) for n in evil}


def test_reserved_and_illegal_names(tmp_path):
    names = ["CON.txt", "aux", "nul/inner.txt", "a:b.txt", "trailing. ", "q?.txt",
             "COM1", "tab\tname.txt"]
    z = make_zip(tmp_path / "r.zip", [(n, n.encode()) for n in names])
    p = planmod.analyze(z, tmp_path / "out")
    assert p.ok, p.problems
    engine.run(p)
    files = all_files(tmp_path / "out")
    assert len(files) == len(names)
    assert set(files.values()) == {sha(n.encode()) for n in names}
    assert all(not os.path.basename(f).upper().startswith(("CON", "AUX", "NUL", "COM1"))
               for f in files)


def test_duplicate_and_case_clashing_names_are_all_kept(tmp_path):
    members = [("A.txt", b"1"), ("a.txt", b"2"), ("dup.txt", b"3"), ("dup.txt", b"4"),
               ("x", b"5"), ("x/y.txt", b"6"), ("X/Y.TXT", b"7")]
    with pytest.warns(UserWarning):
        z = make_zip(tmp_path / "d.zip", members)
    extract(z, tmp_path / "out")
    files = all_files(tmp_path / "out")
    assert sorted(files.values()) == sorted(sha(d) for _, d in members)


def _unchanged(z, before):
    assert file_sha(z) == before


def test_encrypted_entry_refused_before_anything_is_destroyed(tmp_path):
    z = make_zip(tmp_path / "e.zip", [(f"f{i}", rand_bytes(100_000, i)) for i in range(5)])
    patch_cd(z, 3, 8, "<H", 0x1)  # general purpose flag: encrypted
    before = file_sha(z)
    p = planmod.analyze(z, tmp_path / "out")
    assert "encrypted" in keys(p)
    with pytest.raises(ValueError):
        engine.run(p)
    _unchanged(z, before)
    assert not os.path.exists(tmp_path / "out")


def test_deflate64_refused(tmp_path):
    z = make_zip(tmp_path / "m.zip", [("a", b"a" * 1000), ("b", b"b" * 1000)])
    patch_cd(z, 1, 10, "<H", 9)  # compression method 9 = Deflate64
    before = file_sha(z)
    p = planmod.analyze(z, tmp_path / "out")
    assert "method" in keys(p)
    assert "Deflate64" in str(p.problems)
    _unchanged(z, before)


def test_overlapping_entries_refused(tmp_path):
    z = make_zip(tmp_path / "o.zip", [("a", b"a" * 5000), ("b", b"b" * 5000)])
    patch_cd(z, 1, 42, "<I", 0)  # entry b now points at entry a's data
    before = file_sha(z)
    p = planmod.analyze(z, tmp_path / "out")
    assert not p.ok
    _unchanged(z, before)


def test_entry_cannot_overwrite_archive_or_journal(tmp_path):
    z = make_zip(tmp_path / "self.zip", [("ok.txt", b"1"), ("SELF.ZIP", b"boom")])
    p = planmod.analyze(z, tmp_path)
    assert "collides_archive" in keys(p)
    z2 = make_zip(tmp_path / "j.zip", [("j.zip.unzip-progress", b"boom")])
    assert "collides_archive" in keys(planmod.analyze(z2, tmp_path))


def test_existing_files_need_permission(tmp_path):
    z = make_zip(tmp_path / "c.zip", [("x.txt", b"new")])
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "x.txt").write_bytes(b"old")
    assert "conflicts" in keys(planmod.analyze(z, tmp_path / "out"))
    (tmp_path / "out" / "x.txt").chmod(0o444)  # read-only must not stop an allowed overwrite
    extract(z, tmp_path / "out", overwrite=True)
    assert (tmp_path / "out" / "x.txt").read_bytes() == b"new"


def test_junction_inside_target_is_not_followed(tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(out / "sub"), str(elsewhere)],
                       check=True, capture_output=True)
    else:
        os.symlink(str(elsewhere), str(out / "sub"), target_is_directory=True)
    z = make_zip(tmp_path / "j.zip", [("first.txt", rand_bytes(200_000, 1)),
                                       ("sub/x.txt", b"pwned")])
    p = planmod.analyze(z, out, overwrite=True)
    assert p.ok, p.problems
    with pytest.raises(engine.RunStopped) as ei:
        engine.run(p)
    assert ei.value.key == "link_in_target"
    assert os.listdir(elsewhere) == []
    # the refused entry's data is still in the zip
    with zipfile.ZipFile(z) as zf:
        assert zf.read("sub/x.txt") == b"pwned"


def test_not_a_zip(tmp_path):
    f = tmp_path / "x.zip"
    f.write_bytes(b"not a zip at all" * 100)
    assert "bad_zip" in keys(planmod.analyze(f, tmp_path / "out"))


def test_missing_archive(tmp_path):
    assert "archive_missing" in keys(planmod.analyze(tmp_path / "nope.zip", tmp_path / "out"))
