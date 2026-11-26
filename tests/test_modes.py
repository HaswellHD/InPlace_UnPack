"""Extraction modes, advanced settings, journal compatibility and integrity."""
import json
import os
import subprocess
import time
import zipfile

import pytest

from conftest import ROOT, all_files, extract, file_sha, make_zip, rand_bytes, sha
from inplace_unpack import engine, journal, plan as planmod, settings as st, winfs

MODES = list(st.MODES)


def mixed_members():
    big = [(f"big/b{i}.bin", rand_bytes(12 * 1024 * 1024 + i, 100 + i)) for i in range(3)]
    small = [(f"small/s{i:04}.txt", rand_bytes(500 + (i * 131) % 20000, i)) for i in range(400)]
    return big[:1] + small[:200] + big[1:2] + small[200:] + big[2:]


def done_ok(tmp_path, z, mem, out="out"):
    got = all_files(tmp_path / out)
    assert got == {n.replace("/", os.sep): sha(d) for n, d in mem}
    assert not os.path.exists(journal.journal_path(z))
    assert winfs.allocated_size(z) <= os.path.getsize(z) - zipfile.ZipFile(z).start_dir + 2 * 65536


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("comp", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
def test_every_mode_extracts_correctly(tmp_path, mode, comp):
    mem = mixed_members()
    z = make_zip(tmp_path / "m.zip", mem, comp)
    r = extract(z, tmp_path / "out", settings=st.for_mode(mode))
    done_ok(tmp_path, z, mem)
    assert r.entries == len(mem)


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("phase,at", [("mid_write", 150), ("after_extract", 201),
                                      ("after_commit", 300), ("mid_write", 0)])
def test_every_mode_survives_crash(tmp_path, every_entry_commits, mode, phase, at):
    mem = mixed_members()
    z = make_zip(tmp_path / "m.zip", mem, zipfile.ZIP_DEFLATED)
    s = st.for_mode(mode)

    def fault(p, i):
        if p == phase and i == at:
            raise engine.SimulatedCrash()
    with pytest.raises(engine.SimulatedCrash):
        extract(z, tmp_path / "out", settings=s, _fault=fault)
    # resume with a *different* mode: must still be correct
    other = st.for_mode(MODES[(MODES.index(mode) + 1) % 3])
    p = planmod.analyze(z, tmp_path / "out", settings=other)
    assert p.ok and p.resuming, p.problems
    engine.run(p, settings=other)
    done_ok(tmp_path, z, mem)


@pytest.mark.parametrize("phase,at", [("mid_write", 0), ("mid_write", 201), ("after_extract", 201),
                                      ("after_commit", 300), ("after_release", 402)])
def test_performance_survives_crash_and_resumes(tmp_path, every_entry_commits, phase, at):
    """A crash at any phase leaves a state that resumes to a complete, correct result."""
    mem = mixed_members()
    z = make_zip(tmp_path / "m.zip", mem, zipfile.ZIP_DEFLATED)
    s = st.for_mode("performance")

    def fault(p, i):
        if p == phase and i == at:
            raise engine.SimulatedCrash()
    with pytest.raises(engine.SimulatedCrash):
        extract(z, tmp_path / "out", settings=s, _fault=fault)
    p = planmod.analyze(z, tmp_path / "out", settings=s)
    assert p.ok and p.resuming, p.problems
    engine.run(p, settings=s)
    done_ok(tmp_path, z, mem)


def test_never_releases_before_commit(tmp_path, every_entry_commits, monkeypatch):
    """Release offsets never pass the start of an entry that is not committed."""
    mem = mixed_members()
    z = make_zip(tmp_path / "m.zip", mem, zipfile.ZIP_DEFLATED)
    released, committed = [], [0]
    real_save = journal.save

    def save(archive, state, durable=True):
        real_save(archive, state, durable)
        committed[0] = state.get("done", 0)
    monkeypatch.setattr(journal, "save", save)
    real_rel = winfs.SparseFile.release

    def rel(self, start, end):
        released.append((end, committed[0]))
        return real_rel(self, start, end)
    monkeypatch.setattr(winfs.SparseFile, "release", rel)
    s = st.for_mode("performance")
    p = planmod.analyze(z, tmp_path / "out", settings=s)
    starts = [e.start for e in p.entries] + [p.cd_start]
    engine.run(p, settings=s)
    assert released
    for end, done in released:
        assert end <= starts[done]
    done_ok(tmp_path, z, mem)


def test_parallel_error_commits_only_contiguous_prefix(tmp_path, every_entry_commits):
    mem = mixed_members()
    z = make_zip(tmp_path / "m.zip", mem)
    s = st.for_mode("performance")

    def fault(p, i):
        if p == "mid_write" and i == 120:
            raise OSError(5, "simulated I/O error")
    with pytest.raises(engine.RunStopped) as ei:
        extract(z, tmp_path / "out", settings=s, _fault=fault)
    assert ei.value.key == "io_error"
    assert journal.load(z)["done"] <= 120
    engine.run(planmod.analyze(z, tmp_path / "out", settings=s), settings=s)
    done_ok(tmp_path, z, mem)


def test_settings_validation_clamps_everything():
    s = st.Settings(mode="turbo", max_threads=999, max_cpu_percent=1, max_ram_mb=10 ** 9,
                    ram_threshold_percent=200, sync_interval_mb=1, flush_interval_mb=-5,
                    max_temp_gb=-1, priority="realtime", max_write_mb_s=-3)
    s, fixed = st.validate(s)
    assert s.mode == "balanced" and s.priority == "below_normal"
    assert 1 <= s.max_threads <= (os.cpu_count() or 1)
    assert s.max_cpu_percent == 10 and s.sync_interval_mb == 16
    assert s.max_ram_mb * 1024 * 1024 <= max(64 * 1024 * 1024, st.sysinfo.total_ram() // 4)
    assert s.ram_threshold_percent == 95 and s.flush_interval_mb == 0
    assert s.max_temp_gb == 0.25 and s.max_write_mb_s == 0
    assert len(fixed) >= 10


def test_settings_roundtrip(tmp_path):
    s = st.for_mode("safe")
    s.max_threads = 3
    st.save(s, str(tmp_path / "s.json"))
    assert st.load(str(tmp_path / "s.json")) == st.validate(s)[0]
    (tmp_path / "bad.json").write_text("{not json")
    assert st.load(str(tmp_path / "bad.json")).mode == "balanced"


def test_sync_interval_controls_journal_writes(tmp_path, monkeypatch):
    mem = [(f"f{i}", rand_bytes(4 * 1024 * 1024, i)) for i in range(16)]  # 64 MiB
    z = make_zip(tmp_path / "s.zip", mem)
    saves = []
    real = journal.save
    monkeypatch.setattr(journal, "save", lambda *a, **k: (saves.append(1), real(*a, **k)))
    s = st.for_mode("safe")
    s.sync_interval_mb = 16
    extract(z, tmp_path / "o1", settings=s)
    many = len(saves)
    saves.clear()
    z2 = make_zip(tmp_path / "s2.zip", mem)
    s.sync_interval_mb = 1024
    extract(z2, tmp_path / "o2", settings=s)
    assert many >= 4 and len(saves) <= 2, (many, len(saves))


def test_write_speed_limit_is_enforced(tmp_path):
    mem = [("a.bin", rand_bytes(30 * 1024 * 1024, 1))]
    z = make_zip(tmp_path / "w.zip", mem)
    s = st.for_mode("performance")
    s.max_write_mb_s = 15
    t = time.monotonic()
    extract(z, tmp_path / "out", settings=s)
    assert time.monotonic() - t >= 1.5  # 30 MB at 15 MB/s ~ 2 s
    done_ok(tmp_path, z, mem)


def test_cpu_throttle_sleeps_when_over_budget(monkeypatch):
    """Simulate a process that burns 4 cores while only 25 % of 4 cores (= 1) is allowed."""
    clock = {"t": 100.0, "cpu": 0.0}
    monkeypatch.setattr(os, "cpu_count", lambda: 4)
    monkeypatch.setattr(engine.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(engine.sysinfo, "process_cpu_seconds", lambda: clock["cpu"])
    slept = []
    monkeypatch.setattr(engine.time, "sleep", lambda d: slept.append(d))
    th = engine.Throttle(25, 0)
    clock["t"] += 0.5
    clock["cpu"] += 2.0          # 2 CPU-seconds in 0.5 s = 4 cores busy
    th.wrote(1)
    assert slept and slept[0] == pytest.approx(0.5)  # capped; (2.0 - 0.5) / 1 = 1.5 s wanted
    slept.clear()
    th2 = engine.Throttle(100, 0)
    clock["cpu"] += 5
    th2.wrote(1)
    assert not slept             # 100 % = no throttling at all


def test_temp_dir_same_volume(tmp_path):
    mem = mixed_members()[:50]
    z = make_zip(tmp_path / "t.zip", mem)
    (tmp_path / "tmp").mkdir()
    s = st.for_mode("balanced")
    s.temp_dir = str(tmp_path / "tmp")
    extract(z, tmp_path / "out", settings=s)
    done_ok(tmp_path, z, mem)
    assert os.listdir(tmp_path / "tmp") == []


def test_temp_dir_other_volume_copies(tmp_path, monkeypatch):
    mem = mixed_members()[:30]
    z = make_zip(tmp_path / "t.zip", mem)
    (tmp_path / "tmp").mkdir()
    real = winfs.same_volume
    monkeypatch.setattr(winfs, "same_volume",
                        lambda a, b: False if "tmp" in (a + b) and "out" in (a + b) else real(a, b))
    s = st.for_mode("balanced")
    s.temp_dir = str(tmp_path / "tmp")
    p = planmod.analyze(z, tmp_path / "out", settings=s)
    assert ("temp_other_volume", {}) in p.warnings
    engine.run(p, settings=s)
    done_ok(tmp_path, z, mem)
    assert os.listdir(tmp_path / "tmp") == []


def test_missing_temp_dir_is_refused(tmp_path):
    z = make_zip(tmp_path / "t.zip", [("a", b"a")])
    s = st.for_mode("balanced")
    s.temp_dir = str(tmp_path / "does-not-exist")
    assert "temp_missing" in {k for k, _ in planmod.analyze(z, tmp_path / "out", settings=s).problems}


def test_verify_written_detects_corruption(tmp_path, monkeypatch):
    mem = [("a.bin", rand_bytes(100_000, 1)), ("b.bin", rand_bytes(100_000, 2))]
    z = make_zip(tmp_path / "v.zip", mem)
    s = st.for_mode("safe")
    real_open = open
    import builtins

    class Corrupting:
        def __init__(self, f):
            self.f = f

        def write(self, b):
            b = bytes(b)
            return self.f.write(b[:-1] + bytes([b[-1] ^ 1]) if len(b) else b)

        def __getattr__(self, k):
            return getattr(self.f, k)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return self.f.__exit__(*a)

    def fake_open(path, mode="r", *a, **k):
        f = real_open(path, mode, *a, **k)
        return Corrupting(f) if "wb" in mode and str(path).endswith(".part") else f
    monkeypatch.setattr(builtins, "open", fake_open)
    with pytest.raises(engine.RunStopped) as ei:
        extract(z, tmp_path / "out", settings=s)
    monkeypatch.undo()
    assert ei.value.key == "crc" and "verification" in ei.value.params["error"]
    with zipfile.ZipFile(z) as zf:  # nothing was released
        assert zf.read("a.bin") == mem[0][1]


def test_low_ram_falls_back_to_streaming(tmp_path, monkeypatch):
    mem = mixed_members()[:60]
    z = make_zip(tmp_path / "r.zip", mem, zipfile.ZIP_DEFLATED)
    monkeypatch.setattr(st.sysinfo, "memory_load", lambda: 99)
    extract(z, tmp_path / "out", settings=st.for_mode("performance"))
    done_ok(tmp_path, z, mem)


# --- journal ------------------------------------------------------------------
def test_journal_checksum_detects_tampering(tmp_path, every_entry_commits):
    z = make_zip(tmp_path / "j.zip", mixed_members()[:20])
    with pytest.raises(engine.SimulatedCrash):
        extract(z, tmp_path / "out", _fault=lambda p, i: (_ for _ in ()).throw(
            engine.SimulatedCrash()) if (p, i) == ("after_release", 5) else None)
    jp = journal.journal_path(z)
    data = json.load(open(jp, encoding="utf-8"))
    assert data["format"] == "inplace-unzip/2" and data["done"] == 6
    assert data["last_entry"] and data["mode"] == "balanced"
    data["done"] = 15  # someone edits the journal
    json.dump(data, open(jp, "w", encoding="utf-8"))
    p = planmod.analyze(z, tmp_path / "out")
    assert [k for k, _ in p.problems] == ["journal_corrupt"]
    assert journal.describe(z)["valid"] is False


def test_v1_journal_is_still_accepted(tmp_path, every_entry_commits):
    mem = mixed_members()[:40]
    z = make_zip(tmp_path / "j.zip", mem)
    with pytest.raises(engine.SimulatedCrash):
        extract(z, tmp_path / "out", _fault=lambda p, i: (_ for _ in ()).throw(
            engine.SimulatedCrash()) if (p, i) == ("after_release", 9) else None)
    jp = journal.journal_path(z)
    d = json.load(open(jp, encoding="utf-8"))
    v1 = {"format": "inplace-unzip/1", "fingerprint": d["fingerprint"], "target": d["target"],
          "name_encoding": None, "overwrite": False, "entries": d["entries"], "done": d["done"]}
    json.dump(v1, open(jp, "w", encoding="utf-8"))
    p = planmod.analyze(z, tmp_path / "out")
    assert p.ok and p.resuming and p.done == 10
    engine.run(p)
    done_ok(tmp_path, z, mem)


OLD_EXE = os.path.join(ROOT, "dist", "v0.2.0", "inplace-unzip.exe")


@pytest.mark.skipif(not os.path.exists(OLD_EXE), reason="v0.2.0 executable not available")
def test_resume_a_run_started_by_version_0_2_0(tmp_path):
    """Real upgrade scenario: v0.2.0 is killed mid-run, the new version resumes."""
    mem = [(f"big/f{i:02}.bin", rand_bytes(9 * 1024 * 1024, i)) for i in range(14)]
    z = make_zip(tmp_path / "old.zip", mem)
    env = dict(os.environ, INPLACE_UNZIP_TEST_KILL="after_release:5")
    r = subprocess.run([OLD_EXE, z, str(tmp_path / "out"), "--yes"], env=env,
                       capture_output=True, timeout=300)
    assert r.returncode == 99
    j = json.load(open(journal.journal_path(z), encoding="utf-8"))
    assert j["format"] == "inplace-unzip/1" and j["done"] >= 6
    for mode in ("safe",):
        p = planmod.analyze(z, tmp_path / "out", settings=st.for_mode(mode))
        assert p.ok and p.resuming, p.problems
        engine.run(p)
    done_ok(tmp_path, z, mem)
