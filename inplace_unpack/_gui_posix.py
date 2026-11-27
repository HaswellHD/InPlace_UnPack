"""Tk GUI with native Linux integration (KDE/GTK file dialogs, Dark/Light theme,
live DE/EN switching, URI paste cleanup, and responsive layout).

The extraction runs in a worker thread with its own (lowered) priority; the
window thread keeps normal priority, so the UI stays responsive.
"""
from __future__ import annotations

import os
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
import urllib.parse
from tkinter import filedialog, messagebox, ttk

from . import __version__, engine, i18n, jobs, journal, plan as planmod, settings as st, sysinfo, winfs
from .i18n import T, fmt_bytes, fmt_duration, msg, t

RETRY_SECONDS = 30
MAX_IO_RETRIES = 5
RETRYABLE = {"out_of_space", "io_error", "permission", "out_of_memory"}

DARK_PALETTE = {
    "bg": "#1e2229",
    "surface": "#262b34",
    "field": "#16191f",
    "border": "#38404e",
    "fg": "#e8ecf2",
    "muted": "#9aa4b5",
    "btn": "#2f3643",
    "btn_hover": "#3a4353",
    "btn_press": "#232833",
    "accent": "#2563eb",
    "accent_hover": "#3b82f6",
    "accent_fg": "#ffffff",
    "disabled_bg": "#252a33",
    "disabled_fg": "#646e80",
    "good": "#4ade80",
    "bad": "#f87171",
    "note": "#fbbf24",
    "banner": "#60a5fa",
    "warn_bg": "#361f22",
    "warn_fg": "#fca5a5",
    "warn_bd": "#7f3339",
    "trough": "#16191f",
    "bar": "#3b82f6",
}

LIGHT_PALETTE = {
    "bg": "#f3f5f8",
    "surface": "#ffffff",
    "field": "#ffffff",
    "border": "#cbd5e1",
    "fg": "#1e293b",
    "muted": "#5b677a",
    "btn": "#e7ecf3",
    "btn_hover": "#dae2ee",
    "btn_press": "#cdd7e6",
    "accent": "#2563eb",
    "accent_hover": "#1d4ed8",
    "accent_fg": "#ffffff",
    "disabled_bg": "#edf0f5",
    "disabled_fg": "#94a3b8",
    "good": "#15803d",
    "bad": "#b91c1c",
    "note": "#92400e",
    "banner": "#1d4ed8",
    "warn_bg": "#fef2f2",
    "warn_fg": "#991b1b",
    "warn_bd": "#f8b4b4",
    "trough": "#e2e8f0",
    "bar": "#2563eb",
}


def _detect_dark_mode() -> bool:
    if os.name == "nt":
        return False
    gtk_theme = os.environ.get("GTK_THEME", "").lower()
    if "dark" in gtk_theme:
        return True
    kde_cfg = os.path.expanduser("~/.config/kdeglobals")
    if os.path.exists(kde_cfg):
        try:
            in_win = False
            with open(kde_cfg, encoding="utf-8", errors="replace") as f:
                for line in f:
                    s = line.strip()
                    if s.startswith("["):
                        in_win = s == "[Colors:Window]"
                    elif in_win and s.startswith("BackgroundNormal="):
                        rgb = [int(x) for x in s.split("=", 1)[1].split(",")[:3]]
                        if len(rgb) == 3:
                            lum = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
                            return lum < 128
        except (OSError, ValueError):
            pass
    if shutil.which("gsettings"):
        try:
            r = subprocess.run(
                ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                capture_output=True, text=True, timeout=0.6,
            )
            if "prefer-dark" in r.stdout.lower():
                return True
        except Exception:
            pass
    return False


def _clean_path(raw: str) -> str:
    s = raw.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        s = s[1:-1].strip()
    if s.startswith("file://"):
        parsed = urllib.parse.urlparse(s.splitlines()[0].strip())
        if parsed.path:
            s = urllib.parse.unquote(parsed.path)
    return s


def _ellipsize_middle(s: str, max_len: int = 115) -> str:
    if len(s) <= max_len:
        return s
    keep = max_len - 1
    left = keep // 2
    right = keep - left
    return s[:left] + "…" + s[-right:]


def _init_tk_filedialog_prefs(root: tk.Tk) -> None:
    if os.name == "nt":
        return
    try:
        root.tk.call("tk_getOpenFile", "-foobar")
    except tk.TclError:
        pass
    for var, val in (("::tk::dialog::file::showHiddenBtn", "1"),
                     ("::tk::dialog::file::showHiddenVar", "0")):
        try:
            root.tk.call("set", var, val)
        except tk.TclError:
            pass


def _initial_dir_for(path_str: str) -> str:
    p = _clean_path(path_str)
    if p:
        d = p if os.path.isdir(p) else os.path.dirname(p)
        if d and os.path.isdir(d):
            return d
    dl = os.path.expanduser("~/Downloads")
    return dl if os.path.isdir(dl) else os.path.expanduser("~")


def _native_open_zip(parent: tk.Misc, title: str, initial_dir: str) -> str | None:
    if os.name != "nt" and os.environ.get("INPLACE_UNPACK_NO_JOBS") != "1":
        desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
        kdialog = shutil.which("kdialog")
        zenity = shutil.which("zenity")
        if kdialog and ("KDE" in desktop or not zenity):
            cmd = [kdialog, "--title", title, "--getopenfilename", initial_dir,
                   f"{t('zip_types')} (*.zip *.ZIP *.001)|All files (*)"]
            try:
                wid = parent.winfo_id()
                if wid:
                    cmd[1:1] = ["--attach", str(wid)]
            except Exception:
                pass
            try:
                r = subprocess.run(cmd, capture_output=True, text=True)
                return r.stdout.strip() if r.returncode == 0 else ""
            except OSError:
                pass
        if zenity:
            cmd = [zenity, "--file-selection", "--title", title,
                   f"--filename={initial_dir.rstrip('/')}/",
                   "--file-filter=ZIP (*.zip *.ZIP *.001) | *.zip *.ZIP *.001",
                   "--file-filter=* | *"]
            try:
                r = subprocess.run(cmd, capture_output=True, text=True)
                return r.stdout.strip() if r.returncode == 0 else ""
            except OSError:
                pass
    return filedialog.askopenfilename(
        parent=parent,
        title=title,
        initialdir=initial_dir,
        filetypes=[(t("zip_types"), "*.zip *.ZIP *.001"), ("*", "*.*")],
    )


def _native_pick_dir(parent: tk.Misc, title: str, initial_dir: str) -> str | None:
    if os.name != "nt" and os.environ.get("INPLACE_UNPACK_NO_JOBS") != "1":
        desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
        kdialog = shutil.which("kdialog")
        zenity = shutil.which("zenity")
        if kdialog and ("KDE" in desktop or not zenity):
            cmd = [kdialog, "--title", title, "--getexistingdirectory", initial_dir]
            try:
                wid = parent.winfo_id()
                if wid:
                    cmd[1:1] = ["--attach", str(wid)]
            except Exception:
                pass
            try:
                r = subprocess.run(cmd, capture_output=True, text=True)
                return r.stdout.strip() if r.returncode == 0 else ""
            except OSError:
                pass
        if zenity:
            cmd = [zenity, "--file-selection", "--directory", "--title", title,
                   f"--filename={initial_dir.rstrip('/')}/"]
            try:
                r = subprocess.run(cmd, capture_output=True, text=True)
                return r.stdout.strip() if r.returncode == 0 else ""
            except OSError:
                pass
    return filedialog.askdirectory(parent=parent, title=title, initialdir=initial_dir, mustexist=False)


def _open_folder_in_fm(path: str) -> None:
    d = _clean_path(path)
    if not d:
        return
    if not os.path.isdir(d):
        parent = os.path.dirname(os.path.abspath(d))
        if os.path.isdir(parent):
            d = parent
        else:
            return
    if os.name == "nt":
        try:
            os.startfile(d)  # type: ignore[attr-defined]
        except OSError:
            pass
    else:
        opener = shutil.which("xdg-open")
        if opener:
            try:
                subprocess.Popen([opener, d], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                pass


def apply_palette(root: tk.Tk, dark: bool) -> dict[str, str]:
    pal = DARK_PALETTE if dark else LIGHT_PALETTE
    style = ttk.Style(root)
    if os.name != "nt":
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
    elif not dark:
        try:
            style.theme_use("vista")
            root.configure(bg=pal["bg"])
            return pal
        except tk.TclError:
            pass

    root.configure(bg=pal["bg"])
    style.configure(".", background=pal["bg"], foreground=pal["fg"],
                    fieldbackground=pal["field"], bordercolor=pal["border"],
                    lightcolor=pal["surface"], darkcolor=pal["border"])
    style.configure("TFrame", background=pal["bg"])
    style.configure("Card.TFrame", background=pal["surface"], relief="solid", borderwidth=1)
    style.configure("CardInner.TFrame", background=pal["surface"])
    style.configure("TLabel", background=pal["bg"], foreground=pal["fg"])
    style.configure("Muted.TLabel", background=pal["bg"], foreground=pal["muted"])
    style.configure("Card.TLabel", background=pal["surface"], foreground=pal["fg"])
    style.configure("CardMuted.TLabel", background=pal["surface"], foreground=pal["muted"])
    style.configure("CardGood.TLabel", background=pal["surface"], foreground=pal["good"])
    style.configure("Bad.TLabel", background=pal["surface"], foreground=pal["bad"])
    style.configure("Banner.TLabel", background=pal["bg"], foreground=pal["banner"])
    style.configure("Title.TLabel", background=pal["bg"], foreground=pal["fg"],
                    font=("Segoe UI" if os.name == "nt" else "TkDefaultFont", 12, "bold"))

    style.configure("TLabelframe", background=pal["surface"], bordercolor=pal["border"],
                    relief="solid", borderwidth=1)
    style.configure("TLabelframe.Label", background=pal["bg"], foreground=pal["fg"],
                    font=("Segoe UI" if os.name == "nt" else "TkDefaultFont", 10, "bold"))

    style.configure("TButton", background=pal["btn"], foreground=pal["fg"],
                    bordercolor=pal["border"], focusthickness=1, focuscolor=pal["accent"],
                    padding=(10, 5))
    style.map("TButton",
              background=[("disabled", pal["disabled_bg"]), ("pressed", pal["btn_press"]),
                          ("active", pal["btn_hover"])],
              foreground=[("disabled", pal["disabled_fg"])])

    style.configure("Small.TButton", background=pal["btn"], foreground=pal["fg"],
                    bordercolor=pal["border"], padding=(8, 3))
    style.map("Small.TButton",
              background=[("active", pal["btn_hover"]), ("pressed", pal["btn_press"])])

    style.configure("Accent.TButton", background=pal["accent"], foreground=pal["accent_fg"],
                    bordercolor=pal["accent"], padding=(14, 6),
                    font=("Segoe UI" if os.name == "nt" else "TkDefaultFont", 10, "bold"))
    style.map("Accent.TButton",
              background=[("disabled", pal["disabled_bg"]), ("pressed", pal["accent_hover"]),
                          ("active", pal["accent_hover"])],
              foreground=[("disabled", pal["disabled_fg"]), ("!disabled", pal["accent_fg"])])

    style.configure("Toolbutton", background=pal["btn"], foreground=pal["fg"], padding=(10, 5))
    style.map("Toolbutton",
              background=[("active", pal["btn_hover"]), ("selected", pal["btn_press"])])

    style.configure("TCheckbutton", background=pal["bg"], foreground=pal["fg"],
                    indicatorbackground=pal["field"], indicatorforeground=pal["accent"])
    style.map("TCheckbutton",
              background=[("active", pal["bg"])],
              indicatorbackground=[("selected", pal["accent"]), ("!selected", pal["field"])])

    style.configure("Card.TRadiobutton", background=pal["surface"], foreground=pal["fg"],
                    indicatorbackground=pal["field"])
    style.map("Card.TRadiobutton",
              background=[("active", pal["surface"])],
              foreground=[("disabled", pal["disabled_fg"])],
              indicatorbackground=[("selected", pal["accent"]), ("!selected", pal["field"])])

    style.configure("TEntry", fieldbackground=pal["field"], foreground=pal["fg"],
                    insertcolor=pal["fg"], bordercolor=pal["border"], padding=(6, 5))
    style.map("TEntry", bordercolor=[("focus", pal["accent"])])

    style.configure("TSpinbox", fieldbackground=pal["field"], foreground=pal["fg"],
                    insertcolor=pal["fg"], arrowcolor=pal["fg"], bordercolor=pal["border"], padding=4)
    style.configure("TCombobox", fieldbackground=pal["field"], foreground=pal["fg"],
                    background=pal["btn"], arrowcolor=pal["fg"], bordercolor=pal["border"], padding=4)
    style.map("TCombobox",
              fieldbackground=[("readonly", pal["field"])],
              foreground=[("readonly", pal["fg"])],
              selectbackground=[("readonly", pal["field"])],
              selectforeground=[("readonly", pal["fg"])])

    style.configure("TNotebook", background=pal["bg"], bordercolor=pal["border"], tabmargins=(2, 4, 2, 0))
    style.configure("TNotebook.Tab", background=pal["btn"], foreground=pal["muted"],
                    padding=(12, 6), bordercolor=pal["border"])
    style.map("TNotebook.Tab",
              background=[("selected", pal["surface"]), ("active", pal["btn_hover"])],
              foreground=[("selected", pal["fg"]), ("active", pal["fg"])])

    style.configure("Horizontal.TProgressbar", troughcolor=pal["trough"], background=pal["bar"],
                    bordercolor=pal["border"], lightcolor=pal["bar"], darkcolor=pal["bar"],
                    thickness=10)
    style.configure("Vertical.TScrollbar", background=pal["btn"], troughcolor=pal["field"],
                    bordercolor=pal["border"], arrowcolor=pal["muted"])
    return pal


class App:
    def __init__(self, root: tk.Tk, resume_pending: bool = False, open_path: str | None = None):
        self.root = root
        self.settings = st.load()
        i18n.set_lang(self.settings.language)
        self.dark = _detect_dark_mode()
        self.pal = apply_palette(root, self.dark)
        _init_tk_filedialog_prefs(root)

        root.title(f"{t('app_title')} {__version__}")
        root.minsize(900, 740)
        self.q: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.cancel = threading.Event()
        self.plan = None
        self.closing = False
        self.running = False
        self.sampler = sysinfo.Sampler()
        self.retry_job = None        # after() id of a pending retry/countdown
        self.io_retries = 0
        self.last_job = None         # (archive, target, overwrite, delete)
        self._auto_target = ""       # last auto-filled target folder

        self.zip_var = tk.StringVar()
        self.target_var = tk.StringVar()
        self.overwrite_var = tk.BooleanVar(value=False)
        self.delete_var = tk.BooleanVar(value=False)
        self.stop_lines: list = []   # reason of the last stop, kept visible after re-check
        self._last_report_lines: list = []
        self.last_done = -1
        self.mode_var = tk.StringVar(value=self.settings.mode)
        self.status_var = tk.StringVar()
        self.current_var = tk.StringVar()
        self.banner_var = tk.StringVar()

        pad = {"padx": 8, "pady": 4}
        frm = ttk.Frame(root, padding=(14, 12))
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)
        self.frm = frm

        # ---- top header bar (title + quick language & theme buttons) ------------
        hdr = ttk.Frame(frm)
        hdr.grid(row=0, column=0, columnspan=3, sticky="ew", padx=8, pady=(0, 6))
        hdr.columnconfigure(0, weight=1)
        self.lbl_title = ttk.Label(hdr, text=f"Inplace-Unpack  v{__version__}", style="Title.TLabel")
        self.lbl_title.grid(row=0, column=0, sticky="w")
        self.btn_lang = ttk.Button(
            hdr, text=i18n.LANG.upper(), width=4, style="Small.TButton", command=self.toggle_language
        )
        self.btn_lang.grid(row=0, column=1, padx=(4, 4))
        self.btn_theme = ttk.Button(
            hdr, text="☀" if self.dark else "☾", width=3, style="Small.TButton", command=self.toggle_theme
        )
        self.btn_theme.grid(row=0, column=2)

        # ---- inputs -------------------------------------------------------------
        self.lbl_zip = ttk.Label(frm, text=t("zip_file"))
        self.lbl_zip.grid(row=1, column=0, sticky="w", **pad)
        self.ent_zip = ttk.Entry(frm, textvariable=self.zip_var)
        self.ent_zip.grid(row=1, column=1, sticky="ew", **pad)
        self.btn_zip = ttk.Button(frm, text=t("browse"), command=self.pick_zip)
        self.btn_zip.grid(row=1, column=2, sticky="ew", **pad)

        self.lbl_target = ttk.Label(frm, text=t("target"))
        self.lbl_target.grid(row=2, column=0, sticky="w", **pad)
        self.ent_target = ttk.Entry(frm, textvariable=self.target_var)
        self.ent_target.grid(row=2, column=1, sticky="ew", **pad)
        tgt_btns = ttk.Frame(frm)
        tgt_btns.grid(row=2, column=2, sticky="ew", **pad)
        self.btn_target = ttk.Button(tgt_btns, text=t("browse"), command=self.pick_target)
        self.btn_target.pack(side="left")
        self.btn_open_dir = ttk.Button(
            tgt_btns, text="↗", width=3, command=lambda: _open_folder_in_fm(self.target_var.get())
        )
        self.btn_open_dir.pack(side="left", padx=(4, 0))

        opts = ttk.Frame(frm)
        opts.grid(row=3, column=0, columnspan=3, sticky="w", **pad)
        self.chk_overwrite = ttk.Checkbutton(opts, text=t("overwrite"), variable=self.overwrite_var,
                                             command=self.invalidate)
        self.chk_overwrite.pack(side="left", padx=(0, 18))
        self.chk_delete = ttk.Checkbutton(opts, text=t("delete_after"), variable=self.delete_var)
        self.chk_delete.pack(side="left")

        self.warn = tk.Label(frm, text=t("warning_box"), wraplength=840, justify="left",
                             bg=self.pal["warn_bg"], fg=self.pal["warn_fg"],
                             highlightbackground=self.pal["warn_bd"], highlightthickness=1,
                             bd=0, padx=10, pady=8)
        self.warn.grid(row=4, column=0, columnspan=3, sticky="ew", **pad)

        # ---- three extraction modes (collapsible) -------------------------------
        mode_box = ttk.Frame(frm)
        mode_box.grid(row=5, column=0, columnspan=3, sticky="ew", **pad)
        mode_box.columnconfigure(0, weight=1)
        self.modes_open = False
        self.btn_modes = ttk.Button(mode_box, command=self.toggle_modes, style="Toolbutton")
        self.btn_modes.grid(row=0, column=0, sticky="w")
        modes = ttk.Frame(mode_box, padding=8, style="Card.TFrame")
        self.modes_frame = modes
        self.mode_radios = []
        self.mode_desc_lbls = {}
        self.mode_info_lbls = {}
        self.lbl_rec = None
        for col, m in enumerate(("safe", "balanced", "performance")):
            modes.columnconfigure(col, weight=1, uniform="m")
            card = ttk.Frame(modes, padding=(8, 4), style="CardInner.TFrame")
            card.grid(row=0, column=col, sticky="nsew", padx=3)
            rb = ttk.Radiobutton(card, text=t(f"mode_{m}"), value=m, variable=self.mode_var,
                                 style="Card.TRadiobutton", command=self.mode_changed)
            rb.pack(anchor="w")
            self.mode_radios.append(rb)
            if m == "balanced":
                self.lbl_rec = ttk.Label(card, text=t("recommended"), style="CardGood.TLabel")
                self.lbl_rec.pack(anchor="w")
            dl = ttk.Label(card, text=t(f"mode_{m}_desc"), wraplength=265, justify="left",
                           style="Card.TLabel")
            dl.pack(anchor="w", pady=(2, 0))
            il = ttk.Label(card, text=t(f"mode_{m}_info"), wraplength=265, justify="left",
                           style="CardMuted.TLabel")
            il.pack(anchor="w", pady=(3, 0))
            self.mode_desc_lbls[m] = dl
            self.mode_info_lbls[m] = il
        self.update_modes_header()

        tools = ttk.Frame(frm)
        tools.grid(row=6, column=0, columnspan=3, sticky="w", **pad)
        self.btn_check = ttk.Button(tools, text=t("check"), command=self.check)
        self.btn_check.pack(side="left", padx=(0, 6))
        self.btn_adv = ttk.Button(tools, text=t("advanced"), command=self.open_advanced)
        self.btn_adv.pack(side="left", padx=6)
        self.btn_rec = ttk.Button(tools, text=t("recovery_info"), command=self.show_recovery)
        self.btn_rec.pack(side="left", padx=6)

        # ---- scrollable status report -------------------------------------------
        rep_wrap = ttk.Frame(frm)
        rep_wrap.grid(row=7, column=0, columnspan=3, sticky="nsew", **pad)
        rep_wrap.columnconfigure(0, weight=1)
        rep_wrap.rowconfigure(0, weight=1)
        frm.rowconfigure(7, weight=1)
        self.report = tk.Text(
            rep_wrap, height=7, wrap="word", state="disabled", bd=0,
            font="TkDefaultFont", padx=10, pady=8,
            bg=self.pal["field"], fg=self.pal["fg"],
            insertbackground=self.pal["fg"],
            highlightbackground=self.pal["border"], highlightthickness=1,
            spacing1=2, spacing3=2,
        )
        self.report.grid(row=0, column=0, sticky="nsew")
        rep_scroll = ttk.Scrollbar(rep_wrap, orient="vertical", command=self.report.yview)
        rep_scroll.grid(row=0, column=1, sticky="ns")
        self.report.configure(yscrollcommand=rep_scroll.set)
        self._configure_report_tags()

        self.bar = ttk.Progressbar(frm, maximum=1000, style="Horizontal.TProgressbar")
        self.bar.grid(row=8, column=0, columnspan=3, sticky="ew", **pad)
        ttk.Label(frm, textvariable=self.status_var, width=1, anchor="w").grid(
            row=9, column=0, columnspan=3, sticky="ew", padx=8
        )
        ttk.Label(frm, textvariable=self.current_var, style="Muted.TLabel", width=1, anchor="w").grid(
            row=10, column=0, columnspan=3, sticky="ew", padx=8
        )

        # ---- hardware monitor ---------------------------------------------------
        self.mon = ttk.LabelFrame(frm, text=t("monitor"), padding=8)
        self.mon_vals = {}
        self.mon_titles = {}
        self.mon_bars = {}
        items = ["m_speed", "m_data", "m_elapsed", "m_eta", "m_cpu", "m_ram", "m_disk",
                 "m_threads", "m_free"]
        val_font = ("Segoe UI" if os.name == "nt" else "TkDefaultFont", 10, "bold")
        for i, key in enumerate(items):
            r, c = divmod(i, 3)
            cell = ttk.Frame(self.mon, style="CardInner.TFrame")
            cell.grid(row=r, column=c, sticky="ew", padx=8, pady=3)
            self.mon.columnconfigure(c, weight=1, uniform="mon")
            tl = ttk.Label(cell, text=t(key), style="CardMuted.TLabel")
            tl.pack(anchor="w")
            self.mon_titles[key] = tl
            v = tk.StringVar(value="–")
            ttk.Label(cell, textvariable=v, font=val_font, style="Card.TLabel").pack(anchor="w")
            self.mon_vals[key] = v
            if key in ("m_cpu", "m_ram"):
                b = ttk.Progressbar(cell, maximum=100, length=180, style="Horizontal.TProgressbar")
                b.pack(anchor="w", fill="x", pady=(2, 0))
                self.mon_bars[key] = b
        self.low_space_lbl = ttk.Label(self.mon, text="", style="Bad.TLabel")
        self.low_space_lbl.grid(row=3, column=0, columnspan=3, sticky="w", padx=8)
        self.apply_monitor_visibility()

        bottom = ttk.Frame(frm)
        bottom.grid(row=12, column=0, columnspan=3, sticky="ew", padx=8, pady=(8, 2))
        bottom.columnconfigure(0, weight=1)
        self.banner = ttk.Label(bottom, textvariable=self.banner_var, style="Banner.TLabel", anchor="w")
        self.banner.grid(row=0, column=0, sticky="ew")
        self.btn_banner = ttk.Button(bottom, text=t("auto_resume_cancel"), command=self.cancel_retry)
        self.btn_start = ttk.Button(bottom, text=t("start"), style="Accent.TButton", command=self.start)
        self.btn_start.grid(row=0, column=2, padx=4)
        self.btn_pause = ttk.Button(bottom, text=t("pause"), command=self.pause, state="disabled")
        self.btn_pause.grid(row=0, column=3, padx=(4, 0))

        self.zip_var.trace_add("write", lambda *_: self.invalidate())
        self.target_var.trace_add("write", lambda *_: self.invalidate())
        self.ent_zip.bind("<FocusOut>", lambda *_: self._sanitize_var(self.zip_var))
        self.ent_target.bind("<FocusOut>", lambda *_: self._sanitize_var(self.target_var))
        frm.bind("<Configure>", self._on_resize)
        root.bind("<Control-o>", lambda *_: self.pick_zip())
        root.bind("<F5>", lambda *_: self.check())
        root.bind("<Control-Return>", lambda *_: self.start())

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.update_buttons()
        root.after(100, self.poll)
        root.after(1000, self.idle_monitor)
        if open_path:  # started from the file manager right-click menu
            root.after(200, lambda: self.open_from_shell(open_path))
        else:
            root.after(500, lambda: self.offer_pending(resume_pending))

    # --------------------------------------------------------- theme & i18n
    def _configure_report_tags(self):
        self.report.tag_configure("bad", foreground=self.pal["bad"])
        self.report.tag_configure("good", foreground=self.pal["good"])
        self.report.tag_configure("note", foreground=self.pal["note"])

    def toggle_theme(self):
        self.dark = not self.dark
        self.pal = apply_palette(self.root, self.dark)
        self.btn_theme.configure(text="☀" if self.dark else "☾")
        self.warn.configure(bg=self.pal["warn_bg"], fg=self.pal["warn_fg"],
                            highlightbackground=self.pal["warn_bd"])
        self.report.configure(bg=self.pal["field"], fg=self.pal["fg"],
                              insertbackground=self.pal["fg"],
                              highlightbackground=self.pal["border"])
        self._configure_report_tags()

    def toggle_language(self):
        new_lang = "en" if i18n.LANG == "de" else "de"
        self.settings.language = new_lang
        st.save(self.settings)
        i18n.set_lang(new_lang)
        self.refresh_texts()

    def refresh_texts(self):
        self.btn_lang.configure(text=i18n.LANG.upper())
        if not self.running:
            self.root.title(f"{t('app_title')} {__version__}")
        self.lbl_zip.configure(text=t("zip_file"))
        self.lbl_target.configure(text=t("target"))
        self.btn_zip.configure(text=t("browse"))
        self.btn_target.configure(text=t("browse"))
        self.chk_overwrite.configure(text=t("overwrite"))
        self.chk_delete.configure(text=t("delete_after"))
        self.warn.configure(text=t("warning_box"))
        for col, m in enumerate(("safe", "balanced", "performance")):
            self.mode_radios[col].configure(text=t(f"mode_{m}"))
            self.mode_desc_lbls[m].configure(text=t(f"mode_{m}_desc"))
            self.mode_info_lbls[m].configure(text=t(f"mode_{m}_info"))
        if self.lbl_rec is not None:
            self.lbl_rec.configure(text=t("recommended"))
        self.update_modes_header()
        self.btn_check.configure(text=t("check"))
        self.btn_adv.configure(text=t("advanced"))
        self.btn_rec.configure(text=t("recovery_info"))
        self.mon.configure(text=t("monitor"))
        for key, lbl in self.mon_titles.items():
            lbl.configure(text=t(key))
        self.btn_banner.configure(text=t("auto_resume_cancel"))
        self.btn_pause.configure(text=t("pause"))
        self.update_buttons()
        if self.plan is not None:
            self.show_plan(self.plan)

    def _on_resize(self, event):
        if event.widget is self.frm and event.width > 300:
            self.warn.configure(wraplength=max(320, event.width - 52))

    def _sanitize_var(self, var: tk.StringVar):
        cur = var.get()
        cleaned = _clean_path(cur)
        if cleaned != cur:
            var.set(cleaned)

    def open_from_shell(self, path: str):
        self.set_zip(os.path.normpath(os.path.abspath(_clean_path(path))))
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
        self._last_report_lines = list(lines)
        self.report.configure(state="normal")
        self.report.delete("1.0", "end")
        for text, tag in lines:
            self.report.insert("end", text + "\n", tag)
        self.report.configure(state="disabled")

    def apply_monitor_visibility(self):
        if self.settings.show_monitor:
            self.mon.grid(row=11, column=0, columnspan=3, sticky="ew", padx=8, pady=4)
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
        if self.busy():
            return
        f = _native_open_zip(self.root, t("zip_file").rstrip(":"), _initial_dir_for(self.zip_var.get()))
        if not f:
            return
        self.set_zip(os.path.normpath(_clean_path(f)))
        self.check()

    def set_zip(self, f: str, target: str | None = None):
        from . import source
        f = source.first_part(_clean_path(f))  # any part of a split ZIP -> its first part
        self.zip_var.set(f)
        try:
            j = journal.load(f)
        except journal.JournalError:
            j = None
        if target:
            self.target_var.set(target)
        elif j:
            self.target_var.set(j["target"])
        elif not self.target_var.get() or self.target_var.get() == self._auto_target:
            base = source.split_base(f)
            auto = os.path.splitext(base[0] if base else f)[0]
            self._auto_target = auto
            self.target_var.set(auto)

    def pick_target(self):
        if self.busy():
            return
        d = _native_pick_dir(
            self.root, t("target").rstrip(":"), _initial_dir_for(self.target_var.get() or self.zip_var.get())
        )
        if d:
            self._auto_target = ""
            self.target_var.set(os.path.normpath(_clean_path(d)))

    # ---------------------------------------------------------------- dialogs
    def open_advanced(self):
        if not self.busy():
            AdvancedDialog(self)

    def show_recovery(self):
        z = _clean_path(self.zip_var.get())
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
        self._sanitize_var(self.zip_var)
        self._sanitize_var(self.target_var)
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
        latest_progress = None
        try:
            while True:
                item = self.q.get_nowait()
                kind = item[0]
                if kind == "progress":
                    latest_progress = item[1]
                    continue
                if latest_progress is not None:
                    self.show_progress(latest_progress)
                    latest_progress = None
                if kind == "plan":
                    self.running = False
                    self.root.title(f"{t('app_title')} {__version__}")
                    self.show_plan(item[1])
                elif kind == "done":
                    r = item[1]
                    self.running = False
                    self.root.title(f"{t('app_title')} {__version__}")
                    self.bar["value"] = 1000
                    avg_bps = int(r.written / max(r.elapsed, 1e-6))
                    self.status_var.set(t("status_done", entries=r.entries, total=fmt_bytes(r.bytes),
                                          elapsed=fmt_duration(r.elapsed), avg=fmt_bytes(avg_bps)))
                    self.current_var.set("")
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
                    self.root.title(f"{t('app_title')} {__version__}")
                    self.current_var.set("")
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
                    self.root.title(f"{t('app_title')} {__version__}")
                    self.write_report([(item[1], "bad")])
        except queue.Empty:
            pass
        if latest_progress is not None:
            self.show_progress(latest_progress)
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
            pct = 100.0 * pr.bytes_done / pr.bytes_total
            self.bar["value"] = 10 * pct
            if self.running:
                self.root.title(f"[{pct:.0f}%] {t('app_title')} {__version__}")
        self.status_var.set(t("status_running", done=pr.entries_done, ntotal=pr.entries_total,
                              bytes=fmt_bytes(pr.bytes_done), btotal=fmt_bytes(pr.bytes_total),
                              speed=fmt_bytes(int(pr.speed)), avg=fmt_bytes(int(pr.avg_speed)),
                              alloc=fmt_bytes(pr.archive_allocated), free=fmt_bytes(pr.free)))
        self.current_var.set(_ellipsize_middle(pr.current))
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
        w.configure(bg=app.pal["bg"])
        w.title(t("advanced_title"))
        w.transient(app.root)
        w.grab_set()
        w.minsize(680, 560)
        w.bind("<Escape>", lambda *_: w.destroy())
        self.vars: dict = {}
        ttk.Label(w, text=t("custom_note"), wraplength=640, style="Muted.TLabel").pack(
            anchor="w", padx=12, pady=(12, 6))
        nb = ttk.Notebook(w)
        nb.pack(fill="both", expand=True, padx=12, pady=4)
        for tab, items in self.LAYOUT.items():
            page = ttk.Frame(nb, padding=12, style="CardInner.TFrame")
            nb.add(page, text=t(tab))
            page.columnconfigure(1, weight=1)
            for r, (name, kind) in enumerate(items):
                self._row(page, r, name, kind)
            if tab == "tab_ram":
                info = (f"RAM: {fmt_bytes(sysinfo.total_ram())} · "
                        f"{fmt_bytes(sysinfo.available_ram())} frei/free · "
                        f"CPU: {os.cpu_count()} Threads")
                ttk.Label(page, text=info, style="CardGood.TLabel").grid(
                    row=len(items) * 2, column=0, columnspan=3, sticky="w", pady=8)
        btns = ttk.Frame(w)
        btns.pack(fill="x", padx=12, pady=12)
        ttk.Button(btns, text=t("defaults"), command=self.defaults).pack(side="left")
        ttk.Button(btns, text=t("cancel_btn"), command=w.destroy).pack(side="right", padx=4)
        ttk.Button(btns, text=t("save"), style="Accent.TButton", command=self.save).pack(side="right", padx=4)
        self.load(app.settings)

    def _row(self, page, r, name, kind):
        ttk.Label(page, text=t(f"s_{name}"), style="Card.TLabel").grid(
            row=r * 2, column=0, sticky="w", pady=(6, 0), padx=(0, 12)
        )
        if kind == "bool":
            v = tk.BooleanVar()
            ttk.Checkbutton(page, variable=v).grid(row=r * 2, column=1, sticky="w", pady=(6, 0))
        elif kind == "choice":
            v = tk.StringVar()
            ttk.Combobox(page, textvariable=v, values=st.CHOICES[name], state="readonly",
                         width=16).grid(row=r * 2, column=1, sticky="w", pady=(6, 0))
        elif kind == "dir":
            v = tk.StringVar()
            fr = ttk.Frame(page, style="CardInner.TFrame")
            fr.grid(row=r * 2, column=1, sticky="ew", pady=(6, 0))
            ttk.Entry(fr, textvariable=v).pack(side="left", fill="x", expand=True)
            ttk.Button(fr, text=t("browse"), command=lambda: self._browse(v)).pack(side="left", padx=4)
        else:
            v = tk.StringVar()
            lo, hi = st.LIMITS[name]
            ttk.Spinbox(page, textvariable=v, from_=lo, to=hi, width=10,
                        increment=0.25 if kind == "float" else 1).grid(
                row=r * 2, column=1, sticky="w", pady=(6, 0))
        ttk.Label(page, text=t(f"d_{name}"), wraplength=620, style="CardMuted.TLabel",
                  justify="left").grid(row=r * 2 + 1, column=0, columnspan=3, sticky="w", pady=(1, 2))
        self.vars[name] = (v, kind)

    def _browse(self, v):
        d = _native_pick_dir(self.win, t("s_temp_dir"), _initial_dir_for(v.get()))
        if d:
            v.set(os.path.normpath(_clean_path(d)))

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
                elif kind == "dir":
                    raw = _clean_path(str(raw))
            except ValueError:
                raw = getattr(s, name)
            setattr(s, name, raw)
        s, fixed = st.validate(s)
        self.app.settings = s
        st.save(s)
        i18n.set_lang(s.language)
        if not s.resume_after_reboot:
            jobs.set_autostart(False)
        elif jobs.pending():
            jobs.set_autostart(True)
        apply_explorer_menu(s.explorer_menu)
        self.app.apply_monitor_visibility()
        self.app.refresh_texts()
        self.app.invalidate()
        names = [t(f"s_{f}") for f in fixed if f"s_{f}" in T]
        if names:
            messagebox.showinfo(t("advanced_title"), t("clamped") + "\n• " + "\n• ".join(names),
                                parent=self.win)
        self.win.destroy()


def apply_explorer_menu(on: bool) -> None:
    """Add/remove the right-click entry (per-user only). Skipped in tests."""
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
            root._icon_img = tk.PhotoImage(file=png)  # type: ignore[attr-defined]
            root.iconphoto(True, root._icon_img)  # type: ignore[attr-defined]
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
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # type: ignore[attr-defined]
    except Exception:
        pass
    root = tk.Tk(className="inplace-unpack")
    set_window_icon(root)
    i18n.set_lang(st.load().language)
    files = [a for a in argv if not a.startswith("--")]
    App(root, resume_pending="--resume-pending" in argv, open_path=files[0] if files else None)
    root.mainloop()


if __name__ == "__main__":
    main()
