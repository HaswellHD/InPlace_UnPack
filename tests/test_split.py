"""Split ZIPs (name.zip.001, .002, ...): extraction, deleting finished parts, crash + resume."""
import os
import zipfile

import pytest

from conftest import all_files, extract, make_zip, rand_bytes, sha
from inplace_unpack import engine, journal, plan as planmod, settings as st, source

N = 10


def members():
    return [(f"d/f{i:02}.bin", rand_bytes(300_000 + i * 11_000, i + 50)) for i in range(N)]


def split_zip(z, part_size):
    data = open(z, "rb").read()
    os.remove(z)
    paths = []
    for k in range(0, len(data), part_size):
        p = f"{z}.{k // part_size + 1:03d}"
        open(p, "wb").write(data[k:k + part_size])
        paths.append(p)
    return paths


def check(tmp_path, mem):
    got = all_files(tmp_path / "out")
    assert got == {n.replace("/", os.sep): sha(d) for n, d in mem}


def test_split_names():
    assert source.is_split(r"C:\a\b.zip.001") and source.is_split(r"C:\a\b.ZIP.012")
    assert not source.is_split(r"C:\a\b.zip") and not source.is_split(r"C:\a\b.7z.001")
    assert source.first_part(r"C:\a\b.zip.007") == r"C:\a\b.zip.001"


def test_split_zip_extracts_and_deletes_finished_parts(tmp_path, every_entry_commits):
    mem = members()
    parts = split_zip(make_zip(tmp_path / "a.zip", mem), 700_000)
    assert len(parts) >= 4
    seen = []

    def watch(p, i):
        if p == "after_release":
            seen.append(sum(os.path.exists(x) for x in parts))

    r = extract(parts[2], tmp_path / "out", _fault=watch)   # any part may be chosen
    check(tmp_path, mem)
    assert seen[0] > seen[-1]                 # parts disappeared during the run
    assert seen[-1] <= 1                      # at most the part holding the directory remains
    assert not os.path.exists(journal.journal_path(parts[0]))
    assert r.entries == N


def test_split_keep_parts_option(tmp_path, every_entry_commits):
    mem = members()
    parts = split_zip(make_zip(tmp_path / "a.zip", mem), 700_000)
    s = st.for_mode("balanced")
    s.delete_parts = False
    extract(parts[0], tmp_path / "out", settings=s)
    check(tmp_path, mem)
    assert all(os.path.exists(p) for p in parts)


@pytest.mark.parametrize("phase", ["after_commit", "after_release"])
def test_split_crash_and_resume_after_parts_were_deleted(tmp_path, every_entry_commits, phase):
    mem = members()
    parts = split_zip(make_zip(tmp_path / "a.zip", mem), 700_000)

    def crash(p, i):
        if p == phase and i == 6:
            raise engine.SimulatedCrash()

    with pytest.raises(engine.SimulatedCrash):
        extract(parts[0], tmp_path / "out", _fault=crash)
    if phase == "after_release":
        assert not os.path.exists(parts[0])   # first part already gone
    p = planmod.analyze(parts[0], tmp_path / "out")
    assert p.ok and p.resuming and p.split, p.problems
    engine.run(p)
    check(tmp_path, mem)
    assert sum(os.path.exists(x) for x in parts) <= 1


def test_split_delete_archive_removes_all_parts(tmp_path):
    mem = members()
    parts = split_zip(make_zip(tmp_path / "a.zip", mem, compression=zipfile.ZIP_DEFLATED), 900_000)
    extract(parts[0], tmp_path / "out", delete_archive=True)
    check(tmp_path, mem)
    assert not any(os.path.exists(p) for p in parts)


def test_missing_part_is_reported(tmp_path):
    parts = split_zip(make_zip(tmp_path / "a.zip", members()), 700_000)
    os.remove(parts[-1])
    p = planmod.analyze(parts[0], tmp_path / "out")
    assert not p.ok
