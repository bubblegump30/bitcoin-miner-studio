import ctypes
import os
import sys
import queue
import threading
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog

from branding import PUBLISHER_NAME
from config import load_config, save_config
from connections import test_bitcoin_core, test_stratum
from credentials import (
    POOL_TARGET,
    RPC_TARGET,
    backend_name,
    read_secret,
    write_secret,
)
from miner_engine import BenchmarkEngine
from stratum_miner import StratumMiner
from local_test_pool import LocalStratumTestPool
from fleet_monitor import FleetMonitor, export_fleet_json, export_fleet_csv
from asic_manager import (
    default_private_cidr,
    discover_devices,
    ensure_private_host,
    query_device,
    classify_probe,
    restart_miner,
    switch_pool,
)
from neon_widgets import GlowPanel, NeonButton, NavButton, MetricCard

APP_NAME = "Bitcoin Miner Studio"
VERSION = "1.3.0.4"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} v{VERSION}")
        self.geometry("1520x940")
        self.minsize(1280, 800)

        try:
            icon_png = Path(__file__).resolve().parent / "assets" / "BitcoinMinerStudio.png"
            if icon_png.is_file():
                self._bms_app_icon = tk.PhotoImage(file=str(icon_png))
                self.iconphoto(True, self._bms_app_icon)
        except Exception:
            pass
        if sys.platform == "win32":
            try:
                icon_ico = Path(__file__).resolve().parent / "assets" / "BitcoinMinerStudio.ico"
                if icon_ico.is_file():
                    self.iconbitmap(default=str(icon_ico))
            except Exception:
                pass

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
        try:
            self.call("tk", "scaling", 1.25)
        except Exception:
            pass

        self.cfg = load_config()
        self.benchmark = BenchmarkEngine()
        self.ui_queue = queue.Queue()
        self.miner = StratumMiner(
            event_callback=lambda kind, payload: self.ui_queue.put(("miner", kind, payload))
        )
        self.local_pool = LocalStratumTestPool(
            difficulty=float(self.cfg.get("local_test_difficulty", 0.000001)),
            event_callback=lambda kind, payload: self.ui_queue.put(("local_pool", kind, payload)),
        )

        self.asic_devices = {}
        self._asic_busy = False
        self._asic_auto_after = None
        history_path = Path.home() / ".bitcoin-miner-studio" / "fleet_history.json"
        self.fleet_monitor = FleetMonitor(max_samples=180, storage_path=history_path)
        self.asic_aliases = dict(self.cfg.get("asic_aliases", {}) or {})
        self.asic_groups = dict(self.cfg.get("asic_groups", {}) or {})
        self.asic_notes = dict(self.cfg.get("asic_notes", {}) or {})
        self.asic_known_devices = set(self.cfg.get("asic_known_devices", []) or [])
        self._fleet_alert_keys = set()
        self._asic_sort_column = "ip"
        self._asic_sort_reverse = False

        try:
            self.saved_pool_password = read_secret(POOL_TARGET) or ""
        except Exception:
            self.saved_pool_password = ""
        try:
            self.saved_rpc_password = read_secret(RPC_TARGET) or ""
        except Exception:
            self.saved_rpc_password = ""

        self._configure_style()
        self._build_ui()
        self.after(250, self._tick)
        self.protocol("WM_DELETE_WINDOW", self._on_close)


    def _configure_style(self):
        self.colors = {
            "bg": "#07060B",
            "panel": "#0E0A15",
            "card": "#171020",
            "card_2": "#21162E",
            "entry": "#21162E",
            "text": "#FAF7FF",
            "muted": "#CFC3DA",
            "text_muted": "#9587A3",
            "metric": "#FAF7FF",
            "line": "#35115D",
            "shadow": "#05030A",
            "accent": "#9654FF",
            "accent_hover": "#B678FF",
            "accent_soft": "#6425A8",
            "accent_soft_2": "#D3A5FF",
            "danger": "#6425A8",
            "danger_hover": "#9654FF",
            "secondary": "#6425A8",
            "secondary_hover": "#9654FF",
            "teal": "#B678FF",
            "teal_hover": "#D3A5FF",
            "warning": "#9654FF",
            "sidebar": "#0E0A15",
            "sidebar_hover": "#171020",
            "sidebar_active": "#35115D",
            "glow": "#B678FF",
            "glow_soft": "#35115D",
            "success": "#D3A5FF",
            "success_2": "#6425A8",
            "card_edge": "#6425A8",
            "raised": "#21162E",
        }

        self.configure(bg=self.colors["bg"])

        self.ui_scale_profiles = {
            "Normal": 1.00,
            "Large": 1.15,
            "Extra Large": 1.35,
        }
        self.ui_scale_mode = str(self.cfg.get("ui_scale_mode", "Large"))
        if self.ui_scale_mode not in self.ui_scale_profiles:
            self.ui_scale_mode = "Large"
        self.ui_scale_factor = self.ui_scale_profiles[self.ui_scale_mode]

        try:
            self.tk.call("tk", "scaling", self.ui_scale_factor)
        except Exception:
            pass

        try:
            self.option_add("*TCombobox*Listbox.background", self.colors["raised"])
            self.option_add("*TCombobox*Listbox.foreground", self.colors["text"])
            self.option_add("*TCombobox*Listbox.selectBackground", self.colors["accent"])
            self.option_add("*TCombobox*Listbox.selectForeground", self.colors["text"])
            self.option_add("*TCombobox*Listbox.font", "Segoe UI 11")
        except Exception:
            pass
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(".", background=self.colors["panel"], foreground=self.colors["text"])
        style.configure("TFrame", background=self.colors["panel"])
        style.configure("Card.TFrame", background=self.colors["card"], relief="flat", borderwidth=0)
        style.configure("TLabel", background=self.colors["panel"], foreground=self.colors["text"], font=("Segoe UI", 11))
        style.configure(
            "Title.TLabel",
            background=self.colors["bg"],
            foreground=self.colors["text"],
            font=("Segoe UI Semibold", 26),
        )
        style.configure(
            "Sub.TLabel",
            background=self.colors["bg"],
            foreground=self.colors["muted"],
            font=("Segoe UI", 13),
        )
        style.configure(
            "CardTitle.TLabel",
            background=self.colors["card"],
            foreground=self.colors["muted"],
            font=("Segoe UI Semibold", 12),
        )
        style.configure(
            "Metric.TLabel",
            background=self.colors["card"],
            foreground=self.colors["metric"],
            font=("Segoe UI Semibold", 22),
        )

        style.configure("TNotebook", background=self.colors["bg"], borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background=self.colors["panel"],
            foreground=self.colors["muted"],
            padding=(20, 12),
            font=("Segoe UI Semibold", 12),
            borderwidth=0,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", self.colors["sidebar_active"]), ("active", self.colors["card"])],
            foreground=[("selected", self.colors["text"]), ("active", self.colors["text"])],
        )

        style.configure(
            "TEntry",
            fieldbackground=self.colors["entry"],
            foreground=self.colors["text"],
            insertcolor=self.colors["text"],
            padding=12,
            bordercolor=self.colors["line"],
            lightcolor=self.colors["accent"],
            darkcolor=self.colors["line"],
            font=("Segoe UI", 12),
        )
        style.configure(
            "TSpinbox",
            fieldbackground=self.colors["entry"],
            foreground=self.colors["text"],
            arrowcolor=self.colors["text"],
            padding=12,
            font=("Segoe UI", 12),
        )
        style.configure(
            "TCombobox",
            fieldbackground=self.colors["entry"],
            foreground=self.colors["text"],
            arrowcolor=self.colors["text"],
            padding=12,
            selectforeground=self.colors["text"],
            selectbackground=self.colors["entry"],
            font=("Segoe UI", 12),
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", self.colors["entry"]), ("active", self.colors["raised"])],
            foreground=[("readonly", self.colors["text"]), ("active", self.colors["text"]), ("disabled", self.colors["text_muted"])],
            selectforeground=[("readonly", self.colors["text"]), ("active", self.colors["text"])],
            selectbackground=[("readonly", self.colors["entry"]), ("active", self.colors["raised"])],
            arrowcolor=[("readonly", self.colors["text"]), ("active", self.colors["text"]), ("disabled", self.colors["muted"])],
        )
        style.configure(
            "TCheckbutton",
            background=self.colors["panel"],
            foreground=self.colors["text"],
            font=("Segoe UI Semibold", 11),
        )
        style.map("TCheckbutton", background=[("active", self.colors["panel"])])

        style.configure(
            "Treeview",
            background=self.colors["entry"],
            fieldbackground=self.colors["entry"],
            foreground=self.colors["text"],
            rowheight=34,
            borderwidth=0,
            font=("Consolas", 11),
        )
        style.configure(
            "Treeview.Heading",
            background=self.colors["card_2"],
            foreground=self.colors["muted"],
            font=("Segoe UI Semibold", 12),
        )
        style.map("Treeview", background=[("selected", self.colors["sidebar_active"])])

        style.configure(
            "PageTitle.TLabel",
            background=self.colors["panel"],
            foreground=self.colors["text"],
            font=("Segoe UI Semibold", 22),
        )
        style.configure(
            "PageSub.TLabel",
            background=self.colors["panel"],
            foreground=self.colors["muted"],
            font=("Segoe UI", 12),
        )

    def _make_3d_button(
        self,
        parent,
        text,
        command,
        role="primary",
        width=None,
        state="normal",
    ):
        btn = NeonButton(
            parent,
            text=text,
            command=command,
            role=role,
            width=width,
            state=state,
            font=("Segoe UI Semibold", 11),
            height=48,
        )

        def _apply_disabled_visual():
            btn.configure(state="disabled")

        def _apply_enabled_visual():
            btn.configure(state="normal")

        btn._bms_enabled_visual = _apply_enabled_visual
        btn._bms_disabled_visual = _apply_disabled_visual
        return btn


    def _build_ui(self):
        self._nav_buttons = {}
        self._pages = {}
        self._active_page = None
        self._pulse_phase = False

        shell = tk.Frame(self, bg=self.colors["bg"])
        shell.pack(fill="both", expand=True, padx=8, pady=8)

        sidebar_shell = GlowPanel(
            shell,
            fill="#0E0A15",
            border="#35115D",
            glow="#9654FF",
            radius=18,
            inset=10,
            bg=self.colors["bg"],
            width=246,
        )
        sidebar_shell.pack(side="left", fill="y", padx=(0, 10))
        sidebar_shell.pack_propagate(False)
        self.sidebar = sidebar_shell.content
        self.sidebar.configure(bg="#0E0A15")

        brand = tk.Frame(self.sidebar, bg="#0E0A15")
        brand.pack(fill="x", padx=10, pady=(10, 14))

        icon_shell = GlowPanel(
            brand,
            fill="#21162E",
            border="#6425A8",
            glow="#D3A5FF",
            radius=14,
            inset=4,
            bg="#0E0A15",
            width=54,
            height=54,
        )
        icon_shell.pack(side="left", padx=(0, 12))
        icon_shell.pack_propagate(False)
        tk.Label(
            icon_shell.content,
            text="₿",
            bg="#21162E",
            fg="#D3A5FF",
            font=("Segoe UI Semibold", 22),
        ).pack(expand=True)

        brand_text = tk.Frame(brand, bg="#0E0A15")
        brand_text.pack(side="left", fill="x", expand=True, pady=(2, 0))
        tk.Label(
            brand_text,
            text="Bitcoin Miner\nStudio",
            justify="left",
            bg="#0E0A15",
            fg="#FAF7FF",
            font=("Segoe UI Semibold", 12),
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            brand_text,
            text=f"v{VERSION}",
            bg="#0E0A15",
            fg="#9587A3",
            font=("Segoe UI", 9),
            anchor="w",
        ).pack(fill="x", pady=(2, 0))
        tk.Label(
            brand_text,
            text=PUBLISHER_NAME,
            bg="#0E0A15",
            fg="#D3A5FF",
            font=("Segoe UI Semibold", 7),
            anchor="w",
            wraplength=155,
            justify="left",
        ).pack(fill="x", pady=(2, 0))

        tk.Frame(self.sidebar, bg="#35115D", height=1).pack(fill="x", pady=(0, 12))
        tk.Label(
            self.sidebar,
            text="NAVIGATION",
            bg="#0E0A15",
            fg="#9587A3",
            font=("Segoe UI Semibold", 9),
            anchor="w",
        ).pack(fill="x", padx=8, pady=(0, 8))

        nav_specs = [
            ("dashboard", "⌂", "Dashboard"),
            ("asic", "⚙", "ASIC Control"),
            ("pool", "⇄", "Pool Mining"),
            ("core", "Ⓑ", "Bitcoin Core"),
            ("logs", "☰", "Logs"),
        ]
        for key, icon, label in nav_specs:
            btn = NavButton(
                self.sidebar,
                icon=icon,
                text=label,
                command=lambda k=key: self._show_page(k),
                bg="#0E0A15",
                hover="#11182c",
                active="#2b1658",
                accent="#B678FF",
            )
            btn.pack(fill="x", padx=6, pady=2)
            self._nav_buttons[key] = btn

        footer = tk.Frame(self.sidebar, bg="#0E0A15")
        footer.pack(side="bottom", fill="x", pady=(12, 0))

        scale_shell = GlowPanel(
            footer,
            fill="#171020",
            border="#6425A8",
            glow="#9654FF",
            radius=16,
            inset=10,
            bg="#0E0A15",
            height=164,
        )
        scale_shell.pack(fill="x", padx=6, pady=(0, 10))
        scale_shell.pack_propagate(False)
        scale_card = scale_shell.content
        tk.Label(scale_card, text="UI SCALE", bg="#171020", fg="#CFC3DA", font=("Segoe UI Semibold", 11)).pack(anchor="w", padx=10, pady=(10, 6))
        self.ui_scale_var = tk.StringVar(value=self.ui_scale_mode)
        self.ui_scale_combo = ttk.Combobox(
            scale_card,
            textvariable=self.ui_scale_var,
            state="readonly",
            values=("Normal", "Large", "Extra Large"),
            width=16,
        )
        self.ui_scale_combo.pack(fill="x", padx=10, pady=(0, 10), ipady=5)
        self.ui_scale_apply_btn = self._make_3d_button(scale_card, "Apply Scale", self._apply_ui_scale_setting, role="secondary")
        self.ui_scale_apply_btn.configure(font=("Segoe UI Semibold", 12), height=50)
        self.ui_scale_apply_btn.pack(fill="x", padx=10, pady=(0, 10))

        engine_shell = GlowPanel(
            footer,
            fill="#171020",
            border="#6425A8",
            glow="#9654FF",
            radius=16,
            inset=10,
            bg="#0E0A15",
            height=118,
        )
        engine_shell.pack(fill="x", padx=6)
        engine_shell.pack_propagate(False)
        footer_card = engine_shell.content
        tk.Label(footer_card, text="SHA-256d ENGINE", bg="#171020", fg="#CFC3DA", font=("Segoe UI Semibold", 10)).pack(anchor="w", padx=10, pady=(8, 3))
        tk.Label(footer_card, text="READY", bg="#171020", fg="#D3A5FF", font=("Segoe UI Semibold", 14)).pack(anchor="w", padx=10)
        tk.Label(footer_card, text="Visible • Local control", bg="#171020", fg="#9587A3", font=("Segoe UI", 10)).pack(anchor="w", padx=10, pady=(2, 8))

        main_outer = GlowPanel(
            shell,
            fill="#07060B",
            border="#1c1b34",
            glow="#15203f",
            radius=20,
            inset=0,
            bg=self.colors["bg"],
        )
        main_outer.pack(side="left", fill="both", expand=True)
        main = tk.Frame(main_outer.content, bg="#07060B")
        main.pack(fill="both", expand=True, padx=16, pady=14)

        header = tk.Frame(main, bg="#07060B")
        header.pack(fill="x", pady=(6, 10))

        title_wrap = tk.Frame(header, bg="#07060B")
        title_wrap.pack(side="left")
        ttk.Label(title_wrap, text=APP_NAME, style="Title.TLabel").pack(anchor="w")
        ttk.Label(title_wrap, text=f"v{VERSION}  •  Stratum pool miner  •  SHA-256d toolkit", style="Sub.TLabel").pack(anchor="w", pady=(3, 0))

        badge_wrap = GlowPanel(
            header,
            fill="#6425A8",
            border="#B678FF",
            glow="#D3A5FF",
            radius=14,
            inset=4,
            bg="#07060B",
            width=164,
            height=52,
        )
        badge_wrap.pack(side="right")
        badge_wrap.pack_propagate(False)
        tk.Label(badge_wrap.content, text="BITCOIN / SHA-256d", bg="#6425A8", fg="#FAF7FF", font=("Segoe UI Semibold", 11)).pack(expand=True)

        glow_line = tk.Frame(main, bg="#9654FF", height=2)
        glow_line.pack(fill="x", pady=(0, 10))

        self.page_host = tk.Frame(main, bg="#07060B")
        self.page_host.pack(fill="both", expand=True)

        self.dashboard = ttk.Frame(self.page_host)
        self.asic_tab = ttk.Frame(self.page_host)
        self.pool_tab = ttk.Frame(self.page_host)
        self.node_tab = ttk.Frame(self.page_host)
        self.log_tab = ttk.Frame(self.page_host)

        self._pages = {
            "dashboard": self.dashboard,
            "asic": self.asic_tab,
            "pool": self.pool_tab,
            "core": self.node_tab,
            "logs": self.log_tab,
        }

        for page in self._pages.values():
            page.place(relx=0, rely=0, relwidth=1, relheight=1)

        self._build_dashboard()
        self._build_asic_tab()
        self._build_pool_tab()
        self._build_node_tab()
        self._build_log_tab()

        self._show_page("dashboard")
        self.after(550, self._animate_status_glow)
        self.after(1200, self._asic_auto_tick)
        self.after(1400, self._asic_load_known_devices)

    def _apply_ui_scale_setting(self):
        mode = self.ui_scale_var.get().strip()
        if mode not in self.ui_scale_profiles:
            messagebox.showerror("UI Scale", "Choose Normal, Large, or Extra Large.")
            return

        if mode == self.ui_scale_mode:
            messagebox.showinfo(
                "UI Scale",
                f"{mode} is already active.",
            )
            return

        active = self.miner.running or self.benchmark.running or self.local_pool.running
        if active:
            if not messagebox.askyesno(
                "Apply UI Scale",
                "Changing UI scale restarts Bitcoin Miner Studio and will stop "
                "the current mining / benchmark / local-test session.\n\nContinue?",
            ):
                return

        self.cfg["ui_scale_mode"] = mode

        try:
            self._save_fields()
        except Exception:
            try:
                save_config(self.cfg)
            except Exception as exc:
                messagebox.showerror("UI Scale", f"Could not save scale setting:\n{exc}")
                return

        try:
            self.miner.stop()
        except Exception:
            pass
        try:
            self.benchmark.stop()
        except Exception:
            pass
        try:
            self.local_pool.stop()
        except Exception:
            pass

        # Re-launch so all hard-coded and ttk fonts are recreated at the
        # selected Tk scaling factor. This is more reliable than partially
        # resizing an already-running Tk widget tree.
        try:
            os.execl(sys.executable, sys.executable, *sys.argv)
        except Exception as exc:
            messagebox.showerror(
                "UI Scale",
                f"The scale setting was saved, but the app could not restart automatically.\n\n"
                f"Close and reopen Bitcoin Miner Studio to apply {mode}.\n\n{exc}",
            )

    def _show_page(self, key):
        page = self._pages.get(key)
        if page is None:
            return
        page.tkraise()
        self._active_page = key

        for nav_key, btn in self._nav_buttons.items():
            try:
                btn.set_active(nav_key == key)
            except Exception:
                pass

    def _animate_status_glow(self):
        if not self.winfo_exists():
            return
        self._pulse_phase = not self._pulse_phase

        try:
            mode = self.mode_var.get() if hasattr(self, "mode_var") else "READY"
            running = bool(self.miner.running or self.benchmark.running)

            if running:
                if mode == "LOCAL TEST":
                    c1, c2 = "#7c3aed", "#a855f7"
                elif mode == "REAL POOL":
                    c1, c2 = "#14b8a6", "#2dd4bf"
                elif mode == "BENCHMARK":
                    c1, c2 = "#5f46d8", "#8b5cf6"
                else:
                    c1, c2 = self.colors["accent"], self.colors["accent_hover"]

                self.mode_badge.configure(bg=c1 if self._pulse_phase else c2)
            else:
                self._update_mode_badge()
        except Exception:
            pass

        self.after(550, self._animate_status_glow)

    def _metric_card(self, parent, title, var, row, col):
        card = MetricCard(
            parent,
            title,
            var,
            bg=self.colors["panel"],
            fill=self.colors["card"],
            border="#4b347c",
        )
        card.grid(
            row=row,
            column=col,
            sticky="nsew",
            padx=(0 if col == 0 else 7, 0),
            pady=(0 if row == 0 else 7, 0),
        )


    def _build_dashboard(self):
        wrap = tk.Frame(self.dashboard, bg="#07060B")
        wrap.pack(fill="both", expand=True, padx=10, pady=8)

        self.mode_var = tk.StringVar(value="REAL POOL")
        self.endpoint_var = tk.StringVar(value="No pool session")
        self.latency_var = tk.StringVar(value="—")
        self.job_var = tk.StringVar(value="—")
        self.status_var = tk.StringVar(value="Idle")

        strip_panel = GlowPanel(wrap, fill="#171020", border="#6425A8", glow="#B678FF", radius=16, inset=12, bg="#07060B", height=92)
        strip_panel.pack(fill="x", pady=(0, 12))
        strip_panel.pack_propagate(False)
        strip = strip_panel.content
        strip.columnconfigure(1, weight=1)

        self.mode_badge = tk.Label(strip, textvariable=self.mode_var, bg="#6425A8", fg="#FAF7FF", font=("Segoe UI Semibold", 12), padx=16, pady=9)
        self.mode_badge.grid(row=0, column=0, rowspan=2, sticky="w", padx=(6, 14), pady=8)
        tk.Label(strip, textvariable=self.endpoint_var, bg="#171020", fg="#FAF7FF", font=("Segoe UI Semibold", 11), anchor="w").grid(row=0, column=1, sticky="sw", pady=(8, 0))
        tk.Label(strip, textvariable=self.status_var, bg="#171020", fg="#FAF7FF", font=("Segoe UI Semibold", 14), anchor="w").grid(row=1, column=1, sticky="nw", pady=(0, 8))
        tk.Label(strip, text="LATENCY", bg="#171020", fg="#CFC3DA", font=("Segoe UI Semibold", 9)).grid(row=0, column=2, padx=(20, 8), pady=(8, 0))
        tk.Label(strip, textvariable=self.latency_var, bg="#171020", fg="#FAF7FF", font=("Segoe UI Semibold", 12)).grid(row=1, column=2, padx=(20, 8), pady=(0, 8))
        tk.Label(strip, text="JOB", bg="#171020", fg="#CFC3DA", font=("Segoe UI Semibold", 9)).grid(row=0, column=3, padx=(18, 8), pady=(8, 0))
        tk.Label(strip, textvariable=self.job_var, bg="#171020", fg="#FAF7FF", font=("Consolas", 11)).grid(row=1, column=3, padx=(18, 8), pady=(0, 8))

        metrics = tk.Frame(wrap, bg="#07060B")
        metrics.pack(fill="x")
        for i in range(4):
            metrics.columnconfigure(i, weight=1, uniform="metric")

        self.hashrate_var = tk.StringVar(value="0 H/s")
        self.avg_hashrate_var = tk.StringVar(value="0 H/s")
        self.peak_hashrate_var = tk.StringVar(value="0 H/s")
        self.accepted_var = tk.StringVar(value="0")
        self.rejected_var = tk.StringVar(value="0")
        self.stale_var = tk.StringVar(value="0")
        self.submitted_var = tk.StringVar(value="0")
        self.acceptance_var = tk.StringVar(value="—")
        self.difficulty_var = tk.StringVar(value="—")
        self.share_eta_var = tk.StringVar(value="—")
        self.total_hashes_var = tk.StringVar(value="0")
        self.uptime_var = tk.StringVar(value="00:00:00")
        self.workers_var = tk.StringVar(value="0")

        cards = [
            ("HASHRATE", self.hashrate_var, 0, 0),
            ("AVG HASHRATE", self.avg_hashrate_var, 0, 1),
            ("PEAK HASHRATE", self.peak_hashrate_var, 0, 2),
            ("ACCEPTED", self.accepted_var, 0, 3),
            ("REJECTED", self.rejected_var, 1, 0),
            ("STALE", self.stale_var, 1, 1),
            ("SUBMITTED", self.submitted_var, 1, 2),
            ("ACCEPTANCE", self.acceptance_var, 1, 3),
            ("DIFFICULTY", self.difficulty_var, 2, 0),
            ("EXPECTED SHARE", self.share_eta_var, 2, 1),
            ("TOTAL HASHES", self.total_hashes_var, 2, 2),
            ("UPTIME", self.uptime_var, 2, 3),
        ]
        for title, var, row, col in cards:
            card = MetricCard(metrics, title, var, bg="#07060B", fill="#171020", border="#6425A8")
            card.grid(row=row, column=col, sticky="nsew", padx=(0 if col == 0 else 8, 0), pady=(0 if row == 0 else 8, 0))

        controls = tk.Frame(wrap, bg="#07060B")
        controls.pack(fill="x", pady=(10, 0))
        controls.columnconfigure(0, weight=1, uniform="control")
        controls.columnconfigure(1, weight=1, uniform="control")

        mining_panel = GlowPanel(controls, fill="#171020", border="#6425A8", glow="#B678FF", radius=16, inset=12, bg="#07060B", height=108)
        mining_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        mining_panel.grid_propagate(False)
        mining = mining_panel.content
        tk.Label(mining, text="◉  POOL MINING", bg="#171020", fg="#FAF7FF", font=("Segoe UI Semibold", 11)).grid(row=0, column=0, columnspan=7, sticky="w", pady=(2, 10))
        tk.Label(mining, text="Processes:", bg="#171020", fg="#CFC3DA", font=("Segoe UI", 10)).grid(row=1, column=0, sticky="w")
        self.mining_processes_var = tk.IntVar(value=int(self.cfg.get("mining_processes", 2)))
        ttk.Spinbox(mining, from_=1, to=64, width=5, textvariable=self.mining_processes_var).grid(row=1, column=1, sticky="w", padx=(8, 14))
        self.start_mining_btn = self._make_3d_button(mining, "Start Mining", self._start_mining, role="primary", width=10)
        self.start_mining_btn.grid(row=1, column=2, padx=(0, 8))
        self.stop_mining_btn = self._make_3d_button(mining, "Stop Mining", self._stop_mining, role="danger", width=10, state="disabled")
        self.stop_mining_btn.grid(row=1, column=3, padx=(0, 8))
        self.reset_session_btn = self._make_3d_button(mining, "Reset Session", self._reset_session_stats, role="secondary", width=10)
        self.reset_session_btn.grid(row=1, column=4)

        bench_panel = GlowPanel(controls, fill="#171020", border="#6425A8", glow="#28d8ff", radius=16, inset=12, bg="#07060B", height=108)
        bench_panel.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        bench_panel.grid_propagate(False)
        benchmark = bench_panel.content
        tk.Label(benchmark, text="◔  LOCAL BENCHMARK", bg="#171020", fg="#FAF7FF", font=("Segoe UI Semibold", 11)).grid(row=0, column=0, columnspan=6, sticky="w", pady=(2, 10))
        tk.Label(benchmark, text="Processes:", bg="#171020", fg="#CFC3DA", font=("Segoe UI", 10)).grid(row=1, column=0, sticky="w")
        self.benchmark_processes_var = tk.IntVar(value=int(self.cfg.get("benchmark_processes", 2)))
        ttk.Spinbox(benchmark, from_=1, to=64, width=5, textvariable=self.benchmark_processes_var).grid(row=1, column=1, sticky="w", padx=(8, 14))
        self.start_benchmark_btn = self._make_3d_button(benchmark, "Start Benchmark", self._start_benchmark, role="teal", width=13)
        self.start_benchmark_btn.grid(row=1, column=2, padx=(0, 8))
        self.stop_benchmark_btn = self._make_3d_button(benchmark, "Stop", self._stop_benchmark, role="danger", width=8, state="disabled")
        self.stop_benchmark_btn.grid(row=1, column=3)

        recent_panel = GlowPanel(wrap, fill="#171020", border="#6425A8", glow="#B678FF", radius=16, inset=12, bg="#07060B")
        recent_panel.pack(fill="both", expand=True, pady=(10, 0))
        recent = recent_panel.content
        top = tk.Frame(recent, bg="#171020")
        top.pack(fill="x", pady=(1, 8))
        tk.Label(top, text="▣  RECENT SHARES", bg="#171020", fg="#FAF7FF", font=("Segoe UI Semibold", 11)).pack(side="left")
        self.share_summary_var = tk.StringVar(value="No submitted shares yet.")
        tk.Label(top, textvariable=self.share_summary_var, bg="#171020", fg="#CFC3DA", font=("Segoe UI", 9)).pack(side="right")
        columns = ("time", "result", "job", "nonce", "response")
        self.share_tree = ttk.Treeview(recent, columns=columns, show="headings", height=12)
        self.share_tree.heading("time", text="TIME")
        self.share_tree.heading("result", text="RESULT")
        self.share_tree.heading("job", text="JOB")
        self.share_tree.heading("nonce", text="NONCE")
        self.share_tree.heading("response", text="RESPONSE")
        self.share_tree.column("time", width=95, anchor="center", stretch=False)
        self.share_tree.column("result", width=115, anchor="center", stretch=False)
        self.share_tree.column("job", width=420, anchor="w")
        self.share_tree.column("nonce", width=120, anchor="center", stretch=False)
        self.share_tree.column("response", width=110, anchor="e", stretch=False)
        self.share_tree.pack(fill="both", expand=True)

    def _set_action_button_state(self, button, state):
        button.configure(state=state)
        if state == "disabled":
            fn = getattr(button, "_bms_disabled_visual", None)
        else:
            fn = getattr(button, "_bms_enabled_visual", None)
        if fn:
            fn()

    def _build_asic_tab(self):
        frame = ttk.Frame(self.asic_tab, padding=20)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="ASIC Control Center", style="PageTitle.TLabel").pack(anchor="w")
        ttk.Label(
            frame,
            text="Discover and monitor compatible Bitcoin ASIC miners on a private LAN.",
            style="PageSub.TLabel",
        ).pack(anchor="w", pady=(4, 14))

        safety = tk.Frame(
            frame,
            bg="#171020",
            highlightthickness=1,
            highlightbackground=self.colors["card_edge"],
        )
        safety.pack(fill="x", pady=(0, 12))

        self.asic_authorized_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            safety,
            text="I own or administer the devices on this private network.",
            variable=self.asic_authorized_var,
            command=self._asic_update_discovery_state,
            bg="#171020",
            fg="#efe7ff",
            activebackground="#171024",
            activeforeground="#FAF7FF",
            selectcolor="#2b1747",
            font=("Segoe UI Semibold", 12),
        ).pack(side="left", padx=12, pady=10)

        tk.Label(
            safety,
            text="Discovery is restricted to private IPv4 ranges and /24 or smaller.",
            bg="#171020",
            fg=self.colors["muted"],
            font=("Segoe UI", 10),
        ).pack(side="right", padx=12)

        controls_outer = tk.Frame(frame, bg=self.colors["card_edge"])
        controls_outer.pack(fill="x", pady=(0, 12))
        controls = ttk.Frame(controls_outer, style="Card.TFrame", padding=14)
        controls.pack(fill="x", padx=1, pady=1)
        controls.columnconfigure(1, weight=1)

        ttk.Label(controls, text="LAN RANGE", style="CardTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )

        subnet_default = self.cfg.get("asic_subnet") or default_private_cidr()
        self.asic_subnet_var = tk.StringVar(value=subnet_default)
        ttk.Entry(
            controls,
            textvariable=self.asic_subnet_var,
            width=30,
        ).grid(row=1, column=0, sticky="w", pady=(7, 0), padx=(0, 14), ipady=2)

        self.asic_discover_btn = self._make_3d_button(
            controls,
            "Discover ASICs",
            self._asic_discover,
            role="primary",
            state="disabled",
        )
        self.asic_discover_btn.grid(row=1, column=1, sticky="w", pady=(7, 0), padx=(0, 10))

        self.asic_add_btn = self._make_3d_button(
            controls,
            "Add IP",
            self._asic_add_manual,
            role="secondary",
        )
        self.asic_add_btn.grid(row=1, column=2, sticky="w", pady=(7, 0), padx=(0, 10))

        self.asic_refresh_all_btn = self._make_3d_button(
            controls,
            "Refresh All",
            self._asic_refresh_all,
            role="teal",
        )
        self.asic_refresh_all_btn.grid(row=1, column=3, sticky="w", pady=(7, 0), padx=(0, 10))

        self.asic_auto_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            controls,
            text="Auto refresh",
            variable=self.asic_auto_var,
        ).grid(row=0, column=4, sticky="w", padx=(14, 6), pady=(0, 2))

        self.asic_refresh_seconds_var = tk.IntVar(
            value=max(5, int(self.cfg.get("asic_refresh_seconds", 10)))
        )
        ttk.Spinbox(
            controls,
            from_=5,
            to=300,
            width=10,
            textvariable=self.asic_refresh_seconds_var,
        ).grid(row=1, column=4, sticky="w", padx=(14, 6), pady=(7, 0), ipady=2)

        self.asic_temp_alert_var = tk.DoubleVar(
            value=float(self.cfg.get("asic_temp_alert_c", 80.0))
        )
        self.asic_drop_alert_var = tk.DoubleVar(
            value=float(self.cfg.get("asic_hashrate_drop_percent", 25.0))
        )

        ttk.Label(controls, text="TEMP ALERT °C", style="CardTitle.TLabel").grid(
            row=0, column=5, sticky="w", padx=(14, 6), pady=(0, 2)
        )
        ttk.Spinbox(
            controls,
            from_=40,
            to=120,
            increment=1,
            width=10,
            textvariable=self.asic_temp_alert_var,
        ).grid(row=1, column=5, sticky="w", padx=(14, 6), pady=(7, 0), ipady=2)

        ttk.Label(controls, text="HASH DROP %", style="CardTitle.TLabel").grid(
            row=0, column=6, sticky="w", padx=(14, 6), pady=(0, 2)
        )
        ttk.Spinbox(
            controls,
            from_=5,
            to=90,
            increment=5,
            width=10,
            textvariable=self.asic_drop_alert_var,
        ).grid(row=1, column=6, sticky="w", padx=(14, 6), pady=(7, 0), ipady=2)

        self.asic_export_json_btn = self._make_3d_button(
            controls, "Export JSON", self._asic_export_json, role="secondary"
        )
        self.asic_export_json_btn.grid(row=1, column=7, sticky="w", padx=(14, 6), pady=(7, 0))

        self.asic_export_csv_btn = self._make_3d_button(
            controls, "Export CSV", self._asic_export_csv, role="secondary"
        )
        self.asic_export_csv_btn.grid(row=1, column=8, sticky="w", padx=(6, 0), pady=(7, 0))

        self.asic_export_cfg_btn = self._make_3d_button(
            controls, "Export Config", self._asic_export_config, role="secondary"
        )
        self.asic_export_cfg_btn.grid(row=4, column=7, sticky="w", padx=(14, 6), pady=(6, 0))

        self.asic_import_cfg_btn = self._make_3d_button(
            controls, "Import Config", self._asic_import_config, role="secondary"
        )
        self.asic_import_cfg_btn.grid(row=4, column=8, sticky="w", padx=(6, 0), pady=(6, 0))

        ttk.Label(controls, text="SEARCH", style="CardTitle.TLabel").grid(
            row=3, column=0, sticky="w", pady=(12, 0)
        )
        self.asic_search_var = tk.StringVar(value="")
        search_entry = ttk.Entry(controls, textvariable=self.asic_search_var, width=24)
        search_entry.grid(row=4, column=0, sticky="w", pady=(6, 0), padx=(0, 14), ipady=2)
        self.asic_search_var.trace_add("write", lambda *_: self._asic_update_table())

        ttk.Label(controls, text="GROUP FILTER", style="CardTitle.TLabel").grid(
            row=3, column=1, sticky="w", pady=(12, 0)
        )
        self.asic_group_filter_var = tk.StringVar(value="All")
        self.asic_group_filter_combo = ttk.Combobox(
            controls,
            textvariable=self.asic_group_filter_var,
            state="readonly",
            width=22,
            values=["All"],
        )
        self.asic_group_filter_combo.grid(row=4, column=1, sticky="w", pady=(6, 0), ipady=2)
        self.asic_group_filter_combo.bind("<<ComboboxSelected>>", lambda _e: self._asic_update_table())

        self.asic_scan_status_var = tk.StringVar(value="Ready for private-LAN discovery.")
        ttk.Label(
            controls,
            textvariable=self.asic_scan_status_var,
            style="CardTitle.TLabel",
        ).grid(row=5, column=0, columnspan=9, sticky="w", pady=(10, 0))

        # Summary cards
        summary = ttk.Frame(frame)
        summary.pack(fill="x", pady=(0, 12))
        for col in range(8):
            summary.columnconfigure(col, weight=1)

        self.asic_count_var = tk.StringVar(value="0")
        self.asic_online_var = tk.StringVar(value="0")
        self.asic_hashrate_var = tk.StringVar(value="0 H/s")
        self.asic_hot_var = tk.StringVar(value="—")
        self.asic_alerts_var = tk.StringVar(value="0")
        self.asic_availability_var = tk.StringVar(value="—")
        self.asic_health_var = tk.StringVar(value="—")
        self.asic_offline_var = tk.StringVar(value="0")

        for title, var, col in (
            ("DEVICES", self.asic_count_var, 0),
            ("ONLINE", self.asic_online_var, 1),
            ("TOTAL HASHRATE", self.asic_hashrate_var, 2),
            ("MAX TEMP", self.asic_hot_var, 3),
            ("ALERTS", self.asic_alerts_var, 4),
            ("AVG AVAIL", self.asic_availability_var, 5),
            ("AVG HEALTH", self.asic_health_var, 6),
            ("OFFLINE", self.asic_offline_var, 7),
        ):
            self._metric_card(summary, title, var, 0, col)

        body = ttk.Frame(frame)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)

        # Device table
        list_outer = tk.Frame(body, bg=self.colors["card_edge"])
        list_outer.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        list_frame = ttk.Frame(list_outer, style="Card.TFrame", padding=12)
        list_frame.pack(fill="both", expand=True, padx=1, pady=1)

        header = ttk.Frame(list_frame, style="Card.TFrame")
        header.pack(fill="x")
        ttk.Label(header, text="MINERS", style="CardTitle.TLabel").pack(side="left")
        self.asic_table_status_var = tk.StringVar(value="No devices loaded.")
        ttk.Label(
            header,
            textvariable=self.asic_table_status_var,
            style="CardTitle.TLabel",
        ).pack(side="right")

        cols = ("ip", "alias", "group", "model", "verify", "status", "health", "hashrate", "temp", "fan", "availability", "offline", "pool")
        self.asic_tree = ttk.Treeview(list_frame, columns=cols, show="headings", height=15)
        for key, label in (
            ("ip", "IP"),
            ("alias", "ALIAS"),
            ("group", "GROUP"),
            ("model", "MODEL"),
            ("verify", "VERIFICATION"),
            ("status", "STATUS"),
            ("health", "HEALTH"),
            ("hashrate", "HASHRATE"),
            ("temp", "TEMP"),
            ("fan", "FAN"),
            ("availability", "AVAIL"),
            ("offline", "OFFLINE"),
            ("pool", "POOL"),
        ):
            self.asic_tree.heading(
                key,
                text=label,
                command=lambda k=key: self._asic_sort_by(k),
            )

        self.asic_tree.column("ip", width=115, stretch=False)
        self.asic_tree.column("alias", width=120)
        self.asic_tree.column("group", width=95)
        self.asic_tree.column("model", width=145)
        self.asic_tree.column("verify", width=125, stretch=False)
        self.asic_tree.column("status", width=90, stretch=False)
        self.asic_tree.column("health", width=70, anchor="e", stretch=False)
        self.asic_tree.column("hashrate", width=110, anchor="e", stretch=False)
        self.asic_tree.column("temp", width=80, anchor="e", stretch=False)
        self.asic_tree.column("fan", width=95, anchor="e", stretch=False)
        self.asic_tree.column("availability", width=70, anchor="e", stretch=False)
        self.asic_tree.column("offline", width=90, anchor="e", stretch=False)
        self.asic_tree.column("pool", width=170)
        self.asic_tree.pack(fill="both", expand=True, pady=(10, 0))
        self.asic_tree.bind("<<TreeviewSelect>>", self._asic_selected)

        # Detail panel
        detail_outer = tk.Frame(body, bg=self.colors["card_edge"])
        detail_outer.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        detail = ttk.Frame(detail_outer, style="Card.TFrame", padding=14)
        detail.pack(fill="both", expand=True, padx=1, pady=1)

        ttk.Label(detail, text="SELECTED MINER", style="CardTitle.TLabel").pack(anchor="w")

        self.asic_detail_ip = tk.StringVar(value="—")
        self.asic_detail_model = tk.StringVar(value="No miner selected")
        self.asic_detail_hash = tk.StringVar(value="—")
        self.asic_detail_temp = tk.StringVar(value="—")
        self.asic_detail_power = tk.StringVar(value="—")
        self.asic_detail_eff = tk.StringVar(value="—")
        self.asic_detail_uptime = tk.StringVar(value="—")
        self.asic_detail_pool = tk.StringVar(value="—")
        self.asic_detail_worker = tk.StringVar(value="—")
        self.asic_detail_latency = tk.StringVar(value="—")
        self.asic_detail_verify = tk.StringVar(value="—")
        self.asic_detail_caps = tk.StringVar(value="—")
        self.asic_detail_alias = tk.StringVar(value="—")
        self.asic_detail_group = tk.StringVar(value="—")
        self.asic_detail_availability = tk.StringVar(value="—")
        self.asic_detail_health = tk.StringVar(value="—")
        self.asic_detail_offline = tk.StringVar(value="—")
        self.asic_detail_alert = tk.StringVar(value="No active alerts")
        self.asic_detail_note = tk.StringVar(value="—")
        self.asic_health_explain_var = tk.StringVar(value="—")

        tk.Label(
            detail,
            textvariable=self.asic_detail_model,
            bg=self.colors["card"],
            fg="#FAF7FF",
            font=("Segoe UI Semibold", 16),
            anchor="w",
        ).pack(fill="x", pady=(7, 0))
        tk.Label(
            detail,
            textvariable=self.asic_detail_ip,
            bg=self.colors["card"],
            fg=self.colors["muted"],
            font=("Consolas", 11),
            anchor="w",
        ).pack(fill="x", pady=(1, 12))

        grid = tk.Frame(detail, bg=self.colors["card"])
        grid.pack(fill="x")
        rows = [
            ("Alias", self.asic_detail_alias),
            ("Group", self.asic_detail_group),
            ("Verification", self.asic_detail_verify),
            ("Capabilities", self.asic_detail_caps),
            ("Availability", self.asic_detail_availability),
            ("Health", self.asic_detail_health),
            ("Offline For", self.asic_detail_offline),
            ("Hashrate", self.asic_detail_hash),
            ("Temperature", self.asic_detail_temp),
            ("Power", self.asic_detail_power),
            ("Efficiency", self.asic_detail_eff),
            ("Uptime", self.asic_detail_uptime),
            ("Pool", self.asic_detail_pool),
            ("Worker", self.asic_detail_worker),
            ("API latency", self.asic_detail_latency),
            ("Note", self.asic_detail_note),
        ]
        for i, (label, var) in enumerate(rows):
            tk.Label(
                grid,
                text=label.upper(),
                bg=self.colors["card"],
                fg=self.colors["muted"],
                font=("Segoe UI Semibold", 9),
                anchor="w",
            ).grid(row=i, column=0, sticky="w", pady=5)
            tk.Label(
                grid,
                textvariable=var,
                bg=self.colors["card"],
                fg="#FAF7FF",
                font=("Segoe UI", 12),
                anchor="w",
                wraplength=300,
            ).grid(row=i, column=1, sticky="w", padx=(15, 0), pady=5)

        tk.Label(
            detail,
            text="HEALTH EXPLANATION",
            bg=self.colors["card"],
            fg=self.colors["muted"],
            font=("Segoe UI Semibold", 9),
            anchor="w",
        ).pack(fill="x", pady=(14, 4))

        tk.Label(
            detail,
            textvariable=self.asic_health_explain_var,
            bg="#171020",
            fg="#d9c9ef",
            font=("Segoe UI", 10),
            justify="left",
            anchor="w",
            wraplength=380,
            padx=9,
            pady=8,
        ).pack(fill="x")

        tk.Label(
            detail,
            text="HASHRATE TREND",
            bg=self.colors["card"],
            fg=self.colors["muted"],
            font=("Segoe UI Semibold", 9),
            anchor="w",
        ).pack(fill="x", pady=(16, 4))

        self.asic_chart = tk.Canvas(
            detail,
            height=110,
            bg=self.colors["entry"],
            highlightthickness=1,
            highlightbackground=self.colors["line"],
        )
        self.asic_chart.pack(fill="x")

        tk.Label(
            detail,
            text="TEMP / FAN TREND",
            bg=self.colors["card"],
            fg=self.colors["muted"],
            font=("Segoe UI Semibold", 9),
            anchor="w",
        ).pack(fill="x", pady=(10, 4))

        self.asic_temp_chart = tk.Canvas(
            detail,
            height=88,
            bg=self.colors["entry"],
            highlightthickness=1,
            highlightbackground=self.colors["line"],
        )
        self.asic_temp_chart.pack(fill="x")

        self.asic_alert_label = tk.Label(
            detail,
            textvariable=self.asic_detail_alert,
            bg="#171020",
            fg=self.colors["success"],
            font=("Segoe UI Semibold", 12),
            anchor="w",
            justify="left",
            wraplength=380,
            padx=9,
            pady=8,
        )
        self.asic_alert_label.pack(fill="x", pady=(8, 0))

        actions = tk.Frame(detail, bg=self.colors["card"])
        actions.pack(fill="x", pady=(12, 0))

        self.asic_refresh_one_btn = self._make_3d_button(
            actions, "Refresh", self._asic_refresh_selected, role="secondary"
        )
        self.asic_refresh_one_btn.pack(side="left", padx=(0, 6), pady=(0, 7))

        self.asic_alias_btn = self._make_3d_button(
            actions, "Set Alias", self._asic_set_alias, role="secondary"
        )
        self.asic_alias_btn.pack(side="left", padx=(0, 6), pady=(0, 7))

        self.asic_group_btn = self._make_3d_button(
            actions, "Set Group", self._asic_set_group, role="secondary"
        )
        self.asic_group_btn.pack(side="left", padx=(0, 6), pady=(0, 7))

        self.asic_note_btn = self._make_3d_button(
            actions, "Set Note", self._asic_set_note, role="secondary"
        )
        self.asic_note_btn.pack(side="left", padx=(0, 6), pady=(0, 7))

        self.asic_ack_btn = self._make_3d_button(
            actions, "Acknowledge Alerts", self._asic_acknowledge_alerts, role="secondary"
        )
        self.asic_ack_btn.pack(side="left", padx=(0, 6), pady=(0, 7))

        self.asic_web_btn = self._make_3d_button(
            actions, "Open Web UI", self._asic_open_web, role="teal"
        )
        self.asic_web_btn.pack(side="left", padx=(0, 6), pady=(0, 7))

        second = tk.Frame(detail, bg=self.colors["card"])
        second.pack(fill="x")

        self.asic_switch_pool_btn = self._make_3d_button(
            second, "Switch Pool", self._asic_switch_pool, role="primary"
        )
        self.asic_switch_pool_btn.pack(side="left", padx=(0, 6))

        self.asic_restart_btn = self._make_3d_button(
            second, "Restart Miner", self._asic_restart, role="danger"
        )
        self.asic_restart_btn.pack(side="left", padx=(0, 6))

        self.asic_remove_btn = self._make_3d_button(
            second, "Remove Device", self._asic_remove_selected, role="secondary"
        )
        self.asic_remove_btn.pack(side="left")

        timeline_outer = tk.Frame(frame, bg=self.colors["card_edge"])
        timeline_outer.pack(fill="x", pady=(12, 0))
        timeline = ttk.Frame(timeline_outer, style="Card.TFrame", padding=12)
        timeline.pack(fill="x", padx=1, pady=1)

        top = ttk.Frame(timeline, style="Card.TFrame")
        top.pack(fill="x")
        ttk.Label(top, text="ALERT / EVENT TIMELINE", style="CardTitle.TLabel").pack(side="left")

        self.asic_timeline_var = tk.StringVar(value="No fleet events yet.")
        ttk.Label(top, textvariable=self.asic_timeline_var, style="CardTitle.TLabel").pack(side="right")

        self.asic_event_tree = ttk.Treeview(
            timeline,
            columns=("time", "ip", "kind", "severity", "message"),
            show="headings",
            height=6,
        )
        for key, label in (
            ("time", "TIME"),
            ("ip", "IP"),
            ("kind", "EVENT"),
            ("severity", "SEVERITY"),
            ("message", "MESSAGE"),
        ):
            self.asic_event_tree.heading(key, text=label)

        self.asic_event_tree.column("time", width=90, stretch=False)
        self.asic_event_tree.column("ip", width=120, stretch=False)
        self.asic_event_tree.column("kind", width=110, stretch=False)
        self.asic_event_tree.column("severity", width=90, stretch=False)
        self.asic_event_tree.column("message", width=520)
        self.asic_event_tree.pack(fill="x", pady=(8, 0))

    def _asic_update_discovery_state(self):
        state = "normal" if self.asic_authorized_var.get() and not self._asic_busy else "disabled"
        self._set_action_button_state(self.asic_discover_btn, state)

    def _asic_selected_ip(self):
        selected = self.asic_tree.selection()
        if not selected:
            return None
        values = self.asic_tree.item(selected[0], "values")
        if not values:
            return None
        return str(values[0])

    def _asic_selected(self, _event=None):
        ip = self._asic_selected_ip()
        if not ip:
            return
        device = self.asic_devices.get(ip)
        if device:
            self._asic_show_detail(device)

    def _asic_show_detail(self, d):
        ip = d.get("ip", "")
        self.asic_detail_ip.set(ip or "—")
        self.asic_detail_model.set(d.get("model") or "Unknown network device")
        self.asic_detail_alias.set(self.asic_aliases.get(ip) or "—")
        self.asic_detail_group.set(self.asic_groups.get(ip) or "—")
        self.asic_detail_note.set(self.asic_notes.get(ip) or "—")

        availability = self.fleet_monitor.availability_percent(ip)
        self.asic_detail_availability.set(
            f"{availability:.1f}%" if availability is not None else "—"
        )

        health = self.fleet_monitor.health_score(
            d,
            temp_limit=self.asic_temp_alert_var.get(),
            drop_percent=self.asic_drop_alert_var.get(),
        )
        self.asic_detail_health.set(f"{health}/100")
        explanation = self.fleet_monitor.health_explanation(
            d,
            temp_limit=self.asic_temp_alert_var.get(),
            drop_percent=self.asic_drop_alert_var.get(),
        )
        self.asic_health_explain_var.set(explanation["summary"])

        offline_for = self.fleet_monitor.offline_duration_seconds(ip)
        self.asic_detail_offline.set(
            format_duration_compact(offline_for) if offline_for > 0 else "—"
        )

        verification = d.get("verification") or "UNVERIFIED"
        self.asic_detail_verify.set(verification)

        caps = []
        if d.get("api_verified"):
            caps.append("API")
        if d.get("http_available"):
            caps.append("HTTP")
        if d.get("https_available"):
            caps.append("HTTPS")
        if d.get("can_switch_pool"):
            caps.append("POOLS")
        if d.get("can_restart"):
            caps.append("CONTROL")
        self.asic_detail_caps.set(" • ".join(caps) if caps else "None verified")

        self.asic_detail_hash.set(format_hashrate(d.get("hashrate_hs", 0)))

        temp = d.get("temperature_c")
        self.asic_detail_temp.set(f"{temp:.1f} °C" if temp is not None else "—")

        power = d.get("power_w")
        self.asic_detail_power.set(f"{power:.0f} W" if power is not None else "—")

        eff = d.get("efficiency_j_th")
        self.asic_detail_eff.set(f"{eff:.1f} J/TH" if eff is not None else "—")

        self.asic_detail_uptime.set(
            format_uptime(d.get("uptime_s", 0)) if d.get("api_verified") else "—"
        )
        self.asic_detail_pool.set(d.get("pool_url") or "—")
        self.asic_detail_worker.set(d.get("pool_user") or "—")

        latency = d.get("latency_ms")
        if latency is None:
            self.asic_detail_latency.set("Timeout / unavailable")
        else:
            self.asic_detail_latency.set(f"{float(latency):.1f} ms")

        alerts = self.fleet_monitor.alerts(
            d,
            temp_limit=self.asic_temp_alert_var.get(),
            drop_percent=self.asic_drop_alert_var.get(),
        )
        acknowledged_active = self.fleet_monitor.alerts(
            d,
            temp_limit=self.asic_temp_alert_var.get(),
            drop_percent=self.asic_drop_alert_var.get(),
            include_acknowledged=True,
        )
        if alerts:
            text = "\n".join(a["message"] for a in alerts[:3])
            self.asic_detail_alert.set(text)
            if any(a["severity"] == "critical" for a in alerts):
                self.asic_alert_label.configure(fg="#ff70bd")
            else:
                self.asic_alert_label.configure(fg="#d3a6ff")
        else:
            if acknowledged_active:
                self.asic_detail_alert.set("Active alerts acknowledged")
                self.asic_alert_label.configure(fg=self.colors["muted"])
            else:
                self.asic_detail_alert.set("No active alerts")
                self.asic_alert_label.configure(fg=self.colors["success"])

        self._asic_draw_chart(ip)
        self._asic_draw_temp_fan_chart(ip)

        self._set_action_button_state(
            self.asic_web_btn,
            "normal" if d.get("can_open_web") else "disabled",
        )
        self._set_action_button_state(
            self.asic_switch_pool_btn,
            "normal" if d.get("can_switch_pool") else "disabled",
        )
        self._set_action_button_state(
            self.asic_restart_btn,
            "normal" if d.get("can_restart") else "disabled",
        )

    def _asic_draw_chart(self, ip):
        canvas = self.asic_chart
        canvas.delete("all")
        width = max(10, canvas.winfo_width())
        height = max(10, canvas.winfo_height())

        rows = self.fleet_monitor.recent(ip)[-60:]
        values = [float(r.get("hashrate_hs", 0) or 0) for r in rows]

        if len(values) < 2 or max(values) <= 0:
            canvas.create_text(
                width / 2,
                height / 2,
                text="No hashrate history yet",
                fill=self.colors["muted"],
                font=("Segoe UI", 10),
            )
            return

        maximum = max(values)
        minimum = min(values)
        span = max(1.0, maximum - minimum)

        points = []
        for i, value in enumerate(values):
            x = 6 + (width - 12) * (i / max(1, len(values) - 1))
            y = height - 6 - (height - 12) * ((value - minimum) / span)
            points.extend([x, y])

        if len(points) >= 4:
            canvas.create_line(
                *points,
                fill=self.colors["glow"],
                width=2,
                smooth=True,
            )

        canvas.create_text(
            8,
            8,
            anchor="nw",
            text=f"min {format_hashrate(minimum)}",
            fill=self.colors["muted"],
            font=("Segoe UI", 10),
        )
        canvas.create_text(
            width - 8,
            8,
            anchor="ne",
            text=f"max {format_hashrate(maximum)}",
            fill=self.colors["muted"],
            font=("Segoe UI", 10),
        )

    def _asic_draw_temp_fan_chart(self, ip):
        canvas = self.asic_temp_chart
        canvas.delete("all")
        width = max(10, canvas.winfo_width())
        height = max(10, canvas.winfo_height())

        rows = self.fleet_monitor.recent(ip)[-60:]
        temps = [r.get("temperature_c") for r in rows]
        fans = [r.get("fan_rpm") for r in rows]

        temp_vals = [float(v) if v is not None else None for v in temps]
        fan_vals = [float(v) if v is not None else None for v in fans]

        if not any(v is not None for v in temp_vals) and not any(v is not None for v in fan_vals):
            canvas.create_text(
                width / 2,
                height / 2,
                text="No temperature/fan history yet",
                fill=self.colors["muted"],
                font=("Segoe UI", 10),
            )
            return

        def draw_series(values, color, label, normalize_max):
            points = []
            for i, value in enumerate(values):
                if value is None:
                    continue
                x = 6 + (width - 12) * (i / max(1, len(values) - 1))
                y = height - 6 - (height - 12) * min(1.0, max(0.0, value / normalize_max))
                points.extend([x, y])
            if len(points) >= 4:
                canvas.create_line(*points, fill=color, width=2, smooth=True)
            canvas.create_text(
                8 if label == "TEMP" else width - 8,
                7,
                anchor="nw" if label == "TEMP" else "ne",
                text=label,
                fill=color,
                font=("Segoe UI Semibold", 9),
            )

        draw_series(temp_vals, self.colors["danger"], "TEMP", 120.0)
        draw_series(fan_vals, self.colors["teal"], "FAN", 10000.0)

    def _asic_update_table(self):
        selected_ip = self._asic_selected_ip()

        for item in self.asic_tree.get_children():
            self.asic_tree.delete(item)

        devices = sorted(
            self.asic_devices.values(),
            key=lambda d: tuple(int(x) for x in d.get("ip", "0.0.0.0").split(".")),
        )

        # Refresh group filter options.
        groups = sorted({g for g in self.asic_groups.values() if g})
        values = ["All"] + groups
        self.asic_group_filter_combo.configure(values=values)
        if self.asic_group_filter_var.get() not in values:
            self.asic_group_filter_var.set("All")

        search = self.asic_search_var.get().strip().lower()
        group_filter = self.asic_group_filter_var.get()

        filtered = []
        for d in devices:
            ip = d.get("ip", "")
            alias = self.asic_aliases.get(ip, "")
            group = self.asic_groups.get(ip, "")
            haystack = " ".join([
                ip,
                alias,
                group,
                d.get("model", ""),
                d.get("status", ""),
                d.get("verification", ""),
                d.get("pool_url", ""),
                d.get("pool_user", ""),
            ]).lower()

            if search and search not in haystack:
                continue
            if group_filter != "All" and group != group_filter:
                continue
            filtered.append(d)

        def sort_value(d):
            ip = d.get("ip", "")
            col = self._asic_sort_column
            mapping = {
                "ip": tuple(int(x) for x in ip.split(".")) if ip else (0, 0, 0, 0),
                "alias": self.asic_aliases.get(ip, "").lower(),
                "group": self.asic_groups.get(ip, "").lower(),
                "model": str(d.get("model", "")).lower(),
                "verify": str(d.get("verification", "")).lower(),
                "status": str(d.get("status", "")).lower(),
                "health": self.fleet_monitor.health_score(
                    d,
                    temp_limit=self.asic_temp_alert_var.get(),
                    drop_percent=self.asic_drop_alert_var.get(),
                ),
                "hashrate": float(d.get("hashrate_hs", 0) or 0),
                "temp": float(d.get("temperature_c", -1) or -1),
                "fan": float(d.get("fan_rpm", -1) or -1),
                "availability": float(self.fleet_monitor.availability_percent(ip) or -1),
                "offline": float(self.fleet_monitor.offline_duration_seconds(ip) or 0),
                "pool": str(d.get("pool_url", "")).lower(),
            }
            return mapping.get(col, mapping["ip"])

        filtered.sort(key=sort_value, reverse=self._asic_sort_reverse)

        total_hashrate = 0.0
        online = 0
        temps = []
        alert_count = 0
        availability_values = []
        health_values = []
        offline_count = 0

        selected_item = None
        for d in filtered:
            ip = d.get("ip", "")
            if d.get("status") in ("Online", "Web UI only"):
                online += 1
            if d.get("status") == "Offline":
                offline_count += 1

            total_hashrate += float(d.get("hashrate_hs", 0) or 0)

            temp = d.get("temperature_c")
            if temp is not None:
                temps.append(float(temp))

            availability = self.fleet_monitor.availability_percent(ip)
            if availability is not None:
                availability_values.append(availability)

            health = self.fleet_monitor.health_score(
                d,
                temp_limit=self.asic_temp_alert_var.get(),
                drop_percent=self.asic_drop_alert_var.get(),
            )
            health_values.append(health)

            alerts = self.fleet_monitor.alerts(
                d,
                temp_limit=self.asic_temp_alert_var.get(),
                drop_percent=self.asic_drop_alert_var.get(),
            )
            alert_count += len(alerts)

            offline_seconds = self.fleet_monitor.offline_duration_seconds(ip)

            item = self.asic_tree.insert(
                "",
                "end",
                values=(
                    ip,
                    self.asic_aliases.get(ip, ""),
                    self.asic_groups.get(ip, ""),
                    d.get("model", "Unknown"),
                    d.get("verification", "UNVERIFIED"),
                    d.get("status", ""),
                    f"{health}/100",
                    format_hashrate(d.get("hashrate_hs", 0)),
                    f"{temp:.1f} °C" if temp is not None else "—",
                    f"{d.get('fan_rpm'):.0f} RPM" if d.get("fan_rpm") is not None else "—",
                    f"{availability:.0f}%" if availability is not None else "—",
                    format_duration_compact(offline_seconds) if offline_seconds > 0 else "—",
                    d.get("pool_url") or "—",
                ),
            )
            if ip == selected_ip:
                selected_item = item

        self.asic_count_var.set(str(len(filtered)))
        self.asic_online_var.set(str(online))
        self.asic_hashrate_var.set(format_hashrate(total_hashrate))
        self.asic_hot_var.set(f"{max(temps):.1f} °C" if temps else "—")
        self.asic_alerts_var.set(str(alert_count))
        self.asic_availability_var.set(
            f"{sum(availability_values)/len(availability_values):.1f}%"
            if availability_values else "—"
        )
        self.asic_health_var.set(
            f"{sum(health_values)/len(health_values):.0f}/100"
            if health_values else "—"
        )
        self.asic_offline_var.set(str(offline_count))
        self.asic_table_status_var.set(
            f"{len(filtered)} shown • {online} online"
            if filtered else "No devices match the current filter."
        )

        self._asic_refresh_timeline()

        if selected_item:
            self.asic_tree.selection_set(selected_item)
            self.asic_tree.focus(selected_item)
            self._asic_selected()
        elif filtered:
            first = self.asic_tree.get_children()[0]
            self.asic_tree.selection_set(first)
            self.asic_tree.focus(first)
            self._asic_selected()
        else:
            self.asic_detail_ip.set("—")
            self.asic_detail_model.set("No miner selected")
            for var in (
                self.asic_detail_hash, self.asic_detail_temp, self.asic_detail_power,
                self.asic_detail_eff, self.asic_detail_uptime, self.asic_detail_pool,
                self.asic_detail_worker, self.asic_detail_latency,
                self.asic_detail_verify, self.asic_detail_caps,
                self.asic_detail_alias, self.asic_detail_group,
                self.asic_detail_availability, self.asic_detail_health,
                self.asic_detail_offline, self.asic_detail_note,
            ):
                var.set("—")
            self.asic_health_explain_var.set("—")
            self.asic_detail_alert.set("No active alerts")
            self.asic_chart.delete("all")
            self.asic_temp_chart.delete("all")
            self._set_action_button_state(self.asic_web_btn, "disabled")
            self._set_action_button_state(self.asic_switch_pool_btn, "disabled")
            self._set_action_button_state(self.asic_restart_btn, "disabled")

    def _asic_sort_by(self, column):
        if self._asic_sort_column == column:
            self._asic_sort_reverse = not self._asic_sort_reverse
        else:
            self._asic_sort_column = column
            self._asic_sort_reverse = False
        self._asic_update_table()

    def _asic_refresh_timeline(self):
        for item in self.asic_event_tree.get_children():
            self.asic_event_tree.delete(item)

        events = self.fleet_monitor.recent_events(50)
        for e in events:
            ts = time.strftime("%H:%M:%S", time.localtime(e.get("ts", time.time())))
            self.asic_event_tree.insert(
                "",
                "end",
                values=(
                    ts,
                    e.get("ip", ""),
                    e.get("kind", ""),
                    e.get("severity", ""),
                    e.get("message", ""),
                ),
            )
        self.asic_timeline_var.set(
            f"{len(events)} recent event(s)" if events else "No fleet events yet."
        )

    def _asic_load_known_devices(self):
        ips = sorted(self.asic_known_devices)
        if not ips:
            return
        self.asic_scan_status_var.set(f"Loading {len(ips)} known device(s) …")
        for ip in ips:
            threading.Thread(target=self._asic_query_thread, args=(ip,), daemon=True).start()

    def _asic_discover(self):
        if not self.asic_authorized_var.get():
            messagebox.showwarning(
                "ASIC Discovery",
                "Confirm that you own or administer the devices on this private network first.",
            )
            return
        if self._asic_busy:
            return

        cidr = self.asic_subnet_var.get().strip()
        self._asic_busy = True
        self._asic_update_discovery_state()
        self.asic_scan_status_var.set(f"Scanning {cidr} …")
        self._log(f"ASIC discovery started on {cidr}.")
        threading.Thread(target=self._asic_discover_thread, args=(cidr,), daemon=True).start()

    def _asic_discover_thread(self, cidr):
        def progress(done, total):
            if done == total or done % 20 == 0:
                self.ui_queue.put(("asic_progress", done, total))

        try:
            discovered = discover_devices(cidr, progress_callback=progress)
            enriched = []

            for probe in discovered:
                ip = probe["ip"]

                # Only call it a verified ASIC if the compatible API actually responds.
                if probe.get("cgminer"):
                    try:
                        device = query_device(ip)
                        if device.get("api_verified"):
                            enriched.append(device)
                            continue
                    except Exception:
                        pass

                # Web-only devices are queried so we can classify known miner web UIs.
                if probe.get("http") or probe.get("https"):
                    try:
                        device = query_device(ip)
                        if device.get("web_available"):
                            enriched.append(device)
                            continue
                    except Exception:
                        pass

                enriched.append(classify_probe(probe))

            self.ui_queue.put(("asic_discovered", enriched, cidr))
        except Exception as exc:
            self.ui_queue.put(("asic_error", str(exc)))

    def _asic_add_manual(self):
        value = simpledialog.askstring(
            "Add ASIC",
            "Private/local IPv4 address:",
            parent=self,
        )
        if not value:
            return
        try:
            ip = ensure_private_host(value.strip())
        except Exception as exc:
            messagebox.showerror("Add ASIC", str(exc))
            return

        self.asic_scan_status_var.set(f"Querying {ip} …")
        threading.Thread(target=self._asic_query_thread, args=(ip,), daemon=True).start()

    def _asic_query_thread(self, ip):
        try:
            device = query_device(ip)
            self.ui_queue.put(("asic_device", device))
        except Exception as exc:
            self.ui_queue.put(("asic_error", f"{ip}: {exc}"))

    def _asic_refresh_selected(self):
        ip = self._asic_selected_ip()
        if not ip:
            messagebox.showinfo("ASIC Control", "Select a miner first.")
            return
        self.asic_scan_status_var.set(f"Refreshing {ip} …")
        threading.Thread(target=self._asic_query_thread, args=(ip,), daemon=True).start()

    def _asic_refresh_all(self):
        if self._asic_busy or not self.asic_devices:
            return
        self._asic_busy = True
        self._asic_update_discovery_state()
        ips = list(self.asic_devices.keys())
        self.asic_scan_status_var.set(f"Refreshing {len(ips)} miner(s) …")
        threading.Thread(target=self._asic_refresh_all_thread, args=(ips,), daemon=True).start()

    def _asic_refresh_all_thread(self, ips):
        results = []
        for ip in ips:
            try:
                results.append(query_device(ip))
            except Exception:
                previous = dict(self.asic_devices.get(ip, {}))
                if previous.get("api_verified") or previous.get("web_available"):
                    previous["status"] = "Offline"
                else:
                    previous["status"] = "Unknown"
                    previous["verification"] = previous.get("verification") or "UNVERIFIED"
                previous["latency_ms"] = None
                results.append(previous)
        self.ui_queue.put(("asic_refreshed", results))

    def _asic_set_note(self):
        ip = self._asic_selected_ip()
        if not ip:
            messagebox.showinfo("ASIC Control", "Select a device first.")
            return

        current = self.asic_notes.get(ip, "")
        value = simpledialog.askstring(
            "Set Device Note",
            f"Note for {ip}:",
            initialvalue=current,
            parent=self,
        )
        if value is None:
            return

        value = value.strip()
        if value:
            self.asic_notes[ip] = value[:200]
        else:
            self.asic_notes.pop(ip, None)

        if ip in self.asic_devices:
            self._asic_show_detail(self.asic_devices[ip])
        self._save_fields()

    def _asic_export_config(self):
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Export ASIC Fleet Configuration",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialfile="bitcoin-miner-studio-fleet-config.json",
        )
        if not path:
            return

        payload = {
            "version": 1,
            "known_devices": sorted(self.asic_known_devices),
            "aliases": dict(self.asic_aliases),
            "groups": dict(self.asic_groups),
            "notes": dict(self.asic_notes),
            "subnet": self.asic_subnet_var.get().strip(),
            "refresh_seconds": int(self.asic_refresh_seconds_var.get()),
            "temp_alert_c": float(self.asic_temp_alert_var.get()),
            "hashrate_drop_percent": float(self.asic_drop_alert_var.get()),
        }

        try:
            Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
            self._log(f"ASIC fleet config exported: {path}")
        except Exception as exc:
            messagebox.showerror("Export Config", str(exc))

    def _asic_import_config(self):
        path = filedialog.askopenfilename(
            parent=self,
            title="Import ASIC Fleet Configuration",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return

        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            devices = payload.get("known_devices", [])
            aliases = payload.get("aliases", {})
            groups = payload.get("groups", {})
            notes = payload.get("notes", {})

            if not isinstance(devices, list):
                raise ValueError("known_devices must be a list.")
            if not isinstance(aliases, dict) or not isinstance(groups, dict) or not isinstance(notes, dict):
                raise ValueError("aliases/groups/notes must be objects.")

            safe_devices = set()
            for ip in devices:
                try:
                    safe_devices.add(ensure_private_host(str(ip)))
                except Exception:
                    continue

            self.asic_known_devices.update(safe_devices)
            self.asic_aliases.update({str(k): str(v)[:40] for k, v in aliases.items()})
            self.asic_groups.update({str(k): str(v)[:40] for k, v in groups.items()})
            self.asic_notes.update({str(k): str(v)[:200] for k, v in notes.items()})

            subnet = payload.get("subnet")
            if subnet:
                self.asic_subnet_var.set(str(subnet))

            if "refresh_seconds" in payload:
                self.asic_refresh_seconds_var.set(max(5, int(payload["refresh_seconds"])))
            if "temp_alert_c" in payload:
                self.asic_temp_alert_var.set(float(payload["temp_alert_c"]))
            if "hashrate_drop_percent" in payload:
                self.asic_drop_alert_var.set(float(payload["hashrate_drop_percent"]))

            self._save_fields()
            self._asic_update_table()
            self._asic_load_known_devices()
            self._log(f"ASIC fleet config imported: {path}")
        except Exception as exc:
            messagebox.showerror("Import Config", str(exc))

    def _asic_acknowledge_alerts(self):
        ip = self._asic_selected_ip()
        if not ip:
            messagebox.showinfo("ASIC Control", "Select a device first.")
            return

        device = self.asic_devices.get(ip)
        if not device:
            return

        alerts = self.fleet_monitor.alerts(
            device,
            temp_limit=self.asic_temp_alert_var.get(),
            drop_percent=self.asic_drop_alert_var.get(),
        )
        if not alerts:
            messagebox.showinfo("Alerts", "There are no unacknowledged alerts for this device.")
            return

        self.fleet_monitor.acknowledge_all(ip)
        self._asic_show_detail(device)
        self._asic_update_table()
        self._log(f"ASIC Control: acknowledged alerts for {ip}.")

    def _asic_set_alias(self):
        ip = self._asic_selected_ip()
        if not ip:
            messagebox.showinfo("ASIC Control", "Select a device first.")
            return

        current = self.asic_aliases.get(ip, "")
        value = simpledialog.askstring(
            "Set Alias",
            f"Alias for {ip}:",
            initialvalue=current,
            parent=self,
        )
        if value is None:
            return

        value = value.strip()
        if value:
            self.asic_aliases[ip] = value[:40]
        else:
            self.asic_aliases.pop(ip, None)

        self._asic_update_table()
        if ip in self.asic_devices:
            self._asic_show_detail(self.asic_devices[ip])
        self._save_fields()

    def _asic_set_group(self):
        ip = self._asic_selected_ip()
        if not ip:
            messagebox.showinfo("ASIC Control", "Select a device first.")
            return

        current = self.asic_groups.get(ip, "")
        value = simpledialog.askstring(
            "Set Group",
            f"Group for {ip}:",
            initialvalue=current,
            parent=self,
        )
        if value is None:
            return

        value = value.strip()
        if value:
            self.asic_groups[ip] = value[:40]
        else:
            self.asic_groups.pop(ip, None)

        self._asic_update_table()
        if ip in self.asic_devices:
            self._asic_show_detail(self.asic_devices[ip])
        self._save_fields()

    def _asic_export_json(self):
        if not self.asic_devices:
            messagebox.showinfo("Export Fleet", "No ASIC devices are loaded.")
            return
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Export ASIC Fleet JSON",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialfile="bitcoin-miner-studio-fleet.json",
        )
        if not path:
            return
        try:
            export_fleet_json(
                path,
                self.asic_devices,
                self.fleet_monitor,
                self.asic_aliases,
                self.asic_groups,
            )
            self._log(f"ASIC fleet JSON exported: {path}")
        except Exception as exc:
            messagebox.showerror("Export Fleet", str(exc))

    def _asic_export_csv(self):
        if not self.asic_devices:
            messagebox.showinfo("Export Fleet", "No ASIC devices are loaded.")
            return
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Export ASIC Fleet CSV",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialfile="bitcoin-miner-studio-fleet.csv",
        )
        if not path:
            return
        try:
            export_fleet_csv(
                path,
                self.asic_devices,
                self.fleet_monitor,
                self.asic_aliases,
                self.asic_groups,
            )
            self._log(f"ASIC fleet CSV exported: {path}")
        except Exception as exc:
            messagebox.showerror("Export Fleet", str(exc))

    def _asic_remove_selected(self):
        ip = self._asic_selected_ip()
        if not ip:
            messagebox.showinfo("ASIC Control", "Select a device first.")
            return
        if not messagebox.askyesno(
            "Remove Device",
            f"Remove {ip} from the current ASIC Control Center list?\n\n"
            "This does not change the device or its network configuration.",
        ):
            return

        self.asic_devices.pop(ip, None)
        self.asic_known_devices.discard(ip)
        self.asic_aliases.pop(ip, None)
        self.asic_groups.pop(ip, None)
        self.asic_notes.pop(ip, None)
        self._asic_update_table()
        self._save_fields()
        self.asic_scan_status_var.set(f"Removed {ip} from the current list.")
        self._log(f"ASIC Control: removed {ip} from the current device list.")

    def _asic_open_web(self):
        ip = self._asic_selected_ip()
        if not ip:
            messagebox.showinfo("ASIC Control", "Select a miner first.")
            return
        d = self.asic_devices.get(ip, {})
        if not d.get("can_open_web"):
            messagebox.showinfo(
                "ASIC Control",
                "No HTTP/HTTPS management interface was verified for this device.",
            )
            return
        scheme = d.get("web_scheme") or ("https" if d.get("https_available") else "http")
        webbrowser.open(f"{scheme}://{ip}/")

    def _asic_restart(self):
        ip = self._asic_selected_ip()
        if not ip:
            messagebox.showinfo("ASIC Control", "Select a miner first.")
            return
        d = self.asic_devices.get(ip, {})
        if not d.get("can_restart"):
            messagebox.showinfo(
                "Restart Miner",
                "Privileged compatible API control was not verified for this device.",
            )
            return
        if not messagebox.askyesno(
            "Restart Miner",
            f"Restart the miner process on {ip}?\n\n"
            "This requires privileged cgminer API access and may briefly interrupt mining.",
        ):
            return

        self.asic_scan_status_var.set(f"Sending restart command to {ip} …")
        threading.Thread(target=self._asic_restart_thread, args=(ip,), daemon=True).start()

    def _asic_restart_thread(self, ip):
        try:
            response = restart_miner(ip)
            self.ui_queue.put(("asic_action", f"Restart command sent to {ip}: {response}"))
        except Exception as exc:
            self.ui_queue.put(("asic_error", f"Restart failed for {ip}: {exc}"))

    def _asic_switch_pool(self):
        ip = self._asic_selected_ip()
        if not ip:
            messagebox.showinfo("ASIC Control", "Select a miner first.")
            return
        d = self.asic_devices.get(ip, {})
        if not d.get("can_switch_pool"):
            messagebox.showinfo(
                "Switch Pool",
                "Pool-control capability was not verified for this device.",
            )
            return
        pools = d.get("pools") or []
        if not pools:
            messagebox.showinfo(
                "Switch Pool",
                "This miner did not expose a pool list through its compatible API.",
            )
            return

        lines = []
        for i, pool in enumerate(pools):
            url = pool.get("URL", pool.get("Stratum URL", ""))
            user = pool.get("User", "")
            lines.append(f"{i}: {url}  [{user}]")

        index = simpledialog.askinteger(
            "Switch Pool",
            "Configured pools:\n\n" + "\n".join(lines[:10]) + "\n\nPool index to activate:",
            parent=self,
            minvalue=0,
            maxvalue=max(0, len(pools) - 1),
        )
        if index is None:
            return

        if not messagebox.askyesno(
            "Switch Pool",
            f"Switch miner {ip} to configured pool #{index}?",
        ):
            return

        threading.Thread(
            target=self._asic_switch_pool_thread,
            args=(ip, index),
            daemon=True,
        ).start()

    def _asic_switch_pool_thread(self, ip, index):
        try:
            response = switch_pool(ip, index)
            self.ui_queue.put(("asic_action", f"Pool switch sent to {ip}: {response}"))
            time.sleep(0.4)
            try:
                device = query_device(ip)
                self.ui_queue.put(("asic_device", device))
            except Exception:
                pass
        except Exception as exc:
            self.ui_queue.put(("asic_error", f"Pool switch failed for {ip}: {exc}"))

    def _asic_auto_tick(self):
        if not self.winfo_exists():
            return
        try:
            if (
                hasattr(self, "asic_auto_var")
                and self.asic_auto_var.get()
                and self.asic_devices
                and not self._asic_busy
            ):
                self._asic_refresh_all()
        except Exception:
            pass

        try:
            interval = max(5, int(self.asic_refresh_seconds_var.get()))
        except Exception:
            interval = 10
        self._asic_auto_after = self.after(interval * 1000, self._asic_auto_tick)

    def _build_pool_tab(self):
        frame = ttk.Frame(self.pool_tab, padding=24)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Pool Mining", style="PageTitle.TLabel").grid(
            row=0, column=0, columnspan=4, sticky="w"
        )
        ttk.Label(
            frame,
            text="Connect, authorize, receive Stratum work, and submit qualifying shares.",
            style="PageSub.TLabel",
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(4, 20))

        self.pool_url = tk.StringVar(value=self.cfg.get("pool_url", "stratum+tcp://example.com:3333"))
        self.pool_worker = tk.StringVar(value=self.cfg.get("pool_worker", "wallet.worker1"))
        self.pool_password = tk.StringVar(value=self.saved_pool_password)

        fields = [
            ("Pool URL", self.pool_url, False),
            ("Worker / wallet", self.pool_worker, False),
            ("Password", self.pool_password, True),
        ]
        for row, (label, var, secret) in enumerate(fields, start=2):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=7)
            ttk.Entry(frame, textvariable=var, width=68, show="*" if secret else "").grid(
                row=row, column=1, columnspan=2, sticky="ew", padx=(12, 12), pady=7
            )

        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(2, weight=1)

        self.suggest_diff_enabled = tk.BooleanVar(value=bool(self.cfg.get("suggest_difficulty_enabled", False)))
        self.suggest_diff_value = tk.DoubleVar(value=float(self.cfg.get("suggest_difficulty", 1.0)))
        ttk.Checkbutton(
            frame,
            text="Request lower share difficulty (pool may ignore)",
            variable=self.suggest_diff_enabled,
        ).grid(row=5, column=1, sticky="w", pady=(10, 0))
        ttk.Spinbox(
            frame,
            from_=0.0000001,
            to=1000000000,
            increment=0.1,
            width=16,
            textvariable=self.suggest_diff_value,
        ).grid(row=5, column=2, sticky="w", pady=(10, 0))

        self.test_pool_btn = self._make_3d_button(frame, "Test Pool", self._test_pool, role="secondary")
        self.test_pool_btn.grid(row=6, column=1, sticky="w", pady=(14, 0))
        self.pool_start_tab_btn = self._make_3d_button(frame, "Start Mining", self._start_mining, role="primary")
        self.pool_start_tab_btn.grid(row=6, column=2, sticky="w", pady=(14, 0))
        self.local_pool_btn = self._make_3d_button(
            frame, "Start Local Test Pool", self._toggle_local_pool, role="teal"
        )
        self.local_pool_btn.grid(row=6, column=3, sticky="w", pady=(14, 0))

        self.local_pool_status = tk.StringVar(value="Local test pool: stopped")
        tk.Label(
            frame,
            textvariable=self.local_pool_status,
            bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 9)
        ).grid(row=7, column=0, columnspan=4, sticky="w", pady=(12, 0))

        tk.Label(
            frame,
            text=f"Credential storage: {backend_name()}. Passwords are not written to settings.json.",
            bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 9)
        ).grid(row=8, column=0, columnspan=4, sticky="w", pady=(14, 8))

        self.pool_result = tk.Text(
            frame, height=14, bg=self.colors["entry"], fg="#efe7ff", insertbackground="#FAF7FF",
            relief="flat", font=("Consolas", 11), padx=14, pady=14,
            highlightthickness=1, highlightbackground=self.colors["line"]
        )
        self.pool_result.grid(row=9, column=0, columnspan=4, sticky="nsew", pady=(8, 0))
        frame.rowconfigure(9, weight=1)

    def _build_node_tab(self):
        frame = ttk.Frame(self.node_tab, padding=24)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Bitcoin Core", style="PageTitle.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w"
        )
        ttk.Label(
            frame,
            text="Test a local Bitcoin Core RPC endpoint and verify node connectivity.",
            style="PageSub.TLabel",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 20))

        self.rpc_url = tk.StringVar(value=self.cfg.get("rpc_url", "http://127.0.0.1:8332"))
        self.rpc_user = tk.StringVar(value=self.cfg.get("rpc_user", "bitcoinrpc"))
        self.rpc_password = tk.StringVar(value=self.saved_rpc_password)

        fields = [
            ("RPC URL", self.rpc_url, False),
            ("RPC user", self.rpc_user, False),
            ("RPC password", self.rpc_password, True),
        ]
        for row, (label, var, secret) in enumerate(fields, start=2):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=7)
            ttk.Entry(frame, textvariable=var, width=62, show="*" if secret else "").grid(
                row=row, column=1, sticky="ew", padx=(12, 12), pady=7
            )

        frame.columnconfigure(1, weight=1)
        self.test_node_btn = self._make_3d_button(frame, "Test Bitcoin Core", self._test_node, role="secondary")
        self.test_node_btn.grid(row=5, column=1, sticky="w", pady=(16, 0))

        tk.Label(
            frame,
            text=f"Credential storage: {backend_name()}. Passwords are not written to settings.json.",
            bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 9)
        ).grid(row=6, column=0, columnspan=3, sticky="w", pady=(14, 8))

        self.node_result = tk.Text(
            frame, height=13, bg=self.colors["entry"], fg="#efe7ff", insertbackground="#FAF7FF",
            relief="flat", font=("Consolas", 11), padx=14, pady=14,
            highlightthickness=1, highlightbackground=self.colors["line"]
        )
        self.node_result.grid(row=7, column=0, columnspan=3, sticky="nsew", pady=(8, 0))
        frame.rowconfigure(7, weight=1)

    def _build_log_tab(self):
        frame = ttk.Frame(self.log_tab, padding=18)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Logs", style="PageTitle.TLabel").pack(anchor="w")
        ttk.Label(
            frame,
            text="Protocol, pool, benchmark, and diagnostic events.",
            style="PageSub.TLabel",
        ).pack(anchor="w", pady=(4, 12))

        self.log_box = tk.Text(
            frame, bg=self.colors["entry"], fg="#efe7ff", insertbackground="#FAF7FF",
            relief="flat", font=("Consolas", 11), padx=14, pady=14,
            highlightthickness=1, highlightbackground=self.colors["line"]
        )
        self.log_box.pack(fill="both", expand=True)
        self._log(f"{APP_NAME} v{VERSION} initialized.")
        self._log("v0.3.14 adds the requested layered 3D button shadow: #491B76 depth, purple soft shadow, and a white inset highlight.")

    def _start_mining(self):
        if self.benchmark.running:
            self._stop_benchmark()
        if self.miner.running:
            return

        try:
            self._save_fields()
            suggested = self.suggest_diff_value.get() if self.suggest_diff_enabled.get() else None
            self.miner.start(
                self.pool_url.get(),
                self.pool_worker.get(),
                self.pool_password.get(),
                self.mining_processes_var.get(),
                suggest_difficulty=suggested,
            )
        except Exception as exc:
            messagebox.showerror("Mining error", str(exc))
            return

        self.start_mining_btn.configure(state="disabled")
        self.pool_start_tab_btn.configure(state="disabled")
        self.stop_mining_btn.configure(state="normal")
        self.start_benchmark_btn.configure(state="disabled")
        self.reset_session_btn.configure(state="disabled")
        self._log("Pool mining started.")

    def _stop_mining(self):
        self.miner.stop()
        self.start_mining_btn.configure(state="normal")
        self.pool_start_tab_btn.configure(state="normal")
        self.stop_mining_btn.configure(state="disabled")
        self.start_benchmark_btn.configure(state="normal")
        self.reset_session_btn.configure(state="normal")
        self._refresh_mining_stats(self.miner.stats())
        self._log("Pool mining stopped; session statistics retained until Reset Session.")

    def _start_benchmark(self):
        if self.miner.running:
            self._stop_mining()
        n = max(1, min(64, int(self.benchmark_processes_var.get())))
        try:
            self.benchmark.start(n)
        except Exception as exc:
            messagebox.showerror("Benchmark error", str(exc))
            return
        self.status_var.set("Benchmarking")
        self.workers_var.set(str(n))
        self.start_benchmark_btn.configure(state="disabled")
        self.stop_benchmark_btn.configure(state="normal")
        self.start_mining_btn.configure(state="disabled")
        self.pool_start_tab_btn.configure(state="disabled")
        self._log(f"Started local benchmark with {n} process(es).")

    def _stop_benchmark(self):
        self.benchmark.stop()
        self.status_var.set("Idle")
        self.workers_var.set("0")
        self.start_benchmark_btn.configure(state="normal")
        self.stop_benchmark_btn.configure(state="disabled")
        self.start_mining_btn.configure(state="normal")
        self.pool_start_tab_btn.configure(state="normal")
        self._log("Benchmark stopped.")

    def _toggle_local_pool(self):
        if self.local_pool.running:
            if self.miner.running and self.pool_url.get().startswith("stratum+tcp://127.0.0.1:"):
                self._stop_mining()
            self.local_pool.stop()
            self.local_pool_status.set("Local test pool: stopped")
            self.local_pool_btn.configure(text="Start Local Test Pool")
            self._update_mode_badge()
            return

        try:
            endpoint = self.local_pool.start()
        except Exception as exc:
            messagebox.showerror("Local test pool", str(exc))
            return

        self.pool_url.set(endpoint)
        self.pool_worker.set("local.worker1")
        self.pool_password.set("x")
        self.suggest_diff_enabled.set(False)
        self.local_pool_status.set(
            f"Local test pool: RUNNING at {endpoint} • difficulty {self.local_pool.difficulty:g}"
        )
        self.local_pool_btn.configure(text="Stop Local Test Pool")
        self._update_mode_badge()
        self._save_fields()
        self._log("Pool fields switched to the local validation server.")

    def _reset_session_stats(self):
        if self.miner.running:
            messagebox.showinfo("Reset Session", "Stop pool mining before resetting session statistics.")
            return
        try:
            self.miner.reset_stats()
        except Exception as exc:
            messagebox.showerror("Reset Session", str(exc))
            return
        for item in self.share_tree.get_children():
            self.share_tree.delete(item)
        self.share_summary_var.set("No submitted shares yet.")
        self._refresh_mining_stats(self.miner.stats())
        self._log("Mining session statistics reset.")

    def _update_mode_badge(self):
        pool = self.pool_url.get().strip() if hasattr(self, "pool_url") else ""
        local = self.local_pool.running and pool.startswith("stratum+tcp://127.0.0.1:")
        if local:
            self.mode_var.set("LOCAL TEST")
            self.mode_badge.configure(bg="#7c3aed")
        elif pool and "example.com" not in pool:
            self.mode_var.set("REAL POOL")
            self.mode_badge.configure(bg="#14b8a6")
        else:
            self.mode_var.set("READY")
            self.mode_badge.configure(bg="#433062")

    def _refresh_recent_shares(self, rows):
        existing = self.share_tree.get_children()
        for item in existing:
            self.share_tree.delete(item)
        for row in list(rows)[:30]:
            result = str(row.get("result", "")).upper()
            self.share_tree.insert(
                "",
                "end",
                values=(
                    row.get("time", ""),
                    result,
                    row.get("job_id", ""),
                    row.get("nonce", ""),
                    f"{float(row.get('response_ms', 0.0)):.1f} ms",
                ),
            )

    def _refresh_mining_stats(self, stats):
        self.hashrate_var.set(format_hashrate(stats.get("hashrate", 0)))
        self.avg_hashrate_var.set(format_hashrate(stats.get("average_hashrate", 0)))
        self.peak_hashrate_var.set(format_hashrate(stats.get("peak_hashrate", 0)))
        self.accepted_var.set(str(stats.get("accepted", 0)))
        self.rejected_var.set(str(stats.get("rejected", 0)))
        self.stale_var.set(str(stats.get("stale", 0)))
        self.submitted_var.set(str(stats.get("submitted", 0)))

        decided = (
            int(stats.get("accepted", 0))
            + int(stats.get("rejected", 0))
            + int(stats.get("stale", 0))
        )
        self.acceptance_var.set(
            f"{stats.get('acceptance_rate', 0.0):.1f}%" if decided else "—"
        )

        self.difficulty_var.set(format_difficulty(stats.get("difficulty", 0)))
        self.share_eta_var.set(
            format_duration_estimate(stats.get("expected_share_seconds", 0))
        )
        self.total_hashes_var.set(f"{int(stats.get('total_hashes', 0)):,}")
        self.workers_var.set(str(stats.get("workers", 0)))
        self.uptime_var.set(format_uptime(stats.get("uptime", 0)))
        self.status_var.set(stats.get("status", "Idle"))
        self.endpoint_var.set(stats.get("endpoint") or "No pool session")
        latency = float(stats.get("connect_latency_ms", 0.0) or 0.0)
        self.latency_var.set(f"{latency:.1f} ms" if latency > 0 else "—")
        self.job_var.set(stats.get("job_id") or "—")
        self.share_summary_var.set(
            f"{stats.get('accepted', 0)} accepted • "
            f"{stats.get('rejected', 0)} rejected • "
            f"{stats.get('stale', 0)} stale • "
            f"{stats.get('job_count', 0)} jobs"
        )
        self._refresh_recent_shares(stats.get("recent_shares", []))
        self._update_mode_badge()

    def _test_pool(self):
        self._save_fields()
        self.pool_result.delete("1.0", "end")
        self.pool_result.insert("end", "Connecting...\n")
        threading.Thread(target=self._pool_test_thread, daemon=True).start()

    def _pool_test_thread(self):
        try:
            result = test_stratum(self.pool_url.get(), self.pool_worker.get(), self.pool_password.get())
            self.ui_queue.put(("pool_test", result))
        except Exception as exc:
            self.ui_queue.put(("pool_test", f"ERROR: {exc}"))

    def _test_node(self):
        self._save_fields()
        self.node_result.delete("1.0", "end")
        self.node_result.insert("end", "Connecting...\n")
        threading.Thread(target=self._node_test_thread, daemon=True).start()

    def _node_test_thread(self):
        try:
            result = test_bitcoin_core(self.rpc_url.get(), self.rpc_user.get(), self.rpc_password.get())
            self.ui_queue.put(("node_test", result))
        except Exception as exc:
            self.ui_queue.put(("node_test", f"ERROR: {exc}"))

    def _save_fields(self):
        self.cfg.update({
            "pool_url": self.pool_url.get().strip(),
            "pool_worker": self.pool_worker.get().strip(),
            "rpc_url": self.rpc_url.get().strip(),
            "rpc_user": self.rpc_user.get().strip(),
            "benchmark_processes": int(self.benchmark_processes_var.get()),
            "mining_processes": int(self.mining_processes_var.get()),
            "suggest_difficulty_enabled": bool(self.suggest_diff_enabled.get()),
            "suggest_difficulty": float(self.suggest_diff_value.get()),
            "local_test_difficulty": float(self.local_pool.difficulty),
            "asic_subnet": self.asic_subnet_var.get().strip(),
            "asic_refresh_seconds": int(self.asic_refresh_seconds_var.get()),
            "asic_aliases": dict(self.asic_aliases),
            "asic_groups": dict(self.asic_groups),
            "asic_notes": dict(self.asic_notes),
            "asic_known_devices": sorted(self.asic_known_devices),
            "asic_temp_alert_c": float(self.asic_temp_alert_var.get()),
            "asic_hashrate_drop_percent": float(self.asic_drop_alert_var.get()),
            "ui_scale_mode": self.ui_scale_var.get().strip()
                if hasattr(self, "ui_scale_var")
                else self.ui_scale_mode,
        })
        save_config(self.cfg)

        try:
            write_secret(POOL_TARGET, self.pool_worker.get().strip(), self.pool_password.get())
        except Exception as exc:
            self._log(f"Could not save pool credential: {exc}")
        try:
            write_secret(RPC_TARGET, self.rpc_user.get().strip(), self.rpc_password.get())
        except Exception as exc:
            self._log(f"Could not save RPC credential: {exc}")

    def _tick(self):
        if self.miner.running:
            self._refresh_mining_stats(self.miner.stats())
        elif self.benchmark.running:
            stats = self.benchmark.stats()
            self.hashrate_var.set(format_hashrate(stats["hashrate"]))
            self.avg_hashrate_var.set("—")
            self.peak_hashrate_var.set("—")
            self.accepted_var.set("—")
            self.rejected_var.set("—")
            self.stale_var.set("—")
            self.submitted_var.set("—")
            self.acceptance_var.set("—")
            self.difficulty_var.set("Benchmark")
            self.share_eta_var.set("—")
            self.total_hashes_var.set(f'{int(stats["total_hashes"]):,}')
            self.workers_var.set(str(self.benchmark_processes_var.get()))
            self.status_var.set("Benchmarking")
            self.endpoint_var.set("Local SHA-256d benchmark")
            self.latency_var.set("—")
            self.job_var.set("—")
            self.mode_var.set("BENCHMARK")
            self.mode_badge.configure(bg="#5f46d8")
        else:
            # Retain the last completed pool-mining session on screen.
            retained = self.miner.stats()
            if retained.get("total_hashes", 0) or retained.get("submitted", 0):
                self._refresh_mining_stats(retained)
            else:
                self.hashrate_var.set("0 H/s")
                self.avg_hashrate_var.set("0 H/s")
                self.peak_hashrate_var.set("0 H/s")
                self.accepted_var.set("0")
                self.rejected_var.set("0")
                self.stale_var.set("0")
                self.submitted_var.set("0")
                self.acceptance_var.set("—")
                self.difficulty_var.set("—")
                self.share_eta_var.set("—")
                self.total_hashes_var.set("0")
                self.uptime_var.set("00:00:00")
                self.workers_var.set("0")
                self.status_var.set("Idle")
                self.endpoint_var.set("No pool session")
                self.latency_var.set("—")
                self.job_var.set("—")
                self.share_summary_var.set("No submitted shares yet.")
                self._update_mode_badge()

        while True:
            try:
                item = self.ui_queue.get_nowait()
            except queue.Empty:
                break

            if item[0] == "pool_test":
                self.pool_result.delete("1.0", "end")
                self.pool_result.insert("end", item[1])
                self._log("Pool connectivity test completed.")
            elif item[0] == "node_test":
                self.node_result.delete("1.0", "end")
                self.node_result.insert("end", item[1])
                self._log("Bitcoin Core RPC test completed.")
            elif item[0] == "miner":
                _, kind, payload = item
                if kind == "log":
                    self._log(payload)
                elif kind == "share":
                    result = payload.get("result", "")
                    if result in ("accepted", "rejected", "stale"):
                        # Refresh from the engine's canonical retained history.
                        self._refresh_mining_stats(self.miner.stats())
            elif item[0] == "local_pool":
                _, kind, payload = item
                if kind == "log":
                    self._log(payload)
            elif item[0] == "asic_progress":
                _, done, total = item
                self.asic_scan_status_var.set(f"Scanning private LAN … {done}/{total}")
            elif item[0] == "asic_discovered":
                _, devices, cidr = item
                for d in devices:
                    self.asic_devices[d["ip"]] = d
                    self.asic_known_devices.add(d["ip"])
                    self.fleet_monitor.record(d)
                self._asic_busy = False
                self._asic_update_discovery_state()
                self._asic_update_table()
                self.asic_scan_status_var.set(
                    f"Discovery complete on {cidr}: {len(devices)} candidate device(s)."
                )
                self._log(
                    f"ASIC discovery complete on {cidr}; {len(devices)} device(s) detected."
                )
            elif item[0] == "asic_refreshed":
                _, devices = item
                for d in devices:
                    if d.get("ip"):
                        self.asic_devices[d["ip"]] = d
                        self.asic_known_devices.add(d["ip"])
                        self.fleet_monitor.record(d)
                self._asic_busy = False
                self._asic_update_discovery_state()
                self._asic_update_table()
                self.asic_scan_status_var.set(
                    f"Refreshed {len(devices)} miner(s)."
                )
            elif item[0] == "asic_device":
                _, device = item
                self.asic_devices[device["ip"]] = device
                self.asic_known_devices.add(device["ip"])
                self.fleet_monitor.record(device)
                self._asic_update_table()
                self.asic_scan_status_var.set(
                    f"{device['ip']} refreshed: {device.get('status', 'Unknown')}."
                )
            elif item[0] == "asic_action":
                _, message = item
                self.asic_scan_status_var.set(message)
                self._log(message)
            elif item[0] == "asic_error":
                _, message = item
                self._asic_busy = False
                self._asic_update_discovery_state()
                self.asic_scan_status_var.set(message)
                self._log("ASIC Control: " + message)

        self.after(250, self._tick)


    def _log(self, text):
        if not hasattr(self, "log_box"):
            return
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")

    def _on_close(self):
        try:
            if self._asic_auto_after is not None:
                self.after_cancel(self._asic_auto_after)
        except Exception:
            pass
        try:
            self._save_fields()
        except Exception:
            pass
        try:
            self.miner.stop()
        except Exception:
            pass
        try:
            self.benchmark.stop()
        except Exception:
            pass
        try:
            self.local_pool.stop()
        except Exception:
            pass
        self.destroy()


def format_hashrate(value):
    units = ["H/s", "kH/s", "MH/s", "GH/s", "TH/s", "PH/s", "EH/s"]
    v = float(value)
    for unit in units:
        if v < 1000.0 or unit == units[-1]:
            return f"{v:,.2f} {unit}"
        v /= 1000.0
    return f"{v:,.2f} EH/s"


def format_difficulty(value):
    try:
        v = float(value)
    except Exception:
        return "—"
    if v >= 1_000_000_000_000:
        return f"{v / 1_000_000_000_000:.2f} T"
    if v >= 1_000_000_000:
        return f"{v / 1_000_000_000:.2f} G"
    if v >= 1_000_000:
        return f"{v / 1_000_000:.2f} M"
    if v >= 1_000:
        return f"{v / 1_000:.2f} K"
    return f"{v:g}"


def format_uptime(seconds):
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def format_duration_estimate(seconds):
    try:
        seconds = float(seconds)
    except Exception:
        return "—"
    if seconds <= 0:
        return "—"
    if seconds < 1:
        return "<1 sec"
    if seconds < 60:
        return f"~{seconds:.0f} sec"
    minutes = seconds / 60
    if minutes < 60:
        return f"~{minutes:.1f} min"
    hours = minutes / 60
    if hours < 48:
        return f"~{hours:.1f} hr"
    days = hours / 24
    if days < 730:
        return f"~{days:.1f} days"
    years = days / 365.25
    return f"~{years:.1f} years"


def format_duration_compact(seconds):
    try:
        seconds = max(0, int(float(seconds)))
    except Exception:
        return "—"
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h"
    days = hours // 24
    return f"{days}d"


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    App().mainloop()
