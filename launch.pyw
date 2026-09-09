from pathlib import Path
import ctypes
import multiprocessing
import sys
import traceback

from branding import WINDOWS_APP_USER_MODEL_ID


def show_error(message):
    try:
        ctypes.windll.user32.MessageBoxW(None, message, "Bitcoin Miner Studio", 0x10)
    except Exception:
        pass


def configure_windows_app_identity():
    """Set a stable Windows taskbar identity for Bitcoin Miner Studio."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            WINDOWS_APP_USER_MODEL_ID
        )
    except Exception:
        pass


def run_launcher():
    """Start the GUI only in the original Windows application process."""
    # Defense in depth: multiprocessing "spawn" children re-import the entry
    # script. Even if this function were called accidentally inside a worker,
    # a child process must stay headless.
    if multiprocessing.current_process().name != "MainProcess":
        return

    try:
        from main import main
        main()
    except Exception:
        details = (
            f"Python executable: {sys.executable}\n"
            f"Python version: {sys.version}\n\n"
            + traceback.format_exc()
        )
        try:
            Path(__file__).with_name("startup-error.log").write_text(
                details,
                encoding="utf-8",
            )
        except Exception:
            pass
        show_error(
            "Bitcoin Miner Studio could not start.\n\n"
            "A diagnostic file named startup-error.log was created beside the program."
        )


if __name__ == "__main__":
    # Required by Windows multiprocessing/frozen-app compatible launchers.
    multiprocessing.freeze_support()
    configure_windows_app_identity()
    run_launcher()
