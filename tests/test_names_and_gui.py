import os

import pytest

from conftest import make_zip
from inplace_unpack import names, plan as planmod


@pytest.mark.parametrize("raw,expected", [
    ("../../a.txt", ["a.txt"]),
    ("C:\\x\\y.txt", ["x", "y.txt"]),
    ("a/./b//c", ["a", "b", "c"]),
    ("CON", ["_CON"]),
    ("con.tar.gz", ["_con.tar.gz"]),
    ("LPT9.log", ["_LPT9.log"]),
    ("console.txt", ["console.txt"]),
    ('a<b>c:d"e|f?g*h', ["a_b_c_d_e_f_g_h"]),
    ("name. . ", ["name"]),
    ("...", []),
])
def test_split_safe(raw, expected):
    assert names.split_safe(raw) == expected


def test_long_component_is_shortened_and_unique():
    a = names.split_safe("x" * 300 + "1.txt")[0]
    b = names.split_safe("x" * 300 + "2.txt")[0]
    assert len(a) <= names.MAX_COMPONENT and a != b and a.endswith(".txt")


def test_assign_paths_deterministic():
    m = [("A.txt", False), ("a.txt", False), ("a", False), ("a/b", False)]
    r1 = names.assign_paths(m)
    assert r1 == names.assign_paths(m)
    assert [x[0] for x in r1] == [["A.txt"], ["a (2).txt"], ["a (2)"], ["a", "b"]]


def test_gui_smoke(tmp_path):
    tk = pytest.importorskip("tkinter")
    from inplace_unpack import gui
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    root.withdraw()
    app = gui.App(root)
    z = make_zip(tmp_path / "g.zip", [("a.txt", b"a")])
    app.zip_var.set(z)
    app.target_var.set(str(tmp_path / "out"))
    app.show_plan(planmod.analyze(z, tmp_path / "out"))
    app.update_buttons()
    assert str(app.btn_start["state"]) == "normal"   # no extra confirmation checkbox
    assert not app.modes_open
    app.toggle_modes()
    assert app.modes_open and app.modes_frame.winfo_manager() == "grid"

    # mode switch changes the engine settings and keeps user choices
    app.settings.temp_dir = ""
    app.settings.auto_resume = False
    app.mode_var.set("safe")
    app.mode_changed()
    assert app.settings.mode == "safe" and app.settings.sync_interval_mb == 64
    assert app.settings.auto_resume is False

    # advanced dialog: invalid values are clamped and saved
    from inplace_unpack import settings as st
    dlg = gui.AdvancedDialog(app)
    dlg.vars["max_threads"][0].set("500")
    dlg.vars["sync_interval_mb"][0].set("3")
    dlg.vars["auto_threads"][0].set(False)
    gui.messagebox.showinfo = lambda *a, **k: None
    dlg.save()
    assert app.settings.max_threads <= (os.cpu_count() or 1)
    assert app.settings.sync_interval_mb == 16
    assert st.load().sync_interval_mb == 16

    # progress display with statistics does not fail
    from inplace_unpack import engine
    app.show_progress(engine.Progress(1, 2, 10, 20, "x", 5, 100, elapsed=3, speed=1e6, eta=12,
                                      threads=2, active=1, stats=app.sampler.sample(),
                                      low_space=True))
    assert app.mon_vals["m_eta"].get() == "0:12"
    root.destroy()


def test_job_registry(tmp_path, monkeypatch):
    from inplace_unpack import jobs, journal, settings as st
    monkeypatch.setattr(jobs, "DISABLED", False)
    calls = []
    monkeypatch.setattr(jobs, "set_autostart", lambda on: calls.append(on))
    z = make_zip(tmp_path / "a.zip", [("a", b"a")])
    s = st.for_mode("balanced")
    s.resume_after_reboot = True
    jobs.register(z, str(tmp_path / "out"), s)
    assert jobs.pending() == []            # no journal yet -> nothing to resume
    journal.save(z, {"fingerprint": "x", "target": str(tmp_path / "out"), "done": 0})
    assert jobs.pending()[0]["archive"] == os.path.abspath(z)
    jobs.unregister(z)
    assert jobs.pending() == [] and calls == [True, False]


def test_auto_resume_starts_immediately(tmp_path, monkeypatch):
    tk = pytest.importorskip("tkinter")
    from inplace_unpack import gui, jobs
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    root.withdraw()
    app = gui.App(root)
    z = make_zip(tmp_path / "r.zip", [("a", b"a")])
    job = {"archive": z, "target": str(tmp_path / "out")}
    monkeypatch.setattr(jobs, "pending", lambda: [job])
    launched = []
    monkeypatch.setattr(app, "launch", lambda *a: launched.append(a))
    app.settings.auto_resume = True
    app.offer_pending(False)
    assert launched == [(z, job["target"], False, False)]   # no countdown, no click
    assert app.retry_job is None
    root.destroy()


def test_shell_menu_registry(tmp_path, monkeypatch):
    """Right-click entry: written under a test key/folder, then removed again."""
    from inplace_unpack import shellmenu
    if os.name != "nt":
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
        (tmp_path / "xdg" / "nautilus").mkdir(parents=True)
        shellmenu.install("Extract with Inplace-Unpack")
        assert shellmenu.installed()
        kde_file = (tmp_path / "xdg" / "kio" / "servicemenus" / "inplace-unpack.desktop").read_text()
        assert "application/zip" in kde_file and "application/octet-stream" not in kde_file
        assert (tmp_path / "xdg" / "nautilus" / "scripts" / "Inplace-Unpack").exists()
        shellmenu.uninstall()
        assert not shellmenu.installed()
        return
    import winreg
    monkeypatch.setattr(shellmenu, "_BASE",
                        "Software\\Inplace-Unpack-Test\\{ext}\\shell\\" + shellmenu.KEY_NAME)
    try:
        shellmenu.install("Extract with Inplace-Unpack")
        assert shellmenu.installed()
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, shellmenu._BASE.format(ext=".zip") + r"\command") as k:
            cmd = winreg.QueryValueEx(k, None)[0]
        assert '"%1"' in cmd
        shellmenu.uninstall()
        assert not shellmenu.installed()
    finally:
        shellmenu.uninstall()
        for ext in shellmenu.EXTENSIONS:
            for sub in (f"Software\\Inplace-Unpack-Test\\{ext}\\shell", f"Software\\Inplace-Unpack-Test\\{ext}"):
                try:
                    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
                except OSError:
                    pass
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, "Software\\Inplace-Unpack-Test")
        except OSError:
            pass


def test_utf8_multibyte_long_component_fits_linux_name_max(tmp_path):
    """95 Japanese/Cyrillic chars = 285 UTF-8 bytes (> Linux NAME_MAX 255) must be shortened."""
    from conftest import all_files, extract, sha
    long_jp = "日本語テストファイル名_" + "あ" * 95 + "1.txt"
    long_jp2 = "日本語テストファイル名_" + "あ" * 95 + "2.txt"
    a = names.split_safe(long_jp)[0]
    b = names.split_safe(long_jp2)[0]
    assert len(a.encode("utf-8")) <= names.MAX_UTF8_BYTES and a != b and a.endswith(".txt")
    z = make_zip(tmp_path / "jp.zip", [(long_jp, b"one"), (long_jp2, b"two")])
    extract(z, tmp_path / "out")
    assert sorted(all_files(tmp_path / "out").values()) == sorted([sha(b"one"), sha(b"two")])


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlinks and permissions")
def test_linux_overwrite_symlink_does_not_chmod_target_and_preserves_exec(tmp_path):
    """Overwriting a symlink in target must never chmod the symlink's target file;
    Unix executable entries (+x) preserve their executable bit."""
    import zipfile
    from conftest import extract
    secret = tmp_path / "outside_secret.txt"
    secret.write_bytes(b"keep-readable")
    secret.chmod(0o644)
    out = tmp_path / "out"
    out.mkdir()
    os.symlink(str(secret), str(out / "run.sh"))

    zpath = str(tmp_path / "exec.zip")
    with zipfile.ZipFile(zpath, "w") as zf:
        zi = zipfile.ZipInfo("run.sh", date_time=(2024, 1, 1, 0, 0, 0))
        zi.create_system = 3
        zi.external_attr = (0o100755 << 16)
        zf.writestr(zi, b"#!/bin/sh\necho ok\n")

    extract(zpath, out, overwrite=True)
    # outside_secret.txt must still be 0o644 (not clobbered to 0o200 by symlink chmod!)
    assert (secret.stat().st_mode & 0o777) == 0o644
    assert secret.read_bytes() == b"keep-readable"
    assert not (out / "run.sh").is_symlink()
    assert os.access(out / "run.sh", os.X_OK)


def test_bench_runs(tmp_path, capsys):
    from inplace_unpack import bench
    assert bench.main(["--dir", str(tmp_path), "--size-mb", "16", "--small", "80",
                       "--json", str(tmp_path / "r.json")]) == 0
    out = capsys.readouterr().out
    for m in ("safe", "balanced", "performance"):
        assert m in out
    import json
    assert len(json.load(open(tmp_path / "r.json"))["results"]) == 3
