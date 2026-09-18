from __future__ import annotations

import itertools
import json
import multiprocessing
import os
import queue
import sys
import threading
import traceback
import types
from pathlib import Path


# Advertise the public Windows runtime before importing the signed backend.
# Release Readiness uses these markers to validate the native WebView2 package
# instead of incorrectly requiring the legacy pywebview development runtime.
os.environ.setdefault("BMS_NATIVE_HOST", "1")
os.environ.setdefault("BMS_GUI_BACKEND", "microsoft-edge-webview2-direct")

# The native Windows host replaces pywebview entirely. Four existing backend
# methods import the name `webview` only to read these dialog constants, so
# provide a tiny compatibility module instead of installing pywebview/pythonnet.
_FAKE_WEBVIEW = types.ModuleType("webview")
_FAKE_WEBVIEW.OPEN_DIALOG = 10
_FAKE_WEBVIEW.FOLDER_DIALOG = 20
sys.modules.setdefault("webview", _FAKE_WEBVIEW)

_PROTOCOL_OUT = sys.stdout
sys.stdout = sys.stderr
_WRITE_LOCK = threading.Lock()
_HOST_WAITERS: dict[str, dict] = {}
_HOST_WAITERS_LOCK = threading.Lock()
_HOST_REQUEST_IDS = itertools.count(1)
_STOP = threading.Event()


def _emit(payload: dict) -> None:
    line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    with _WRITE_LOCK:
        _PROTOCOL_OUT.write(line + "\n")
        _PROTOCOL_OUT.flush()


def _host_event(action: str, **payload) -> None:
    _emit({"type": "host_event", "action": action, **payload})


class NativeWindowProxy:
    """Subset of the pywebview Window API used by the signed backend.

    Dialog requests cross the same private stdin/stdout channel used for normal
    API calls. No localhost HTTP listener, firewall rule, or browser extension
    is involved.
    """

    def create_file_dialog(self, dialog_type, allow_multiple=False, file_types=()):
        request_id = f"dialog-{next(_HOST_REQUEST_IDS)}"
        event = threading.Event()
        holder = {"event": event, "response": None}
        with _HOST_WAITERS_LOCK:
            _HOST_WAITERS[request_id] = holder

        _emit(
            {
                "type": "host_request",
                "id": request_id,
                "action": "file_dialog",
                "dialog_type": int(dialog_type),
                "allow_multiple": bool(allow_multiple),
                "file_types": list(file_types or ()),
            }
        )

        if not event.wait(120.0):
            with _HOST_WAITERS_LOCK:
                _HOST_WAITERS.pop(request_id, None)
            raise TimeoutError("The native Windows file picker did not respond.")

        with _HOST_WAITERS_LOCK:
            response = _HOST_WAITERS.pop(request_id, {}).get("response") or {}
        if not response.get("ok", False):
            error = str(response.get("error") or "Native Windows file picker failed.")
            raise RuntimeError(error)
        selected = response.get("selected")
        return list(selected) if selected else None


class NativeHostTrayManager:
    """Tray state/monitor adapter for the WinForms native host.

    The native C# host owns the actual NotifyIcon and ContextMenuStrip. Python
    provides settings, health state and notification events only, so there is
    exactly one Windows tray UI implementation in the release runtime.
    """

    def __init__(self, backend):
        from windows_tray import build_tray_status, normalize_tray_settings

        self.backend = backend
        self._build_tray_status = build_tray_status
        self._normalize_tray_settings = normalize_tray_settings
        self.settings = normalize_tray_settings(backend.cfg)
        self.supported = sys.platform == "win32"
        self.running = False
        self.hidden = False
        self.exit_requested = False
        self.error = ""
        self.last_status = {}
        self.last_notification = ""
        self.last_notification_at = 0.0
        self._previous_status = None
        self._stop = threading.Event()
        self._thread = None

    def _snapshot(self):
        try:
            self.last_status = self._build_tray_status(self.backend._tray_status_snapshot())
        except Exception as exc:
            self.error = str(exc)
            self.last_status = self._build_tray_status({})
            self.last_status["severity"] = "warning"
            self.last_status["detail"] = f"Background status unavailable: {exc}"
        return dict(self.last_status)

    def _state_payload(self, status=None):
        if status is None:
            status = self._snapshot()
        return {
            "schema": 1,
            "supported": bool(self.supported),
            "platform": sys.platform,
            "running": bool(self.running),
            "hidden": bool(self.hidden),
            "exit_requested": bool(self.exit_requested),
            "error": str(self.error or ""),
            "settings": dict(self.settings),
            "status": dict(status),
            "last_notification": self.last_notification,
            "last_notification_at": float(self.last_notification_at or 0),
        }

    def state(self):
        return self._state_payload()

    def start(self):
        if not self.supported or not self.settings.get("tray_enabled"):
            self.running = False
            return False
        if self.running:
            return True
        self._stop.clear()
        self.running = True
        self._thread = threading.Thread(target=self._monitor_loop, name="NativeHostTrayMonitor", daemon=True)
        self._thread.start()
        _host_event("tray_state", tray=self.state())
        return True

    def stop(self):
        self._stop.set()
        self.running = False
        thread = self._thread
        if thread and thread.is_alive() and threading.current_thread() is not thread:
            thread.join(timeout=2.0)
        self._thread = None
        return True

    def update_settings(self, values=None):
        previous_enabled = bool(self.settings.get("tray_enabled"))
        self.settings = self._normalize_tray_settings({**self.settings, **dict(values or {})})
        enabled = bool(self.settings.get("tray_enabled"))
        if enabled and not self.running:
            self.start()
        elif previous_enabled and not enabled and self.running:
            self.stop()
        state = self.state()
        _host_event("tray_state", tray=state)
        return state

    def should_minimize_to_tray(self):
        return bool(self.supported and self.running and self.settings.get("tray_enabled") and self.settings.get("tray_minimize_to_tray"))

    def should_close_to_tray(self):
        return bool(self.supported and self.running and self.settings.get("tray_enabled") and self.settings.get("tray_close_to_tray") and not self.exit_requested)

    def show_window(self):
        _host_event("show_window")
        self.hidden = False
        _host_event("tray_state", tray=self.state())
        return True

    def hide_window(self):
        if not (self.supported and self.running and self.settings.get("tray_enabled")):
            self.error = "Tray is disabled or unavailable."
            return False
        _host_event("hide_window")
        self.hidden = True
        _host_event("tray_state", tray=self.state())
        return True

    def request_exit(self):
        self.exit_requested = True
        _host_event("exit_app")
        return True

    def notify(self, title, message, severity="info", force=False):
        if not self.supported or not self.running or not self.settings.get("tray_notifications_enabled"):
            return False
        fingerprint = f"{severity}|{title}|{message}"
        import time
        now = time.time()
        if not force and fingerprint == self.last_notification and (now - self.last_notification_at) < 60:
            return False
        self.last_notification = fingerprint
        self.last_notification_at = now
        _host_event(
            "tray_notification",
            title=str(title or "Bitcoin Miner Studio"),
            message=str(message or ""),
            severity=str(severity or "info"),
        )
        return True

    def test_notification(self):
        return self.notify(
            "Bitcoin Miner Studio",
            "Tray notifications are working. Background monitoring remains local to this PC.",
            "info",
            force=True,
        )

    def _notify_transition(self, previous, current):
        if not self.settings.get("tray_notifications_enabled"):
            return
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
            self.notify(
                current.get("title") or "Bitcoin Miner Studio",
                current.get("detail") or current.get("summary") or "Health warning",
                current.get("severity"),
            )

    def _monitor_loop(self):
        while not self._stop.is_set():
            current = self._snapshot()
            previous = self._previous_status
            if previous is not None:
                self._notify_transition(previous, current)
            self._previous_status = dict(current)
            _host_event("tray_state", tray=self._state_payload(current))
            self._stop.wait(int(self.settings.get("tray_poll_seconds") or 10))


class NativeTrayBridge:
    """Expose native-host tray state without creating a second tray icon."""

    def __init__(self, backend, icon_path: Path):
        self.backend = backend
        self.manager = NativeHostTrayManager(backend)
        backend._attach_tray_manager(self.manager)

    def publish_settings(self) -> None:
        _host_event("tray_state", tray=self.manager.state())

    def start_if_enabled_async(self) -> None:
        if self.manager.settings.get("tray_enabled"):
            self.manager.start()
        else:
            self.publish_settings()

def _handle_call(backend, tray_bridge: NativeTrayBridge, request: dict) -> None:
    request_id = request.get("id")
    method_name = str(request.get("method") or "")
    args = request.get("args")
    if not isinstance(args, list):
        args = []

    try:
        from api_contract import EXPOSED_API_METHODS

        if method_name not in EXPOSED_API_METHODS:
            raise PermissionError(f"Bridge method is not exposed by API contract: {method_name}")
        method = getattr(backend, method_name, None)
        if not callable(method):
            raise AttributeError(f"Backend method is unavailable: {method_name}")

        result = method(*args)
        _emit({"type": "response", "id": request_id, "ok": True, "result": result})

        if method_name == "save_tray_settings":
            tray_bridge.publish_settings()
    except Exception as exc:
        _emit(
            {
                "type": "response",
                "id": request_id,
                "ok": False,
                "error": str(exc),
                "error_type": type(exc).__name__,
            }
        )


def _reader_loop(backend, tray_bridge: NativeTrayBridge) -> None:
    for raw in sys.stdin:
        if _STOP.is_set():
            break
        raw = raw.strip()
        if not raw:
            continue
        try:
            message = json.loads(raw)
        except Exception:
            print(f"Ignoring malformed native-host message: {raw[:200]}", file=sys.stderr)
            continue

        msg_type = str(message.get("type") or "")
        if msg_type == "host_response":
            request_id = str(message.get("id") or "")
            with _HOST_WAITERS_LOCK:
                holder = _HOST_WAITERS.get(request_id)
                if holder is not None:
                    holder["response"] = message
                    holder["event"].set()
            continue

        if msg_type == "shutdown":
            _STOP.set()
            break

        if msg_type == "call":
            threading.Thread(
                target=_handle_call,
                args=(backend, tray_bridge, message),
                name=f"NativeApi-{message.get('method', 'call')}",
                daemon=True,
            ).start()

    _STOP.set()


def main() -> int:
    multiprocessing.freeze_support()

    try:
        from api_contract import API_SCHEMA, EXPOSED_API_METHODS
        from webview_app import APP_ICON_RELATIVE, VERSION, WebBackend

        root = Path(__file__).resolve().parent.parent
        backend = WebBackend()
        backend.window = NativeWindowProxy()
        tray_bridge = NativeTrayBridge(backend, root / APP_ICON_RELATIVE)

        _emit(
            {
                "type": "ready",
                "version": VERSION,
                "api_schema": API_SCHEMA,
                "exposed_methods": len(EXPOSED_API_METHODS),
                "transport": "stdio-json-v1",
                "gui_backend": os.environ["BMS_GUI_BACKEND"],
            }
        )
        tray_bridge.start_if_enabled_async()

        _reader_loop(backend, tray_bridge)
        try:
            backend.close()
        except Exception:
            traceback.print_exc(file=sys.stderr)
        return 0
    except Exception as exc:
        _emit(
            {
                "type": "fatal",
                "error": str(exc),
                "error_type": type(exc).__name__,
                "traceback": traceback.format_exc(),
            }
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
