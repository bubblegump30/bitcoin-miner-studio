"""Bitcoin Miner Studio v1.5.0 — Windows Tray & Background Monitoring.

The tray is a local Windows UI companion only. It exposes window-management and
read-only status surfaces. It intentionally has no mining-start, ASIC-control,
pool-switch, wallet, credential, or block-submission command.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

TRAY_SCHEMA = 1
MIN_POLL_SECONDS = 5
MAX_POLL_SECONDS = 300

DEFAULT_TRAY_SETTINGS = {
    "tray_enabled": True,
    "tray_minimize_to_tray": True,
    "tray_close_to_tray": False,
    "tray_notifications_enabled": True,
    "tray_poll_seconds": 10,
}


def normalize_tray_settings(values=None):
    values = dict(values or {})
    out = dict(DEFAULT_TRAY_SETTINGS)
    for key in ("tray_enabled", "tray_minimize_to_tray", "tray_close_to_tray", "tray_notifications_enabled"):
        if key in values:
            out[key] = bool(values.get(key))
    try:
        poll = int(values.get("tray_poll_seconds", out["tray_poll_seconds"]))
    except (TypeError, ValueError):
        poll = out["tray_poll_seconds"]
    out["tray_poll_seconds"] = max(MIN_POLL_SECONDS, min(MAX_POLL_SECONDS, poll))
    return out


def build_tray_status(snapshot=None):
    """Return privacy-safe status text/severity from local in-memory telemetry."""
    s = dict(snapshot or {})
    pool_running = bool(s.get("pool_running"))
    pool_health = max(0.0, min(100.0, float(s.get("pool_health") or 0))) if pool_running else 100.0
    solo_running = bool(s.get("solo_running"))
    core_connected = bool(s.get("core_connected"))
    asic_total = max(0, int(s.get("asic_total") or 0))
    asic_online = max(0, min(asic_total, int(s.get("asic_online") or 0)))
    security_checked = bool(s.get("security_checked"))
    security_verified = bool(s.get("security_verified"))

    severity = "ok"
    alerts = []
    if security_checked and not security_verified:
        severity = "critical"
        alerts.append("Security locked")
    if solo_running and not core_connected:
        severity = "critical" if severity != "critical" else severity
        alerts.append("Core offline during solo")
    if pool_running and pool_health < 70:
        if severity == "ok": severity = "warning"
        alerts.append(f"Pool health {pool_health:.0f}%")
    if asic_total and asic_online < asic_total:
        if severity == "ok": severity = "warning"
        alerts.append(f"ASIC {asic_online}/{asic_total} online")

    pool_text = f"Pool {pool_health:.0f}%" if pool_running else "Pool idle"
    core_text = "Core online" if core_connected else "Core offline"
    asic_text = f"ASIC {asic_online}/{asic_total}" if asic_total else "ASIC none"
    summary = " · ".join((pool_text, core_text, asic_text))
    title = "Bitcoin Miner Studio"
    if severity == "critical": title = "Bitcoin Miner Studio — Attention"
    elif severity == "warning": title = "Bitcoin Miner Studio — Warning"

    return {
        "schema": TRAY_SCHEMA,
        "severity": severity,
        "title": title,
        "summary": summary,
        "detail": "; ".join(alerts) if alerts else "Local monitoring is healthy.",
        "pool_running": pool_running,
        "pool_health": pool_health,
        "pool_failovers": int(s.get("pool_failovers") or 0),
        "solo_running": solo_running,
        "core_connected": core_connected,
        "core_height": int(s.get("core_height") or 0),
        "asic_total": asic_total,
        "asic_online": asic_online,
        "security_checked": security_checked,
        "security_verified": security_verified,
    }


class WindowsTrayManager:
    """Dependency-free Shell_NotifyIcon wrapper with a small local status monitor."""
    WM_TRAY = 0x8000 + 85
    WM_CLOSE = 0x0010
    WM_LBUTTONDBLCLK = 0x0203
    WM_RBUTTONUP = 0x0205
    NIM_ADD = 0x00000000
    NIM_MODIFY = 0x00000001
    NIM_DELETE = 0x00000002
    NIM_SETVERSION = 0x00000004
    NIF_MESSAGE = 0x00000001
    NIF_ICON = 0x00000002
    NIF_TIP = 0x00000004
    NIF_INFO = 0x00000010
    NIIF_INFO = 0x00000001
    NIIF_WARNING = 0x00000002
    NIIF_ERROR = 0x00000003
    NOTIFYICON_VERSION_4 = 4

    def __init__(self, icon_path, status_provider=None, show_callback=None, hide_callback=None, exit_callback=None, settings=None):
        self.icon_path = Path(icon_path)
        self.status_provider = status_provider
        self.show_callback = show_callback
        self.hide_callback = hide_callback
        self.exit_callback = exit_callback
        self.settings = normalize_tray_settings(settings)
        self.supported = sys.platform == "win32"
        self.running = False
        self.hidden = False
        self.exit_requested = False
        self.error = ""
        self.last_status = build_tray_status({})
        self.last_notification = ""
        self.last_notification_at = 0.0
        self._previous_snapshot = None
        self._thread = None
        self._monitor_thread = None
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._hwnd = None
        self._nid = None
        self._shell32 = None
        self._user32 = None
        self._wndproc_ref = None
        self._class_name = f"BitcoinMinerStudioTray_{os.getpid()}"

    def state(self):
        return {
            "schema": TRAY_SCHEMA,
            "supported": self.supported,
            "platform": sys.platform,
            "running": bool(self.running),
            "hidden": bool(self.hidden),
            "exit_requested": bool(self.exit_requested),
            "error": str(self.error or ""),
            "settings": dict(self.settings),
            "status": dict(self.last_status or {}),
            "last_notification": self.last_notification,
            "last_notification_at": float(self.last_notification_at or 0),
        }

    def update_settings(self, values=None):
        previous_enabled = bool(self.settings.get("tray_enabled"))
        self.settings = normalize_tray_settings({**self.settings, **dict(values or {})})
        enabled = bool(self.settings.get("tray_enabled"))
        if self.supported:
            if enabled and not self.running:
                self.start()
            elif previous_enabled and not enabled and self.running:
                self.stop()
        return self.state()

    def should_minimize_to_tray(self):
        return bool(self.supported and self.running and self.settings.get("tray_enabled") and self.settings.get("tray_minimize_to_tray"))

    def should_close_to_tray(self):
        return bool(self.supported and self.running and self.settings.get("tray_enabled") and self.settings.get("tray_close_to_tray") and not self.exit_requested)

    def start(self):
        if not self.supported:
            self.error = "Windows system tray is available only on Windows."
            return False
        if not self.settings.get("tray_enabled"):
            return False
        if self.running or (self._thread and self._thread.is_alive()):
            return True
        self._stop.clear(); self._ready.clear(); self.error = ""
        self._thread = threading.Thread(target=self._run_windows, name="BitcoinMinerStudioTray", daemon=True)
        self._thread.start()
        self._ready.wait(3.0)
        return bool(self.running)

    def stop(self):
        self._stop.set()
        try:
            if self._hwnd and self._user32:
                self._user32.PostMessageW(self._hwnd, self.WM_CLOSE, 0, 0)
        except Exception:
            pass
        thread = self._thread
        if thread and thread.is_alive() and threading.current_thread() is not thread:
            thread.join(timeout=2.0)
        self.running = False
        return True

    def show_window(self):
        try:
            if callable(self.show_callback): self.show_callback()
            self.hidden = False
            return True
        except Exception as exc:
            self.error = str(exc); return False

    def hide_window(self):
        if not (self.supported and self.running and self.settings.get("tray_enabled")):
            return False
        try:
            if callable(self.hide_callback): self.hide_callback()
            self.hidden = True
            return True
        except Exception as exc:
            self.error = str(exc); return False

    def request_exit(self):
        self.exit_requested = True
        try:
            if callable(self.exit_callback): self.exit_callback()
            return True
        except Exception as exc:
            self.error = str(exc); return False

    def test_notification(self):
        return self.notify("Bitcoin Miner Studio", "Tray notifications are working. Background monitoring remains local to this PC.", "info", force=True)

    def notify(self, title, message, severity="info", force=False):
        if not self.supported or not self.running or not self.settings.get("tray_notifications_enabled"):
            return False
        now = time.time()
        fingerprint = f"{severity}|{title}|{message}"
        if not force and fingerprint == self.last_notification and (now - self.last_notification_at) < 60:
            return False
        try:
            if not (self._nid and self._shell32): return False
            self._nid.uFlags = self.NIF_INFO
            self._nid.szInfoTitle = str(title or "Bitcoin Miner Studio")[:63]
            self._nid.szInfo = str(message or "")[:255]
            self._nid.dwInfoFlags = self.NIIF_ERROR if severity == "critical" else (self.NIIF_WARNING if severity == "warning" else self.NIIF_INFO)
            ok = bool(self._shell32.Shell_NotifyIconW(self.NIM_MODIFY, self._nid))
            if ok:
                self.last_notification = fingerprint
                self.last_notification_at = now
            return ok
        except Exception as exc:
            self.error = str(exc); return False

    def _status_snapshot(self):
        try:
            raw = self.status_provider() if callable(self.status_provider) else {}
            status = build_tray_status(raw)
            self.last_status = status
            return status
        except Exception as exc:
            self.error = str(exc)
            status = build_tray_status({})
            status["severity"] = "warning"
            status["detail"] = f"Background status unavailable: {exc}"
            self.last_status = status
            return status

    def _monitor_loop(self):
        while not self._stop.is_set():
            current = self._status_snapshot()
            self._update_tooltip(current.get("summary") or "Bitcoin Miner Studio")
            previous = self._previous_snapshot
            if previous is not None:
                self._notify_transition(previous, current)
            self._previous_snapshot = dict(current)
            self._stop.wait(int(self.settings.get("tray_poll_seconds") or 10))

    def _notify_transition(self, previous, current):
        if not self.settings.get("tray_notifications_enabled"): return
        if int(current.get("pool_failovers") or 0) > int(previous.get("pool_failovers") or 0):
            self.notify("Pool failover", "Miner Studio moved to another configured pool endpoint.", "warning")
            return
        if bool(previous.get("core_connected")) and not bool(current.get("core_connected")):
            self.notify("Bitcoin Core disconnected", "The previously connected local Bitcoin Core RPC is now offline.", "warning")
            return
        if not bool(previous.get("core_connected")) and bool(current.get("core_connected")):
            self.notify("Bitcoin Core recovered", f"Local Bitcoin Core is online at height {int(current.get('core_height') or 0):,}.", "info")
            return
        if int(previous.get("asic_total") or 0) and int(current.get("asic_online") or 0) < int(previous.get("asic_online") or 0):
            self.notify("ASIC fleet warning", current.get("summary") or "An ASIC became unavailable.", "warning")
            return
        if previous.get("severity") != current.get("severity") and current.get("severity") in {"warning", "critical"}:
            self.notify(current.get("title") or "Bitcoin Miner Studio", current.get("detail") or current.get("summary") or "Health warning", current.get("severity"))

    def _update_tooltip(self, text):
        try:
            if not (self._nid and self._shell32): return
            self._nid.uFlags = self.NIF_TIP
            self._nid.szTip = ("Bitcoin Miner Studio\n" + str(text or ""))[:127]
            self._shell32.Shell_NotifyIconW(self.NIM_MODIFY, self._nid)
        except Exception:
            pass

    def _run_windows(self):
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            shell32 = ctypes.windll.shell32
            kernel32 = ctypes.windll.kernel32
            gdi32 = ctypes.windll.gdi32
            self._user32, self._shell32 = user32, shell32
            LRESULT = ctypes.c_ssize_t
            WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

            class WNDCLASSW(ctypes.Structure):
                _fields_ = [("style", wintypes.UINT),("lpfnWndProc", WNDPROC),("cbClsExtra", ctypes.c_int),("cbWndExtra", ctypes.c_int),("hInstance", wintypes.HINSTANCE),("hIcon", wintypes.HICON),("hCursor", wintypes.HANDLE),("hbrBackground", wintypes.HBRUSH),("lpszMenuName", wintypes.LPCWSTR),("lpszClassName", wintypes.LPCWSTR)]

            class NOTIFYICONDATAW(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.DWORD),("hWnd", wintypes.HWND),("uID", wintypes.UINT),("uFlags", wintypes.UINT),("uCallbackMessage", wintypes.UINT),("hIcon", wintypes.HICON),("szTip", wintypes.WCHAR*128),("dwState", wintypes.DWORD),("dwStateMask", wintypes.DWORD),("szInfo", wintypes.WCHAR*256),("uTimeoutOrVersion", wintypes.UINT),("szInfoTitle", wintypes.WCHAR*64),("dwInfoFlags", wintypes.DWORD),("guidItem", ctypes.c_byte*16),("hBalloonIcon", wintypes.HICON)]

            class POINT(ctypes.Structure):
                _fields_ = [("x", wintypes.LONG),("y", wintypes.LONG)]

            class MEASUREITEMSTRUCT(ctypes.Structure):
                _fields_ = [
                    ("CtlType", wintypes.UINT),
                    ("CtlID", wintypes.UINT),
                    ("itemID", wintypes.UINT),
                    ("itemWidth", wintypes.UINT),
                    ("itemHeight", wintypes.UINT),
                    ("itemData", ctypes.c_size_t),
                ]

            class DRAWITEMSTRUCT(ctypes.Structure):
                _fields_ = [
                    ("CtlType", wintypes.UINT),
                    ("CtlID", wintypes.UINT),
                    ("itemID", wintypes.UINT),
                    ("itemAction", wintypes.UINT),
                    ("itemState", wintypes.UINT),
                    ("hwndItem", wintypes.HWND),
                    ("hDC", wintypes.HDC),
                    ("rcItem", wintypes.RECT),
                    ("itemData", ctypes.c_size_t),
                ]

            class MENUINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("fMask", wintypes.DWORD),
                    ("dwStyle", wintypes.DWORD),
                    ("cyMax", wintypes.UINT),
                    ("hbrBack", wintypes.HBRUSH),
                    ("dwContextHelpID", wintypes.DWORD),
                    ("dwMenuData", ctypes.c_size_t),
                ]

            # ctypes defaults native function return values to 32-bit c_int.
            # Menu/Window handles are pointer-sized on 64-bit Windows, so an
            # untyped CreatePopupMenu() result can be truncated and produce an
            # empty/blank tray popup. Bind the Win32 menu APIs explicitly.
            HMENU = getattr(wintypes, "HMENU", wintypes.HANDLE)
            user32.CreatePopupMenu.argtypes = []
            user32.CreatePopupMenu.restype = HMENU
            user32.AppendMenuW.argtypes = [HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
            user32.AppendMenuW.restype = wintypes.BOOL
            user32.TrackPopupMenu.argtypes = [HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, ctypes.c_void_p]
            user32.TrackPopupMenu.restype = wintypes.UINT
            user32.DestroyMenu.argtypes = [HMENU]
            user32.DestroyMenu.restype = wintypes.BOOL
            user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
            user32.GetCursorPos.restype = wintypes.BOOL
            user32.SetForegroundWindow.argtypes = [wintypes.HWND]
            user32.SetForegroundWindow.restype = wintypes.BOOL
            user32.SetMenuInfo.argtypes = [HMENU, ctypes.POINTER(MENUINFO)]
            user32.SetMenuInfo.restype = wintypes.BOOL
            user32.FillRect.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.HBRUSH]
            user32.FillRect.restype = ctypes.c_int
            user32.DrawTextW.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(wintypes.RECT), wintypes.UINT]
            user32.DrawTextW.restype = ctypes.c_int
            gdi32.CreateSolidBrush.argtypes = [wintypes.DWORD]
            gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
            gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
            gdi32.DeleteObject.restype = wintypes.BOOL
            gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
            gdi32.SetBkMode.restype = ctypes.c_int
            gdi32.SetTextColor.argtypes = [wintypes.HDC, wintypes.DWORD]
            gdi32.SetTextColor.restype = wintypes.DWORD

            def rgb(red, green, blue):
                return int(red) | (int(green) << 8) | (int(blue) << 16)

            WM_DRAWITEM = 0x002B
            WM_MEASUREITEM = 0x002C
            ODT_MENU = 1
            ODS_SELECTED = 0x0001
            ODS_DISABLED = 0x0004
            DT_LEFT = 0x0000
            DT_VCENTER = 0x0004
            DT_SINGLELINE = 0x0020
            DT_NOPREFIX = 0x0800
            TRANSPARENT = 1

            menu_labels = {
                1001: "Open Bitcoin Miner Studio",
                1002: "Current Status",
                1003: "Hide Window",
                1099: "Exit",
            }
            menu_separators = {1901, 1902}
            menu_item_ids = set(menu_labels) | menu_separators

            def fill_rect(hdc, rect, color):
                brush = gdi32.CreateSolidBrush(color)
                if brush:
                    try:
                        user32.FillRect(hdc, ctypes.byref(rect), brush)
                    finally:
                        gdi32.DeleteObject(brush)

            def draw_owner_menu_item(draw):
                item_id = int(draw.itemID)
                rect = wintypes.RECT(
                    draw.rcItem.left,
                    draw.rcItem.top,
                    draw.rcItem.right,
                    draw.rcItem.bottom,
                )
                selected = bool(int(draw.itemState) & ODS_SELECTED)
                disabled = bool(int(draw.itemState) & ODS_DISABLED)

                background = rgb(66, 43, 96) if selected else rgb(29, 24, 42)
                fill_rect(draw.hDC, rect, background)

                if item_id in menu_separators:
                    middle = int((rect.top + rect.bottom) / 2)
                    line = wintypes.RECT(rect.left + 12, middle, max(rect.left + 13, rect.right - 12), middle + 1)
                    fill_rect(draw.hDC, line, rgb(78, 62, 108))
                    return

                label = menu_labels.get(item_id, "")
                if not label:
                    return
                gdi32.SetBkMode(draw.hDC, TRANSPARENT)
                text_color = rgb(150, 140, 165) if disabled else rgb(242, 237, 250)
                gdi32.SetTextColor(draw.hDC, text_color)
                text_rect = wintypes.RECT(rect.left + 14, rect.top, rect.right - 12, rect.bottom)
                user32.DrawTextW(
                    draw.hDC,
                    label,
                    -1,
                    ctypes.byref(text_rect),
                    DT_LEFT | DT_VCENTER | DT_SINGLELINE | DT_NOPREFIX,
                )

            def show_menu(hwnd):
                menu = user32.CreatePopupMenu()
                if not menu:
                    self.error = "CreatePopupMenu failed."
                    return

                MF_OWNERDRAW = 0x0100
                MF_DISABLED = 0x0002
                MF_GRAYED = 0x0001
                MIM_BACKGROUND = 0x00000002
                entries = (
                    (MF_OWNERDRAW, 1001),
                    (MF_OWNERDRAW, 1002),
                    (MF_OWNERDRAW | MF_DISABLED | MF_GRAYED, 1901),
                    (MF_OWNERDRAW, 1003),
                    (MF_OWNERDRAW | MF_DISABLED | MF_GRAYED, 1902),
                    (MF_OWNERDRAW, 1099),
                )
                menu_brush = gdi32.CreateSolidBrush(rgb(29, 24, 42))
                try:
                    if menu_brush:
                        info = MENUINFO()
                        info.cbSize = ctypes.sizeof(MENUINFO)
                        info.fMask = MIM_BACKGROUND
                        info.hbrBack = menu_brush
                        user32.SetMenuInfo(menu, ctypes.byref(info))

                    for flags, command_id in entries:
                        if not user32.AppendMenuW(menu, flags, command_id, None):
                            raise ctypes.WinError()
                    point = POINT()
                    if not user32.GetCursorPos(ctypes.byref(point)):
                        raise ctypes.WinError()
                    user32.SetForegroundWindow(hwnd)
                    TPM_RIGHTBUTTON, TPM_RETURNCMD = 0x0002, 0x0100
                    command = user32.TrackPopupMenu(
                        menu, TPM_RIGHTBUTTON | TPM_RETURNCMD,
                        point.x, point.y, 0, hwnd, None
                    )
                except Exception as exc:
                    self.error = f"Tray menu failed: {exc}"
                    command = 0
                finally:
                    user32.DestroyMenu(menu)
                    if menu_brush:
                        gdi32.DeleteObject(menu_brush)

                if command == 1001: self.show_window()
                elif command == 1002:
                    status = self._status_snapshot()
                    user32.MessageBoxW(None, f"{status.get('summary','')}\n\n{status.get('detail','')}", "Bitcoin Miner Studio — Current Status", 0x40)
                elif command == 1003: self.hide_window()
                elif command == 1099: self.request_exit()

            @WNDPROC
            def wndproc(hwnd, msg, wparam, lparam):
                if msg == WM_MEASUREITEM and lparam:
                    measure = ctypes.cast(lparam, ctypes.POINTER(MEASUREITEMSTRUCT)).contents
                    if int(measure.CtlType) == ODT_MENU and int(measure.itemID) in menu_item_ids:
                        measure.itemWidth = 248
                        measure.itemHeight = 10 if int(measure.itemID) in menu_separators else 32
                        return 1
                if msg == WM_DRAWITEM and lparam:
                    draw = ctypes.cast(lparam, ctypes.POINTER(DRAWITEMSTRUCT)).contents
                    if int(draw.CtlType) == ODT_MENU and int(draw.itemID) in menu_item_ids:
                        draw_owner_menu_item(draw)
                        return 1
                if msg == self.WM_TRAY:
                    event = int(lparam) & 0xFFFF
                    if event == self.WM_LBUTTONDBLCLK: self.show_window(); return 0
                    if event == self.WM_RBUTTONUP: show_menu(hwnd); return 0
                if msg == self.WM_CLOSE:
                    try:
                        if self._nid: shell32.Shell_NotifyIconW(self.NIM_DELETE, self._nid)
                    except Exception: pass
                    user32.DestroyWindow(hwnd); return 0
                if msg == 0x0002:
                    user32.PostQuitMessage(0); return 0
                return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

            self._wndproc_ref = wndproc
            hinstance = kernel32.GetModuleHandleW(None)
            wc = WNDCLASSW(); wc.lpfnWndProc = wndproc; wc.hInstance = hinstance; wc.lpszClassName = self._class_name
            user32.RegisterClassW(ctypes.byref(wc))
            hwnd = user32.CreateWindowExW(0, self._class_name, "Bitcoin Miner Studio Tray", 0, 0,0,0,0, None, None, hinstance, None)
            if not hwnd: raise RuntimeError("Could not create Windows tray host window.")
            self._hwnd = hwnd

            IMAGE_ICON, LR_LOADFROMFILE = 1, 0x0010
            icon = user32.LoadImageW(None, str(self.icon_path), IMAGE_ICON, 0, 0, LR_LOADFROMFILE)
            if not icon: raise RuntimeError(f"Could not load tray icon: {self.icon_path}")

            nid = NOTIFYICONDATAW(); nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW); nid.hWnd = hwnd; nid.uID = 1
            nid.uFlags = self.NIF_MESSAGE|self.NIF_ICON|self.NIF_TIP; nid.uCallbackMessage = self.WM_TRAY; nid.hIcon = icon
            nid.szTip = "Bitcoin Miner Studio"
            self._nid = nid
            if not shell32.Shell_NotifyIconW(self.NIM_ADD, nid): raise RuntimeError("Shell_NotifyIconW(NIM_ADD) failed.")
            nid.uTimeoutOrVersion = self.NOTIFYICON_VERSION_4; shell32.Shell_NotifyIconW(self.NIM_SETVERSION, nid)

            self.running = True; self._ready.set()
            self._monitor_thread = threading.Thread(target=self._monitor_loop, name="BitcoinMinerStudioTrayMonitor", daemon=True)
            self._monitor_thread.start()

            msg = wintypes.MSG()
            while not self._stop.is_set() and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg)); user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as exc:
            self.error = str(exc)
        finally:
            self.running = False; self._ready.set(); self._hwnd = None; self._nid = None
