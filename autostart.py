"""Start-at-login and single-instance helpers (standard library only, reusable).

Login modes:
    "off"         nothing happens at login
    "window"      the app opens normally when you log in
    "background"  the app starts with `--headless`: the engine and Local API run with
                  no window at all; opening the app later attaches to it

This runs when the user LOGS IN to their desktop session, not at machine boot
before any login - that would need a system service, which a desktop app should
not install on its own.
"""
import os
import socket
import subprocess
import sys
import threading

APP_ID = "ai-voice-studio"
APP_TITLE = "AI Voice Studio"
BACKGROUND_FLAG = "--headless"                  # engine only, no window
LEGACY_FLAGS = ("--background",)                # older login entries; treated as --headless
INSTANCE_PORT = 47653           # loopback only; used to raise the already-running app
HEADLESS_PORT = 47654           # loopback only; the headless engine's control port


# ── what gets launched ────────────────────────────────────────────────────
def launch_command(background, script=None):
    """argv list that starts this app (works from source and when frozen)."""
    if getattr(sys, "frozen", False):
        # An AppImage runs from a temporary mount that changes every launch;
        # $APPIMAGE is the real, stable file the user started.
        cmd = [os.environ.get("APPIMAGE") or sys.executable]
    else:
        exe = sys.executable
        if sys.platform == "win32" and exe.lower().endswith("python.exe"):
            w = exe[:-len("python.exe")] + "pythonw.exe"      # no console window
            exe = w if os.path.exists(w) else exe
        cmd = [exe, os.path.abspath(script or sys.argv[0])]
    if background:
        cmd.append(BACKGROUND_FLAG)
    return cmd


# ── Linux: ~/.config/autostart/*.desktop ──────────────────────────────────
def _linux_file():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "autostart", APP_ID + ".desktop")


def _desktop_quote(arg):
    if arg and not any(ch in arg for ch in ' \t\n"\'\\><~|&;$*?#()`'):
        return arg
    esc = arg.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$")
    return '"' + esc.replace("%", "%%") + '"'


# ── macOS: ~/Library/LaunchAgents/*.plist ─────────────────────────────────
def _mac_file():
    return os.path.expanduser(f"~/Library/LaunchAgents/com.somore100.{APP_ID}.plist")


# ── Windows: HKCU Run key ────────────────────────────────────────────────
_WIN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _is_bg(where):
    """True if the launch line (str) or argument list contains a headless flag."""
    return any(f in where for f in (BACKGROUND_FLAG,) + LEGACY_FLAGS)


def get_login_mode():
    """Reads the real OS state: "off" | "window" | "background"."""
    try:
        if sys.platform.startswith("linux"):
            with open(_linux_file(), encoding="utf-8") as f:
                txt = f.read()
            if "X-GNOME-Autostart-enabled=false" in txt or "Hidden=true" in txt:
                return "off"
            line = next((ln for ln in txt.splitlines() if ln.startswith("Exec=")), "")
            return "background" if _is_bg(line) else "window"
        if sys.platform == "darwin":
            import plistlib
            with open(_mac_file(), "rb") as f:
                args = plistlib.load(f).get("ProgramArguments", [])
            return "background" if _is_bg(args) else "window"
        if sys.platform == "win32":
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WIN_KEY) as k:
                val = winreg.QueryValueEx(k, APP_TITLE)[0]
            return "background" if _is_bg(val) else "window"
    except (OSError, ValueError):
        pass
    return "off"


def set_login_mode(mode, script=None):
    """Applies "off" | "window" | "background". Returns the path / key touched.
    Raises OSError if the OS refuses."""
    if mode not in ("off", "window", "background"):
        raise ValueError(mode)
    cmd = launch_command(mode == "background", script)
    if sys.platform.startswith("linux"):
        path = _linux_file()
        if mode == "off":
            _rm(path)
            return path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if getattr(sys, "frozen", False):       # __file__ is a temp unpack dir here
            workdir = os.path.dirname(os.path.abspath(cmd[0]))
        else:
            workdir = os.path.dirname(os.path.abspath(script or sys.argv[0]))
        with open(path, "w", encoding="utf-8") as f:
            f.write("[Desktop Entry]\nType=Application\n"
                    f"Name={APP_TITLE}\n"
                    f"Comment={APP_TITLE}"
                    f"{' (background)' if mode == 'background' else ''}\n"
                    f"Exec={' '.join(_desktop_quote(a) for a in cmd)}\n"
                    f"Path={workdir}\nTerminal=false\n"
                    "X-GNOME-Autostart-enabled=true\n")
        return path
    if sys.platform == "darwin":
        import plistlib
        path = _mac_file()
        if mode == "off":
            _rm(path)
            return path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            plistlib.dump({"Label": f"com.somore100.{APP_ID}", "ProgramArguments": cmd,
                           "RunAtLoad": True}, f)
        return path
    if sys.platform == "win32":
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WIN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if mode == "off":
                try:
                    winreg.DeleteValue(k, APP_TITLE)
                except FileNotFoundError:
                    pass
            else:
                winreg.SetValueEx(k, APP_TITLE, 0, winreg.REG_SZ, subprocess.list2cmdline(cmd))
        return "HKCU\\" + _WIN_KEY
    raise OSError("Start at login is not supported on this system.")


def _rm(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def _listener(port):
    """Loopback listening socket that can be re-bound right after a restart.
    POSIX: SO_REUSEADDR (still refuses a second live listener). Windows: there
    SO_REUSEADDR would let two programs share a port, so use the exclusive flag."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if os.name == "nt":
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", port))
        srv.listen(4)
    except OSError:
        srv.close()
        raise
    return srv


# ── single instance: a second launch just raises the first ────────────────
def claim_instance(on_show, port=INSTANCE_PORT):
    """Returns (state, socket):
        "owner"    this process is now the one running instance (keep the socket alive);
                   on_show() is called (from a helper thread) when another launch asks us to show.
        "running"  another instance exists and was asked to show its window -> exit now
        "unknown"  the port is taken by something else -> carry on without single-instance
    """
    try:
        srv = _listener(port)
    except OSError:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.5) as c:
                c.sendall(f"show {APP_ID}\n".encode())
                if c.recv(8).startswith(b"ok"):
                    return "running", None
        except OSError:
            pass
        return "unknown", None

    def serve():
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            with conn:
                try:
                    conn.settimeout(1.0)
                    if conn.recv(64).decode("utf-8", "replace").strip() == f"show {APP_ID}":
                        conn.sendall(b"ok\n")
                        on_show()
                except Exception:
                    pass

    threading.Thread(target=serve, daemon=True).start()
    return "owner", srv


# ── headless engine: presence / control over a loopback port ──────────────
def headless_serve(info, on_stop, port=HEADLESS_PORT, ready=None):
    """Called by the headless engine. Answers "info" (who/where am I) and "stop".
    `ready` (a threading.Event) gates "info": until it is set the engine answers
    "starting", so nobody attaches to an API that is not listening yet.
    Returns the listening socket, or None if another engine already owns the port."""
    try:
        srv = _listener(port)
    except OSError:
        return None

    def serve():
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            with conn:
                try:
                    conn.settimeout(1.0)
                    cmd = conn.recv(64).decode("utf-8", "replace").strip()
                    if cmd == f"info {APP_ID}" and ready is not None and not ready.is_set():
                        conn.sendall(b"starting\n")
                    elif cmd == f"info {APP_ID}":
                        conn.sendall((f"headless pid={info['pid']} api={info['api']}\n").encode())
                    elif cmd == f"stop {APP_ID}":
                        conn.sendall(b"ok\n")
                        on_stop()
                except Exception:
                    pass

    threading.Thread(target=serve, daemon=True).start()
    return srv


def _ask(cmd, port, timeout=1.0):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as c:
            c.sendall(f"{cmd} {APP_ID}\n".encode())
            return c.recv(128).decode("utf-8", "replace").strip()
    except OSError:
        return ""


def headless_probe(port=HEADLESS_PORT):
    """{"pid": int, "api": int} if a headless engine is running, else None."""
    ans = _ask("info", port)
    if not ans.startswith("headless"):
        return None
    try:
        kv = dict(p.split("=", 1) for p in ans.split()[1:])
        return {"pid": int(kv["pid"]), "api": int(kv["api"])}
    except (KeyError, ValueError):
        return None


def headless_stop(port=HEADLESS_PORT):
    """Ask a running headless engine to stop. True if it acknowledged."""
    return _ask("stop", port).startswith("ok")
