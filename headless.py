"""Headless engine: run the Local API with no window at all (standard library only).

    Audiovane --headless        (alias: --background)

No Tk window is ever created. A small control port on 127.0.0.1 lets the app (and
`autostart.headless_stop`) find a running engine and ask it to stop, so opening
the app later attaches to this engine instead of starting a second API.
"""
import os
import signal
import sys
import threading

import api_server
import autostart


def _hide_console():
    """A Windows console build would leave a console window open at login."""
    if sys.platform == "win32":
        try:
            import ctypes
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 0)
        except Exception:
            pass


def run(backend, port, token="", control_port=autostart.HEADLESS_PORT, log=print,
        allow_no_key=False):
    """Serve until asked to stop. Returns an exit code (0 ok, 1 could not start)."""
    stop, ready = threading.Event(), threading.Event()
    ctl = autostart.headless_serve(
        {"pid": os.getpid(), "api": port}, stop.set, port=control_port, ready=ready)
    if ctl is None:
        log(f"[AVS] headless: another background engine is already running (control port "
            f"{control_port}); exiting", flush=True)
        return 1
    try:
        api = api_server.ApiServer(backend, port, token, log=log, allow_no_key=allow_no_key)
        api.start()
    except ValueError as e:                     # no API key and not explicitly allowed
        log(f"[AVS] headless: {e}", flush=True)
        ctl.close()
        return 1
    except OSError as e:
        log(f"[AVS] headless: could not start the Local API on port {port}: {e}. "
            "Is Audiovane already running its API? Stop it first.", flush=True)
        ctl.close()
        return 1
    ready.set()
    _hide_console()
    log(f"[AVS] headless engine running (pid {os.getpid()}): Local API on 127.0.0.1:{port}, "
        "no window", flush=True)
    if threading.current_thread() is threading.main_thread():
        for name in ("SIGINT", "SIGTERM"):
            sig = getattr(signal, name, None)
            if sig is not None:
                try:
                    signal.signal(sig, lambda *_: stop.set())
                except (ValueError, OSError):
                    pass
    while not stop.wait(0.5):
        pass
    log("[AVS] headless engine stopping", flush=True)
    try:
        api.stop()
    finally:
        ctl.close()
    return 0
