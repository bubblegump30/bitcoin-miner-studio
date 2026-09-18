from __future__ import annotations

import argparse
import importlib
import os
from pathlib import Path
import subprocess
import sys
import traceback

ROOT = Path(__file__).resolve().parent
REQUIREMENTS = ROOT / "requirements.txt"
LAUNCH_SCRIPT = ROOT / "launch.pyw"
MAIN_SCRIPT = ROOT / "main.py"
ERROR_LOG = ROOT / "startup-error.log"


def _write_error(text: str) -> None:
    try:
        ERROR_LOG.write_text(text, encoding="utf-8")
    except Exception:
        pass


def _show_windows_error(text: str) -> None:
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, "Bitcoin Miner Studio", 0x10)
    except Exception:
        pass


def _webview_import_ok() -> tuple[bool, str]:
    try:
        import webview
        version = getattr(webview, "__version__", "installed")
        return True, str(version)
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def ensure_runtime(verbose: bool = False) -> None:
    ok, detail = _webview_import_ok()
    if ok:
        if verbose:
            print(f"pywebview: {detail}")
        return

    if verbose:
        print("pywebview import failed:", detail)
        print("Installing with the exact interpreter shown below:")
        print(sys.executable)

    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-warn-script-location",
        "-r",
        str(REQUIREMENTS),
    ]
    subprocess.check_call(cmd, cwd=ROOT)
    importlib.invalidate_caches()

    ok, detail = _webview_import_ok()
    if not ok:
        raise RuntimeError(f"pywebview still cannot be imported after installation: {detail}")
    if verbose:
        print(f"pywebview: {detail}")


def windowed_interpreter() -> Path | None:
    """Return pythonw.exe belonging to THIS exact python.exe installation."""
    exe = Path(sys.executable).resolve()
    candidates = []

    if os.name == "nt":
        # Standard CPython layout: python.exe and pythonw.exe are siblings.
        if exe.name.lower() == "python.exe":
            candidates.append(exe.with_name("pythonw.exe"))
        else:
            candidates.append(exe.parent / "pythonw.exe")

        # Some installs use versioned names.
        stem = exe.stem.lower()
        if stem.startswith("python") and stem != "python":
            suffix = exe.stem[len("python"):]
            candidates.append(exe.with_name(f"pythonw{suffix}.exe"))

    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def launch_windowed() -> None:
    ensure_runtime(verbose=False)

    if os.name == "nt":
        pyw = windowed_interpreter()
        if pyw:
            # IMPORTANT: direct absolute pythonw.exe path. Never use global pyw.exe.
            subprocess.Popen(
                [str(pyw), str(LAUNCH_SCRIPT)],
                cwd=str(ROOT),
                close_fds=True,
            )
            return

        # Rare fallback: use this exact python.exe without creating another console.
        flags = 0
        flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
        flags |= getattr(subprocess, "DETACHED_PROCESS", 0)
        subprocess.Popen(
            [sys.executable, str(MAIN_SCRIPT)],
            cwd=str(ROOT),
            creationflags=flags,
            close_fds=True,
        )
        return

    subprocess.Popen([sys.executable, str(MAIN_SCRIPT)], cwd=str(ROOT), close_fds=True)


def diagnostics(launch_console: bool = False) -> int:
    print("=== Bitcoin Miner Studio v2.0.2 Stable diagnostics ===")
    print()
    print("Chosen interpreter:")
    print(sys.executable)
    print()
    print("Python version:")
    print(sys.version.replace("\\n", " "))
    print()

    pyw = windowed_interpreter()
    print("Matching windowed interpreter:")
    print(str(pyw) if pyw else "NOT FOUND (console-free fallback will be used)")
    print()

    ok, detail = _webview_import_ok()
    print("pywebview import:")
    print("OK - " + detail if ok else "FAILED - " + detail)
    print()

    # Explicitly explain the machine-specific launcher issue we bypass.
    print("Launcher policy:")
    print("Global py.exe / pyw.exe associations are NOT used to launch the app.")
    print("Bitcoin Miner Studio uses the interpreter paths shown above.")
    print()

    if not ok:
        print("Attempting runtime repair...")
        try:
            ensure_runtime(verbose=True)
        except Exception:
            details = traceback.format_exc()
            print(details)
            _write_error(details)
            return 1
        print()

    print("Stable release assets:")
    for name in ("release_candidate.py", "release_info.json", "purple_dragon_manifest.json", "ui/index.html"):
        candidate = ROOT / name
        print(f"{name}: {'OK' if candidate.is_file() else 'MISSING'}")
    print()

    print("Config / support storage:")
    print(str(Path.home() / ".bitcoin-miner-studio"))
    print()

    if launch_console:
        print("Starting main.py with this exact interpreter in console mode...")
        print()
        return subprocess.call([sys.executable, str(MAIN_SCRIPT)], cwd=str(ROOT))

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--diagnose", action="store_true")
    parser.add_argument("--console", action="store_true")
    args, _ = parser.parse_known_args()

    try:
        if args.diagnose:
            return diagnostics(launch_console=args.console)
        launch_windowed()
        return 0
    except Exception:
        details = traceback.format_exc()
        _write_error(details)
        message = (
            "Bitcoin Miner Studio could not start.\\n\\n"
            "startup-error.log was written beside the program.\\n\\n"
            "Run diagnose.bat for detailed diagnostics."
        )
        _show_windows_error(message)
        print(details, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
