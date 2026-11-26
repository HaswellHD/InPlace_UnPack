"""Abort / crash / resume. A simulated crash raises SimulatedCrash, which the
engine does not catch: no cleanup runs, exactly like a killed process. The
hard-kill tests really terminate a child process with os._exit()."""
import os
import subprocess
import sys
import threading
import zipfile

import pytest

from conftest import ROOT, all_files, extract, file_sha, make_zip, rand_bytes, sha
from inplace_unpack import engine, journal, plan as planmod, winfs

N = 12


def members():
    return [(f"d/f{i:02}.bin", rand_bytes(200_000 + i * 7000, i)) for i in range(N)]


def check_complete(tmp_path, z, mem):
    got = all_files(tmp_path / "out")
    assert {k: v for k, v in got.items()} == {n.replace("/", os.sep): sha(d) for n, d in mem}
    assert not os.path.exists(journal.journal_path(z))
    assert winfs.allocated_size(z) <= os.path.getsize(z) - zipfile.ZipFile(z).start_dir + 2 * 65536


@pytest.mark.parametrize("phase", ["mid_write", "after_extract", "after_commit", "after_release"])
@pytest.mark.parametrize("at", [0, 5, N - 1])
def test_crash_and_resume(tmp_path, every_entry_commits, phase, at):
    mem = members()
    z = make_zip(tmp_path / "a.zip", mem)
    size0 = winfs.allocated_size(z)

    def fault(p, i):
        if p == phase and i == at:
            raise engine.SimulatedCrash()

    with pytest.raises(engine.SimulatedCrash):
        extract(z, tmp_path / "out", _fault=fault)
    assert os.path.exists(journal.journal_path(z))
    if phase == "after_release" and at >= 5:
        assert winfs.allocated_size(z) < size0  # space really was released before the crash

    p = planmod.analyze(z, tmp_path / "out")
    assert p.ok and p.resuming, p.problems
    engine.run(p)
    check_complete(tmp_path, z, mem)


def test_double_crash(tmp_path, every_entry_commits):
    mem = members()
    z = make_zip(tmp_path / "a.zip", mem)
    for at in (3, 8):
        def fault(p, i, at=at):
            if p == "after_commit" and i == at:
                raise engine.SimulatedCrash()
        p = planmod.analyze(z, tmp_path / "out")
        assert p.ok
        with pytest.raises(engine.SimulatedCrash):
            engine.run(p, _fault=fault)
    engine.run(planmod.analyze(z, tmp_path / "out"))
    check_complete(tmp_path, z, mem)


def test_cancel_then_resume(tmp_path, every_entry_commits):
    mem = members()
    z = make_zip(tmp_path / "a.zip", mem)
    ev = threading.Event()

    def press_pause_after_entry_3(p, i):  # like the user clicking "Pause"
        if (p, i) == ("after_extract", 3):
            ev.set()

    with pytest.raises(engine.RunStopped) as ei:
        extract(z, tmp_path / "out", cancel=ev, _fault=press_pause_after_entry_3)
    assert ei.value.key == "cancelled" and ei.value.resumable
    j = journal.load(z)
    assert 4 <= j["done"] < N
    engine.run(planmod.analyze(z, tmp_path / "out"))
    check_complete(tmp_path, z, mem)


def test_resume_requires_same_target(tmp_path, every_entry_commits):
    z = make_zip(tmp_path / "a.zip", members())
    with pytest.raises(engine.SimulatedCrash):
        extract(z, tmp_path / "out", _fault=lambda p, i: (_ for _ in ()).throw(
            engine.SimulatedCrash()) if (p, i) == ("after_release", 4) else None)
    p = planmod.analyze(z, tmp_path / "other")
    assert [k for k, _ in p.problems] == ["journal_other_target"]


def test_journal_of_other_zip_is_refused(tmp_path, every_entry_commits):
    z = make_zip(tmp_path / "a.zip", members())
    with pytest.raises(engine.SimulatedCrash):
        extract(z, tmp_path / "out", _fault=lambda p, i: (_ for _ in ()).throw(
            engine.SimulatedCrash()) if (p, i) == ("after_extract", 2) else None)
    os.remove(z)
    make_zip(tmp_path / "a.zip", [("other.txt", b"different zip")])
    assert "journal_mismatch" in {k for k, _ in planmod.analyze(z, tmp_path / "out").problems}


def test_lost_journal_is_detected(tmp_path, every_entry_commits):
    z = make_zip(tmp_path / "a.zip", members())
    with pytest.raises(engine.SimulatedCrash):
        extract(z, tmp_path / "out", _fault=lambda p, i: (_ for _ in ()).throw(
            engine.SimulatedCrash()) if (p, i) == ("after_release", 6) else None)
    os.remove(journal.journal_path(z))
    p = planmod.analyze(z, tmp_path / "out2")
    assert "local_header_missing" in {k for k, _ in p.problems}


def damage_entry_5(z):
    with zipfile.ZipFile(z) as zf:
        info = sorted(zf.infolist(), key=lambda i: i.header_offset)[5]
    data = bytearray(open(z, "rb").read())
    pos = info.header_offset + 30 + len(info.filename) + 1000
    data[pos] ^= 0xFF
    open(z, "wb").write(data)
    return info, data


def test_crc_error_stops_cleanly(tmp_path, every_entry_commits):
    from inplace_unpack import settings as st
    mem = members()
    z = make_zip(tmp_path / "a.zip", mem)
    info, data = damage_entry_5(z)
    tail_before = bytes(data[info.header_offset:])

    s = st.for_mode("balanced")
    s.keep_damaged = False
    with pytest.raises(engine.RunStopped) as ei:
        extract(z, tmp_path / "out", settings=s)
    assert ei.value.key == "crc"
    got = all_files(tmp_path / "out")
    assert len(got) == 5  # entries 0..4 done, no half-written entry 5
    with open(z, "rb") as f:
        f.seek(info.header_offset)
        assert f.read() == tail_before  # entry 5 and later untouched
    assert journal.load(z)["done"] == 5


@pytest.mark.parametrize("mode", ["balanced", "performance"])
def test_damaged_entry_is_kept_and_run_continues(tmp_path, every_entry_commits, mode):
    """Default in Balanced/Performance: a CRC error does not stop the run; the damaged
    entry is written byte-for-byte as stored and listed in <zip>.damaged.txt."""
    from inplace_unpack import settings as st
    mem = members()
    z = make_zip(tmp_path / "a.zip", mem, compression=zipfile.ZIP_STORED)
    info, data = damage_entry_5(z)
    start = info.header_offset + 30 + len(info.filename) + len(info.extra)
    stored = bytes(data[start:start + info.compress_size])

    r = extract(z, tmp_path / "out", settings=st.for_mode(mode))
    assert r.damaged == [info.filename]
    got = all_files(tmp_path / "out")
    assert len(got) == N
    assert got[info.filename.replace("/", os.sep)] == sha(stored)   # kept exactly as stored
    report = open(z + ".damaged.txt", encoding="utf-8").read()
    assert info.filename in report
    assert not os.path.exists(journal.journal_path(z))


def test_damaged_large_entry_streamed_is_kept(tmp_path):
    """Same for an entry big enough to go through the decompress/write pipeline."""
    big = rand_bytes(10 * 1024 * 1024, 7)
    z = make_zip(tmp_path / "a.zip", [("a.txt", b"a"), ("big.bin", big), ("z.txt", b"z")])
    with zipfile.ZipFile(z) as zf:
        info = zf.getinfo("big.bin")
    data = bytearray(open(z, "rb").read())
    start = info.header_offset + 30 + len(info.filename)
    data[start + 5_000_000] ^= 0xFF
    open(z, "wb").write(data)
    r = extract(z, tmp_path / "out")
    assert r.damaged == ["big.bin"]
    assert open(tmp_path / "out" / "big.bin", "rb").read() == bytes(data[start:start + len(big)])
    assert (tmp_path / "out" / "z.txt").read_bytes() == b"z"


def test_safe_mode_still_stops_on_damage(tmp_path, every_entry_commits):
    from inplace_unpack import settings as st
    z = make_zip(tmp_path / "a.zip", members())
    damage_entry_5(z)
    with pytest.raises(engine.RunStopped) as ei:
        extract(z, tmp_path / "out", settings=st.for_mode("safe"))
    assert ei.value.key == "crc"


def test_space_precheck(tmp_path, monkeypatch):
    z = make_zip(tmp_path / "a.zip", members())
    monkeypatch.setattr(winfs, "free_bytes", lambda p: 10 * 1024 * 1024)
    p = planmod.analyze(z, tmp_path / "out")
    assert [k for k, _ in p.problems] == ["space"]
    assert planmod.analyze(z, tmp_path / "out", ignore_space=True).ok


def test_space_runs_out_during_run_then_resume(tmp_path, monkeypatch, every_entry_commits):
    mem = members()
    z = make_zip(tmp_path / "a.zip", mem)
    p = planmod.analyze(z, tmp_path / "out")
    assert p.ok
    real = winfs.free_bytes
    calls = {"n": 0}

    def fake(path):
        calls["n"] += 1
        return real(path) if calls["n"] < 6 else 1024
    monkeypatch.setattr(winfs, "free_bytes", fake)
    with pytest.raises(engine.RunStopped) as ei:
        engine.run(p)
    assert ei.value.key == "out_of_space" and ei.value.resumable
    assert not [f for f in all_files(tmp_path / "out") if f.endswith(".part")]
    monkeypatch.setattr(winfs, "free_bytes", real)
    engine.run(planmod.analyze(z, tmp_path / "out"))
    check_complete(tmp_path, z, mem)


def test_disk_full_mid_write_removes_part_file(tmp_path, monkeypatch):
    mem = members()
    z = make_zip(tmp_path / "a.zip", mem)
    p = planmod.analyze(z, tmp_path / "out")

    def fault(phase, i):
        if phase == "mid_write" and i == 3:
            raise OSError(28, "No space left on device")
    with pytest.raises(engine.RunStopped) as ei:
        engine.run(p, _fault=fault)
    assert ei.value.key == "out_of_space"
    assert not [f for f in all_files(tmp_path / "out") if ".part" in f]
    engine.run(planmod.analyze(z, tmp_path / "out"))
    check_complete(tmp_path, z, mem)


def _cli(args, env_extra=None):
    env = dict(os.environ, PYTHONPATH=ROOT, **(env_extra or {}))
    return subprocess.run([sys.executable, "-m", "inplace_unpack", *args, "--yes"],
                          cwd=ROOT, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=300)


@pytest.mark.parametrize("kill_at", ["after_extract:7", "mid_write:12", "after_commit:5", "after_release:5"])
def test_hard_kill_of_real_process_then_resume(tmp_path, kill_at):
    mem = [(f"big/f{i:02}.bin", rand_bytes(9 * 1024 * 1024, i)) for i in range(18)]
    z = make_zip(tmp_path / "k.zip", mem)
    r = _cli([z, str(tmp_path / "out")], {"INPLACE_UNPACK_TEST_KILL": kill_at})
    assert r.returncode == 99, r.stdout + r.stderr
    r = _cli([z, str(tmp_path / "out")])
    assert r.returncode == 0, r.stdout + r.stderr
    check_complete(tmp_path, z, mem)
