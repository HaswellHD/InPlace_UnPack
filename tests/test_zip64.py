"""ZIP64. The >4 GB test writes ~9 GB to disk and takes a few minutes, so it
only runs with INPLACE_UNPACK_LARGE=1."""
import hashlib
import os
import random
import zipfile

import pytest

from conftest import all_files, extract, file_sha, make_zip, rand_bytes, sha
from inplace_unpack import engine, journal, plan as planmod, winfs

GB = 1024 ** 3


def test_forced_zip64_headers(tmp_path):
    p = tmp_path / "z64.zip"
    data = [rand_bytes(150_000, i) for i in range(6)]
    with zipfile.ZipFile(p, "w") as z:
        for i, d in enumerate(data):
            with z.open(f"f{i}.bin", "w", force_zip64=True) as w:
                w.write(d)
    extract(p, tmp_path / "out")
    got = all_files(tmp_path / "out")
    assert [got[f"f{i}.bin"] for i in range(6)] == [sha(d) for d in data]


def test_more_than_65535_entries(tmp_path):
    n = 66_000
    p = tmp_path / "many.zip"
    with zipfile.ZipFile(p, "w") as z:
        for i in range(n):
            z.writestr(f"d{i // 1000:02}/{i}.txt", str(i))
    with zipfile.ZipFile(p) as z:
        assert len(z.infolist()) == n
    extract(p, tmp_path / "out", durable=False)
    count = sum(len(f) for _, _, f in os.walk(tmp_path / "out"))
    assert count == n
    assert (tmp_path / "out" / "d65" / "65999.txt").read_text() == "65999"


def _pattern_writer(w, total, seed):
    """Write *total* incompressible-looking bytes fast (1 MiB random block, varied)."""
    rnd = random.Random(seed)
    block = bytearray(rnd.randbytes(1 << 20))
    h = hashlib.sha256()
    left = total
    k = 0
    while left:
        block[0:8] = k.to_bytes(8, "little")  # every MiB differs
        chunk = block if left >= len(block) else block[:left]
        w.write(chunk)
        h.update(chunk)
        left -= len(chunk)
        k += 1
    return h.hexdigest()


@pytest.mark.skipif(os.environ.get("INPLACE_UNPACK_LARGE") != "1",
                    reason="set INPLACE_UNPACK_LARGE=1 (needs ~10 GB free, several minutes)")
def test_entry_larger_than_4gb_and_offsets_beyond_4gb(tmp_path):
    size1 = 4 * GB + 300 * 1024 * 1024  # stored -> next entry starts beyond 4 GB
    p = tmp_path / "large.zip"
    hashes = {}
    with zipfile.ZipFile(p, "w", zipfile.ZIP_STORED, allowZip64=True) as z:
        zi = zipfile.ZipInfo("huge.bin")
        zi.file_size = size1
        with z.open(zi, "w", force_zip64=True) as w:
            hashes["huge.bin"] = _pattern_writer(w, size1, 1)
        with z.open("after_4gb.bin", "w") as w:
            hashes["after_4gb.bin"] = _pattern_writer(w, 50 * 1024 * 1024, 2)
        z.writestr("tail.txt", b"tail")
        hashes["tail.txt"] = sha(b"tail")
    with zipfile.ZipFile(p) as z:
        infos = sorted(z.infolist(), key=lambda i: i.header_offset)
        assert infos[1].header_offset > 4 * GB

    plan = planmod.analyze(p, tmp_path / "out")
    assert plan.ok, plan.problems
    peak_seen = {"alloc": 0}

    def prog(pr):
        peak_seen["alloc"] = max(peak_seen["alloc"], pr.archive_allocated)
    engine.run(plan, prog)
    for name, h in hashes.items():
        assert file_sha(str(tmp_path / "out" / name)) == h
    assert winfs.allocated_size(p) <= 1024 * 1024
