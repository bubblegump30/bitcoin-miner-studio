from __future__ import annotations

import itertools
import json
import multiprocessing
import queue
import sys
import threading
import traceback
import types
from pathlib import Path


# The native Windows host replaces pywebview entirely.  Four existing backend
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
    API calls.  No localhost HTTP listener, firewall rule, or browser extension
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


class NativeTrayBridge:
    """Attach the existing dependency-free tray manager to the native host."""

    def __init__(self, backend, icon_path: Path):
        from windows_tray import WindowsTrayManager, normalize_tray_settings

        self.backend = backend
        self.manager = WindowsTrayManager(
            icon_path,
            status_provider=backend._tray_status_snapshot,
            show_callback=lambda: _host_event("show_window"),
            hide_callback=lambda: _host_event("hide_window"),
            exit_callback=lambda: _host_event("exit_app"),
            settings=normalize_tray_settings(backend.cfg),
        )
        backend._attach_tray_manager(self.manager)

    def publish_settings(self) -> None:
        state = self.manager.state()
        _host_event("tray_state", tray=state)

    def start_if_enabled_async(self) -> None:
        if not self.manager.settings.get("tray_enabled"):
            self.publish_settings()
            return

        def _start():
            try:
                self.manager.start()
            finally:
                self.publish_settings()

        threading.Thread(target=_start, name="NativeTrayStart", daemon=True).start()


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
