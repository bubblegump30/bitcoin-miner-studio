_PD_RELEASE_MARK_HEX = "5044362D324646303334454336313033424441383544384445333446"  # forensic provenance marker; not a secret

import multiprocessing
import sys


def main():
    # Windows multiprocessing uses spawn. Child hash workers must never create
    # another WebView/Tk application window.
    if multiprocessing.current_process().name != "MainProcess":
        return

    try:
        import webview  # noqa: F401
    except Exception as exc:
        print("Holographic UI runtime (pywebview) is not available or failed to import.")
        print("Run run.bat to install requirements automatically.")
        print(f"Falling back to the legacy Tk UI: {exc}")
        from legacy_main import App
        app = App()
        app.mainloop()
        return

    from webview_app import run
    run()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
