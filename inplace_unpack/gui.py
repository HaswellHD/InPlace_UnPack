"""Tk GUI. No extra dependencies, so the .exe stays small.

The extraction runs in a worker thread with its own (lowered) priority; the
window thread keeps normal priority, so the UI stays responsive.
"""
from __future__ import annotations

import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import __version__, engine, jobs, journal, plan as planmod, settings as st, sysinfo, winfs
from .i18n import T, fmt_bytes, fmt_duration, msg, t

RETRY_SECONDS = 30
MAX_IO_RETRIES = 5
RETRYABLE = {"out_of_space", "io_error", "permission", "out_of_memory"}


class App:
    def __init__(self, root: tk.Tk, resume_pending: bool = False, open_path: str | None = None):
        self.root = root
        root.title(f"{t('app_title')} {__version__}")
        root.minsize(900, 760)
        self.q: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.cancel = threading.Event()
        self.plan = None
        self.closing = False
        self.running = False
        self.settings = st.load()
        self.sampler = sysinfo.Sampler()
        self.retry_job = None        # after() id of a pending retry/countdown
        self.io_retries = 0
        self.last_job = None         # (archive, target, overwrite, delete)

        self.zip_var = tk.StringVar()
        self.target_var = tk.StringVar()
        self.overwrite_var = tk.BooleanVar(value=False)
        self.delete_var = tk.BooleanVar(value=False)
        self.stop_lines: list = []   # reason of the last stop, kept visible after re-check
        self.last_done = -1
        self.mode_var = tk.StringVar(value=self.settings.mode)
        self.status_var = tk.StringVar()
        self.current_var = tk.StringVar()
        self.banner_var = tk.StringVar()

        pad = {"padx": 8, "pady": 3}
        frm = ttk.Frame(root, padding=10)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)
        self.frm = frm

        ttk.Label(frm, text=t("zip_file")).grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.zip_var).grid(row=0, column=1, sticky="ew", **pad)
        self.btn_zip = ttk.Button(frm, text=t("browse"), command=self.pick_zip)
        self.btn_zip.grid(row=0, column=2, **pad)

        ttk.Label(frm, text=t("target")).grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.target_var).grid(row=1, column=1, sticky="ew", **pad)
        self.btn_target = ttk.Button(frm, text=t("browse"), command=self.pick_target)
        self.btn_target.grid(row=1, column=2, **pad)

        opts = ttk.Frame(frm)
        opts.grid(row=2, column=0, columnspan=3, sticky="w", **pad)
        ttk.Checkbutton(opts, text=t("overwrite"), variable=self.overwrite_var,
                        command=self.invalidate).pack(side="left", padx=(0, 16))
        ttk.Checkbutton(opts, text=t("delete_after"), variable=self.delete_var).pack(side="left")

        warn = tk.Label(frm, text=t("warning_box"), wraplength=860, justify="left",
                        bg="#fdecea", fg="#8a1c12", bd=1, relief="solid", padx=8, pady=6)
        warn.grid(row=3, column=0, columnspan=3, sticky="ew", **pad)

        # ---- three extraction modes (collapsible) -------------------------------
        mode_box = ttk.Frame(frm)
        mode_box.grid(row=4, column=0, columnspan=3, sticky="ew", **pad)
        mode_box.columnconfigure(0, weight=1)
        self.modes_open = False
        self.btn_modes = ttk.Button(mode_box, command=self.toggle_modes, style="Toolbutton")
        self.btn_modes.grid(row=0, column=0, sticky="w")
        modes = ttk.Frame(mode_box, padding=6, relief="groove", borderwidth=1)
        self.modes_frame = modes
        self.mode_radios = []
        for col, m in enumerate(("safe", "balanced", "performance")):
            modes.columnconfigure(col, weight=1, uniform="m")
            card = ttk.Frame(modes, padding=(6, 2))
            card.grid(row=0, column=col, sticky="nsew")
            rb = ttk.Radiobutton(card, text=t(f"mode_{m}"), value=m, variable=self.mode_var,
                                 command=self.mode_changed)
            rb.pack(anchor="w")
            self.mode_radios.append(rb)
            if m == "balanced":
                tk.Label(card, text=t("recommended"), fg="#1e7b34").pack(anchor="w")
            ttk.Label(card, text=t(f"mode_{m}_desc"), wraplength=270, justify="left").pack(anchor="w")
            ttk.Label(card, text=t(f"mode_{m}_info"), wraplength=270, justify="left",
                      foreground="#555").pack(anchor="w", pady=(2, 0))
        self.update_modes_header()

        tools = ttk.Frame(frm)
        tools.grid(row=5, column=0, columnspan=3, sticky="w", **pad)
        self.btn_check = ttk.Button(tools, text=t("check"), command=self.check)
        self.btn_check.pack(side="left", padx=(0, 6))
        self.btn_adv = ttk.Button(tools, text=t("advanced"), command=self.open_advanced)
        self.btn_adv.pack(side="left", padx=6)
        ttk.Button(tools, text=t("recovery_info"), command=self.show_recovery).pack(side="left", padx=6)

        self.report = tk.Text(frm, height=7, wrap="word", state="disabled", relief="solid", bd=1)
        self.report.grid(row=6, column=0, columnspan=3, sticky="nsew", **pad)
        frm.rowconfigure(6, weight=1)
        self.report.tag_configure("bad", foreground="#b3261e")
        self.report.tag_configure("good", foreground="#1e7b34")
        self.report.tag_configure("note", foreground="#6b5900")

        self.bar = ttk.Progressbar(frm, maximum=1000)
        self.bar.grid(row=8, column=0, columnspan=3, sticky="ew", **pad)
        ttk.Label(frm, textvariable=self.status_var).grid(row=9, column=0, columnspan=3,
                                                          sticky="w", padx=8)
        ttk.Label(frm, textvariable=self.current_var, foreground="#666").grid(
            row=10, column=0, columnspan=3, sticky="w", padx=8)

        # ---- hardware monitor ---------------------------------------------------
        self.mon = ttk.LabelFrame(frm, text=t("monitor"), padding=6)
        self.mon_vals = {}
        self.mon_bars = {}
        items = ["m_speed", "m_data", "m_elapsed", "m_eta", "m_cpu", "m_ram", "m_disk",
                 "m_threads", "m_free"]
        for i, key in enumerate(items):
            r, c = divmod(i, 3)
            cell = ttk.Frame(self.mon)
            cell.grid(row=r, column=c, sticky="ew", padx=6, pady=2)
            self.mon.columnconfigure(c, weight=1, uniform="mon")
            ttk.Label(cell, text=t(key), foreground="#555").pack(anchor="w")
            v = tk.StringVar(value="–")
            ttk.Label(cell, textvariable=v, font=("Segoe UI" if os.name == "nt" else "TkDefaultFont", 10, "bold")).pack(anchor="w")
            self.mon_vals[key] = v
            if key in ("m_cpu", "m_ram"):
                b = ttk.Progressbar(cell, maximum=100, length=180)
                b.pack(anchor="w", fill="x")
                self.mon_bars[key] = b
        self.low_space_lbl = tk.Label(self.mon, text="", fg="#b3261e")
        self.low_space_lbl.grid(row=3, column=0, columnspan=3, sticky="w")
        self.apply_monitor_visibility()

        bottom = ttk.Frame(frm)
        bottom.grid(row=12, column=0, columnspan=3, sticky="ew", **pad)
        bottom.columnconfigure(0, weight=1)
        self.banner = tk.Label(bottom, textvariable=self.banner_var, fg="#0b57d0", anchor="w")
        self.banner.grid(row=0, column=0, sticky="w")
        self.btn_banner = ttk.Button(bottom, text=t("auto_resume_cancel"), command=self.cancel_retry)
        self.btn_start = ttk.Button(bottom, text=t("start"), command=self.start)
        self.btn_start.grid(row=0, column=2, padx=4)
        self.btn_pause = ttk.Button(bottom, text=t("pause"), command=self.pause, state="disabled")
        self.btn_pause.grid(row=0, column=3, padx=4)

        self.zip_var.trace_add("write", lambda *_: self.invalidate())
        self.target_var.trace_add("write", lambda *_: self.invalidate())
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.update_buttons()
        root.after(100, self.poll)
        root.after(1000, self.idle_monitor)
        if open_path:  # started from the Explorer right-click menu
            root.after(300, lambda: self.open_from_shell(open_path))
        else:
            root.after(600, lambda: self.offer_pending(resume_pending))

    def open_from_shell(self, path: str):
        self.set_zip(os.path.normpath(os.path.abspath(path)))
        self.check()

    # ---------------------------------------------------------------- helpers
    def busy(self) -> bool:
        return self.worker is not None and self.worker.is_alive()

    def invalidate(self):
        self.plan = None
        self.update_buttons()

    def update_buttons(self):
        busy = self.busy()
        can_start = not busy and self.plan is not None and self.plan.ok
        self.btn_start.configure(state="normal" if can_start else "disabled",
                                 text=t("resume") if self.plan and self.plan.resuming else t("start"))
        for b in (self.btn_check, self.btn_zip, self.btn_target, self.btn_adv, *self.mode_radios):
            b.configure(state="disabled" if busy else "normal")
        self.btn_pause.configure(state="normal" if busy and self.running else "disabled")

    def write_report(self, lines):
        self.report.configure(state="normal")
        self.report.delete("1.0", "end")
        for text, tag in lines:
            self.report.insert("end", text + "\n", tag)
        self.report.configure(state="disabled")

    def apply_monitor_visibility(self):
        if self.settings.show_monitor:
            self.mon.grid(row=11, column=0, columnspan=3, sticky="ew", padx=8, pady=3)
        else:
            self.mon.grid_remove()

    def update_modes_header(self):
        arrow = "▾" if self.modes_open else "▸"
        self.btn_modes.configure(text=f"{arrow} " + t("modes_header", mode=t(f"mode_{self.mode_var.get()}")))

    def toggle_modes(self):
        self.modes_open = not self.modes_open
        if self.modes_open:
            self.modes_frame.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        else:
            self.modes_frame.grid_remove()
        self.update_modes_header()

    def mode_changed(self):
        """Switch preset values; keep the user's non-preset choices (temp dir, resume, ...)."""
        new = st.for_mode(self.mode_var.get())
        for f in st.fields(st.Settings):
            if f.name not in st.PRESETS[new.mode] and f.name != "mode":
                setattr(new, f.name, getattr(self.settings, f.name))
        self.settings = st.validate(new)[0]
        st.save(self.settings)
        self.update_modes_header()
        self.invalidate()

    def pick_zip(self):
        f = filedialog.askopenfilename(filetypes=[(t("zip_types"), "*.zip *.zip.001"), ("*", "*.*")])
        if not f:
            return
        self.set_zip(os.path.normpath(f))
        self.check()

    def set_zip(self, f: str, target: str | None = None):
        from . import source
        f = source.first_part(f)          # any part of a split ZIP -> its first part
        self.zip_var.set(f)
        try:
            j = journal.load(f)
        except journal.JournalError:
            j = None
        if target:
            self.target_var.set(target)
        elif j:
            self.target_var.set(j["target"])
        elif not self.target_var.get():
            base = source.split_base(f)
            self.target_var.set(os.path.splitext(base[0] if base else f)[0])

    def pick_target(self):
        d = filedialog.askdirectory(mustexist=False)
        if d:
            self.target_var.set(os.path.normpath(d))

    # ---------------------------------------------------------------- dialogs
    def open_advanced(self):
        AdvancedDialog(self)

    def show_recovery(self):
        z = self.zip_var.get().strip()
        if not z:
            messagebox.showinfo(t("app_title"), t("choose_first"))
            return
        d = journal.describe(z)
        if not d["exists"]:
            text = t("no_journal")
        elif not d["valid"]:
            text = t("journal_invalid", error=d["error"])
        else:
            text = t("journal_view", path=d["path"], target=d.get("target"), done=d.get("done"),
                     entries=d.get("entries", "?"), last=d.get("last_entry", "–"),
                     mode=d.get("mode", "–"), updated=d.get("updated", "–"),
                     format=d.get("format"))
        messagebox.showinfo(t("recovery_info").rstrip(" …"), text)

    # ---------------------------------------------------------------- actions
    def _inputs(self):
        z, tg = self.zip_var.get().strip(), self.target_var.get().strip()
        if not z or not tg:
            messagebox.showinfo(t("app_title"), t("choose_first"))
            return None
        return z, tg

    def check(self):
        inp = self._inputs()
        if not inp or self.busy():
            return
        self.write_report([("…", None)])
        self._spawn(self._check_worker, *inp, self.overwrite_var.get(), self.settings)

    def _check_worker(self, z, tg, overwrite, s):
        try:
            self.q.put(("plan", planmod.analyze(z, tg, overwrite=overwrite, settings=s)))
        except Exception as e:  # never let the GUI die silently
            self.q.put(("error", t("unexpected", error=repr(e))))

    def start(self):
        if not self.plan or not self.plan.ok or self.busy():
            return
        # a resumed job was already confirmed when it was first started
        if not self.plan.resuming and not messagebox.askyesno(
                t("app_title"), t("really_start", name=self.plan.archive),
                icon="warning", default="no"):
            return
        self.io_retries = 0
        self.launch(self.plan.archive, self.plan.target, self.overwrite_var.get(),
                    self.delete_var.get())

    def launch(self, z, tg, overwrite, delete):
        self.cancel_retry()
        self.cancel.clear()
        self.stop_lines = []
        self.running = True
        self.last_job = (z, tg, overwrite, delete)
        self._spawn(self._run_worker, z, tg, overwrite, delete, self.settings)

    def _run_worker(self, z, tg, overwrite, delete, s):
        try:
            p = planmod.analyze(z, tg, overwrite=overwrite, settings=s)  # re-check right before starting
            if not p.ok:
                self.q.put(("plan", p))
                return
            r = engine.run(p, lambda pr: self.q.put(("progress", pr)), self.cancel,
                           delete_archive=delete, settings=s)
            self.q.put(("done", r))
        except engine.RunStopped as e:
            self.q.put(("stopped", e))
        except Exception as e:
            self.q.put(("error", t("unexpected", error=repr(e))))

    def pause(self):
        self.cancel.set()
        self.btn_pause.configure(state="disabled")

    def _spawn(self, fn, *args):
        self.worker = threading.Thread(target=fn, args=args, daemon=False)
        self.worker.start()
        self.update_buttons()

    def on_close(self):
        self.cancel_retry()
        if self.busy() and self.running:
            self.closing = True
            self.pause()
            return  # closes when the worker has stopped cleanly
        self.root.destroy()

    # ------------------------------------------------- automatic resume/retry
    def offer_pending(self, forced: bool):
        if self.busy():
            return
        pend = jobs.pending()
        if not pend:
            return
        job = pend[0]
        self.set_zip(job["archive"], job["target"])
        if self.settings.auto_resume or forced:
            self.launch(job["archive"], job["target"], False, False)  # resume at once, no countdown
        elif messagebox.askyesno(t("app_title"), t("resume_found", name=job["archive"])):
            self.launch(job["archive"], job["target"], False, False)

    def countdown(self, sec, name, action, kind):
        if sec <= 0:
            self.banner_var.set("")
            self.btn_banner.grid_remove()
            self.retry_job = None
            action()
            return
        self.banner_var.set(t("auto_resume_countdown", name=os.path.basename(name), sec=sec)
                            if kind == "resume" else t("auto_retry_wait", sec=sec))
        self.btn_banner.grid(row=0, column=1, padx=4)
        self.retry_job = self.root.after(1000, lambda: self.countdown(sec - 1, name, action, kind))

    def cancel_retry(self):
        if self.retry_job:
            self.root.after_cancel(self.retry_job)
            self.retry_job = None
        self.banner_var.set("")
        self.btn_banner.grid_remove()

    def maybe_retry(self, e: engine.RunStopped):
        if not (self.settings.auto_resume and self.last_job and e.key in RETRYABLE
                and e.resumable and not self.closing):
            return
        if e.key != "out_of_space":
            self.io_retries += 1
            if self.io_retries > MAX_IO_RETRIES:
                return
        z, tg, ow, dl = self.last_job

        def retry():
            if e.key == "out_of_space":
                need = int(e.params.get("need", 0))
                try:
                    if winfs.free_bytes(tg) < need:
                        self.countdown(RETRY_SECONDS, z, retry, "retry")  # keep waiting for space
                        return
                except OSError:
                    pass
            self.launch(z, tg, ow, dl)
        self.countdown(RETRY_SECONDS, z, retry, "retry")

    # ------------------------------------------------------------- queue poll
    def poll(self):
        try:
            while True:
                item = self.q.get_nowait()
                kind = item[0]
                if kind == "plan":
                    self.show_plan(item[1])
                elif kind == "progress":
                    self.show_progress(item[1])
                elif kind == "done":
                    r = item[1]
                    self.running = False
                    self.bar["value"] = 1000
                    lines = [(t("done_msg", entries=r.entries, total=r.bytes), "good"),
                             (t("done_deleted") if r.archive_deleted else t("done_keep"), None)]
                    if r.damaged_report:
                        lines.append((t("done_damaged", count=len(r.damaged) or "?",
                                        path=r.damaged_report), "note"))
                    self.write_report(lines)
                    self.plan = None
                elif kind == "stopped":
                    e = item[1]
                    self.running = False
                    self.stop_lines = [(t("last_stop"), "bad"),
                                       ("  " + msg((e.key, e.params)),
                                        "note" if e.key == "cancelled" else "bad")]
                    self.write_report(self.stop_lines)
                    self.plan = None
                    if not self.closing:
                        self.root.after(200, self.check)
                        self.maybe_retry(e)
                elif kind == "error":
                    self.running = False
                    self.write_report([(item[1], "bad")])
        except queue.Empty:
            pass
        if self.closing and not self.busy():
            self.root.destroy()
            return
        self.update_buttons()
        self.root.after(100, self.poll)

    def show_plan(self, p):
        self.plan = p
        lines = [(t("summary", entries=len(p.entries), total=p.total_bytes, size=p.archive_size,
                    free=p.free, need=p.peak_need + p.reserve), None)]
        if p.ok:
            lines.append((t("fits"), "good"))
        else:
            lines.append((t("not_ok"), "bad"))
            lines += [("  • " + msg(x), "bad") for x in p.problems]
        if p.warnings:
            lines.append((t("warnings"), "note"))
            lines += [("  • " + msg(x), "note") for x in p.warnings]
        lines.append((t("vss_note"), None))
        self.write_report(self.stop_lines + lines)  # the stop reason stays visible
        if p.total_bytes:
            self.bar["value"] = 1000 * (p.total_bytes - p.remaining_bytes) / p.total_bytes

    def show_progress(self, pr: engine.Progress):
        if pr.entries_done > self.last_done >= 0:
            self.io_retries = 0   # progress was made: a later hiccup gets fresh retries
        self.last_done = pr.entries_done
        if pr.bytes_total:
            self.bar["value"] = 1000 * pr.bytes_done / pr.bytes_total
        self.status_var.set(t("status_running", done=pr.entries_done, ntotal=pr.entries_total,
                              bytes=fmt_bytes(pr.bytes_done), btotal=fmt_bytes(pr.bytes_total),
                              speed=fmt_bytes(int(pr.speed)), avg=fmt_bytes(int(pr.avg_speed)),
                              alloc=fmt_bytes(pr.archive_allocated), free=fmt_bytes(pr.free)))
        self.current_var.set(pr.current)
        v = self.mon_vals
        v["m_speed"].set(t("speed_avg", speed=fmt_bytes(int(pr.speed)), avg=fmt_bytes(int(pr.avg_speed))))
        v["m_data"].set(f"{fmt_bytes(pr.bytes_done)} / {fmt_bytes(pr.bytes_total)}")
        v["m_elapsed"].set(fmt_duration(pr.elapsed))
        v["m_eta"].set(fmt_duration(pr.eta))
        v["m_threads"].set(f"{pr.active} / {pr.threads}")
        v["m_free"].set(fmt_bytes(pr.free))
        if pr.stats:
            self.show_stats(pr.stats)
        self.low_space_lbl.configure(text=t("low_space_warn") if pr.low_space else "")

    def show_stats(self, s: dict):
        v = self.mon_vals
        v["m_cpu"].set(f"{s['proc_cpu']:.0f} % / {s['sys_cpu']:.0f} %")
        v["m_ram"].set(f"{fmt_bytes(s['proc_ram'])} / {s['sys_ram_load']} %")
        v["m_disk"].set(f"{fmt_bytes(int(s['read_bps']))}/s / {fmt_bytes(int(s['write_bps']))}/s")
        self.mon_bars["m_cpu"]["value"] = s["sys_cpu"]
        self.mon_bars["m_ram"]["value"] = s["sys_ram_load"]

    def idle_monitor(self):
        if not self.running and self.settings.show_monitor:
            try:
                self.show_stats(self.sampler.sample())
            except Exception:
                pass
        if not self.closing:
            self.root.after(1000, self.idle_monitor)


class AdvancedDialog:
    """Every field maps 1:1 to a Settings attribute read by the engine."""

    LAYOUT = {
        "tab_cpu": [("auto_threads", "bool"), ("max_threads", "int"), ("max_cpu_percent", "int"),
                    ("background_mode", "bool"), ("priority", "choice")],
        "tab_ram": [("max_ram_mb", "int"), ("ram_threshold_percent", "int"),
                    ("auto_memory", "bool"), ("auto_ram_disk", "bool")],
        "tab_storage": [("temp_dir", "dir"), ("max_temp_gb", "float"), ("max_write_mb_s", "int"),
                        ("flush_interval_mb", "int"), ("low_space_warn_gb", "float"),
                        ("delete_parts", "bool")],
        "tab_journal": [("sync_interval_mb", "int"), ("verify_written", "bool"),
                        ("auto_resume", "bool"), ("resume_after_reboot", "bool"),
                        ("keep_damaged", "bool")],
        "tab_other": [("auto_optimize", "bool"), ("show_monitor", "bool"), ("language", "choice"),
                      ("explorer_menu", "bool")],
    }

    def __init__(self, app: App):
        self.app = app
        self.win = w = tk.Toplevel(app.root)
        w.title(t("advanced_title"))
        w.transient(app.root)
        w.grab_set()
        w.minsize(640, 460)
        self.vars: dict = {}
        ttk.Label(w, text=t("custom_note"), wraplength=600, foreground="#555").pack(
            anchor="w", padx=10, pady=(10, 4))
        nb = ttk.Notebook(w)
        nb.pack(fill="both", expand=True, padx=10, pady=4)
        for tab, items in self.LAYOUT.items():
            page = ttk.Frame(nb, padding=8)
            nb.add(page, text=t(tab))
            page.columnconfigure(1, weight=1)
            for r, (name, kind) in enumerate(items):
                self._row(page, r, name, kind)
            if tab == "tab_ram":
                info = (f"RAM: {fmt_bytes(sysinfo.total_ram())} · "
                        f"{fmt_bytes(sysinfo.available_ram())} frei/free · "
                        f"CPU: {os.cpu_count()} Threads")
                ttk.Label(page, text=info, foreground="#1e7b34").grid(
                    row=len(items) * 2, column=0, columnspan=3, sticky="w", pady=6)
        btns = ttk.Frame(w)
        btns.pack(fill="x", padx=10, pady=10)
        ttk.Button(btns, text=t("defaults"), command=self.defaults).pack(side="left")
        ttk.Button(btns, text=t("cancel_btn"), command=w.destroy).pack(side="right", padx=4)
        ttk.Button(btns, text=t("save"), command=self.save).pack(side="right", padx=4)
        self.load(app.settings)

    def _row(self, page, r, name, kind):
        ttk.Label(page, text=t(f"s_{name}")).grid(row=r * 2, column=0, sticky="w", pady=(6, 0))
        if kind == "bool":
            v = tk.BooleanVar()
            ttk.Checkbutton(page, variable=v).grid(row=r * 2, column=1, sticky="w", pady=(6, 0))
        elif kind == "choice":
            v = tk.StringVar()
            ttk.Combobox(page, textvariable=v, values=st.CHOICES[name], state="readonly",
                         width=16).grid(row=r * 2, column=1, sticky="w", pady=(6, 0))
        elif kind == "dir":
            v = tk.StringVar()
            fr = ttk.Frame(page)
            fr.grid(row=r * 2, column=1, sticky="ew", pady=(6, 0))
            ttk.Entry(fr, textvariable=v).pack(side="left", fill="x", expand=True)
            ttk.Button(fr, text=t("browse"), command=lambda: self._browse(v)).pack(side="left", padx=4)
        else:
            v = tk.StringVar()
            lo, hi = st.LIMITS[name]
            ttk.Spinbox(page, textvariable=v, from_=lo, to=hi, width=10,
                        increment=0.25 if kind == "float" else 1).grid(
                row=r * 2, column=1, sticky="w", pady=(6, 0))
        ttk.Label(page, text=t(f"d_{name}"), wraplength=580, foreground="#666",
                  justify="left").grid(row=r * 2 + 1, column=0, columnspan=3, sticky="w")
        self.vars[name] = (v, kind)

    def _browse(self, v):
        d = filedialog.askdirectory(parent=self.win)
        if d:
            v.set(os.path.normpath(d))

    def load(self, s: st.Settings):
        for name, (v, kind) in self.vars.items():
            v.set(getattr(s, name))

    def defaults(self):
        self.load(st.for_mode(self.app.settings.mode))

    def save(self):
        s = st.for_mode(self.app.settings.mode)
        for name, (v, kind) in self.vars.items():
            raw = v.get()
            try:
                if kind == "int":
                    raw = int(float(raw))
                elif kind == "float":
                    raw = float(str(raw).replace(",", "."))
            except ValueError:
                raw = getattr(s, name)
            setattr(s, name, raw)
        s, fixed = st.validate(s)
        self.app.settings = s
        st.save(s)
        if not s.resume_after_reboot:
            jobs.set_autostart(False)
        elif jobs.pending():
            jobs.set_autostart(True)
        apply_explorer_menu(s.explorer_menu)
        self.app.apply_monitor_visibility()
        self.app.invalidate()
        names = [t(f"s_{f}") for f in fixed if f"s_{f}" in T]
        if names:
            messagebox.showinfo(t("advanced_title"), t("clamped") + "\n• " + "\n• ".join(names),
                                parent=self.win)
        self.win.destroy()


def apply_explorer_menu(on: bool) -> None:
    """Add/remove the right-click entry (HKCU only). Skipped in tests."""
    if os.environ.get("INPLACE_UNPACK_NO_JOBS") == "1":
        return
    from . import shellmenu
    try:
        if on:
            shellmenu.install(t("menu_label"))
        elif shellmenu.installed():
            shellmenu.uninstall()
    except OSError:
        pass


def set_window_icon(root: tk.Tk) -> None:
    """Window/taskbar icon: bundled by PyInstaller (sys._MEIPASS) or from the repo."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ico = os.path.join(base, "assets", "icon.ico")
    if os.name != "nt":
        png = os.path.join(base, "assets", "icon.png")
        try:
            root._icon_img = tk.PhotoImage(file=png)
            root.iconphoto(True, root._icon_img)
        except tk.TclError:
            pass
        return
    if os.path.exists(ico):
        try:
            root.iconbitmap(default=ico)  # also used by dialogs
        except tk.TclError:
            pass


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk(className="inplace-unpack")
    try:
        ttk.Style().theme_use("vista" if os.name == "nt" else "clam")
    except tk.TclError:
        pass
    set_window_icon(root)
    from . import i18n
    i18n.set_lang(st.load().language)
    files = [a for a in argv if not a.startswith("--")]
    App(root, resume_pending="--resume-pending" in argv, open_path=files[0] if files else None)
    root.mainloop()


if __name__ == "__main__":
    main()
