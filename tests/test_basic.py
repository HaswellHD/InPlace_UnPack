import os
import time
import zipfile

import pytest

from conftest import all_files, extract, make_zip, rand_bytes, sha
from inplace_unpack import journal, winfs


@pytest.mark.parametrize("compression", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED,
                                         zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA])
def test_roundtrip_and_space_released(tmp_path, compression):
    members = [(f"dir{i % 3}/file{i}.bin", rand_bytes(300_000 + i * 1000, i)) for i in range(20)]
    members.append(("empty.txt", b""))
    members.append(("emptydir/", b""))
    z = make_zip(tmp_path / "a.zip", members, compression)
    size = os.path.getsize(z)
    cd = size - zipfile.ZipFile(z).start_dir

    r = extract(z, tmp_path / "out")

    got = all_files(tmp_path / "out")
    for name, data in members:
        if not name.endswith("/"):
            assert got[name.replace("/", os.sep)] == sha(data)
    assert os.path.isdir(tmp_path / "out" / "emptydir")
    assert r.entries == len(members)
    # everything except the central directory (and at most one partial unit) is released
    assert winfs.allocated_size(z) <= cd + 2 * 65536
    assert not os.path.exists(journal.journal_path(z))
    assert not [p for p in os.listdir(tmp_path / "out" / "dir0") if p.endswith(".part")]


def test_unicode_names(tmp_path):
    names = ["Ärger/Überprüfung äöüß.txt", "日本語/ファイル.txt", "emoji_😀.txt",
             "Ελληνικά/αρχείο.txt", "עברית.txt", "a" * 180 + ".txt"]
    members = [(n, n.encode("utf-8") * 10) for n in names]
    z = make_zip(tmp_path / "u.zip", members, zipfile.ZIP_DEFLATED)
    extract(z, tmp_path / "out")
    got = all_files(tmp_path / "out")
    for n, data in members:
        assert got[n.replace("/", os.sep)] == sha(data)


def test_timestamps_preserved(tmp_path):
    z = make_zip(tmp_path / "t.zip", [("x.txt", b"hello")])
    extract(z, tmp_path / "out")
    expected = time.mktime((2021, 6, 15, 12, 30, 0, 0, 0, -1))
    assert abs(os.path.getmtime(tmp_path / "out" / "x.txt") - expected) <= 2


def test_many_small_files_release_space(tmp_path):
    """Prototype bug M1: tiny ranges never freed whole 64 KB units."""
    members = [(f"s/{i:05}.txt", rand_bytes(1000 + (i * 37) % 4000, i)) for i in range(3000)]
    z = make_zip(tmp_path / "small.zip", members)
    size = os.path.getsize(z)
    cd = size - zipfile.ZipFile(z).start_dir
    extract(z, tmp_path / "out", durable=False)
    assert len(all_files(tmp_path / "out")) == 3000
    assert winfs.allocated_size(z) <= cd + 2 * 65536, (winfs.allocated_size(z), cd)


def test_delete_archive_option(tmp_path):
    z = make_zip(tmp_path / "d.zip", [("x.txt", b"x" * 1000)])
    r = extract(z, tmp_path / "out", delete_archive=True)
    assert r.archive_deleted and not os.path.exists(z)
    assert not os.path.exists(journal.journal_path(z))
