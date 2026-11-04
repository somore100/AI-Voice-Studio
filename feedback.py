"""Reusable "Leave Feedback" window for Tkinter apps (standard library only).

Copy this single file into any app and call:

    import feedback
    feedback.open_feedback(root, app_name="My App", app_version="1.2",
                           to_addr="support@example.com",
                           endpoint=None,            # optional relay, see below
                           colors={"bg": ..., "card": ..., "fg": ..., "dim": ...,
                                   "accent": ..., "surface": ..., "border": ...,
                                   "good": ..., "bad": ...})

No credentials live in the app. Two ways to deliver a report:

1. Default (endpoint=None): opens the user's own mail client with the report
   pre-filled, addressed to `to_addr`. The user reads it and presses Send, so
   nothing leaves the machine unseen. "Copy report" is offered as a fallback.
2. Relay (endpoint="https://..."): the report is POSTed as JSON to a small web
   endpoint YOU control, which forwards it to your inbox (a free Google Apps
   Script web app works, see RELAY_APPS_SCRIPT below). The endpoint URL is not a
   secret in the way a mail password is, but treat it as public: it can only
   receive reports.

System information is only collected when the user ticks the box, and the exact
text that will be included is shown in the window first.
"""
import json
import os
import platform
import re
import subprocess
import sys
import threading
import tkinter as tk
import urllib.parse
import urllib.request
import webbrowser
from tkinter import ttk

REPORT_TYPES = [          # (label shown, tag used in the subject)
    ("Bug Report", "BUG"),
    ("Feature Suggestion", "FEATURE"),
    ("General Feedback", "FEEDBACK"),
    ("Question", "QUESTION"),
    ("Other", "OTHER"),
]

MAX_TITLE, MAX_DESC = 120, 4000
_MAILTO_LIMIT = 1800      # many mail clients / OSes choke on longer mailto: links
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ── system information (only called when the user opts in) ────────────────
def _run(cmd, timeout=6):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           creationflags=_NO_WINDOW)
        return r.stdout.strip()
    except Exception:
        return ""


def _cpu():
    try:
        if sys.platform.startswith("linux"):
            with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as f:
                for ln in f:
                    if ln.lower().startswith("model name"):
                        return ln.split(":", 1)[1].strip()
        elif sys.platform == "darwin":
            v = _run(["sysctl", "-n", "machdep.cpu.brand_string"])
            if v:
                return v
        elif sys.platform == "win32":
            v = os.environ.get("PROCESSOR_IDENTIFIER", "")
            if v:
                return v
    except Exception:
        pass
    return platform.processor() or "unknown"


def _gpus():
    names = []
    try:
        if sys.platform.startswith("linux"):
            for ln in _run(["lspci"]).splitlines():
                if re.search(r"VGA compatible|3D controller|Display controller", ln):
                    names.append(ln.split(": ", 1)[-1].strip())
        elif sys.platform == "darwin":
            for ln in _run(["system_profiler", "SPDisplaysDataType"]).splitlines():
                if "Chipset Model" in ln:
                    names.append(ln.split(":", 1)[1].strip())
        elif sys.platform == "win32":
            out = _run(["powershell", "-NoProfile", "-Command",
                        "(Get-CimInstance Win32_VideoController).Name"])
            names = [ln.strip() for ln in out.splitlines() if ln.strip()]
    except Exception:
        pass
    return names or ["unknown"]


def _ram_gb():
    try:
        if sys.platform.startswith("linux"):
            with open("/proc/meminfo") as f:
                kb = int(f.readline().split()[1])
            return kb / 1024 / 1024
        if sys.platform == "darwin":
            return int(_run(["sysctl", "-n", "hw.memsize"])) / 1024 ** 3
        if sys.platform == "win32":
            import ctypes

            class MEM(ctypes.Structure):
                _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong),
                            ("total", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong),
                            ("pt", ctypes.c_ulonglong), ("pa", ctypes.c_ulonglong),
                            ("vt", ctypes.c_ulonglong), ("va", ctypes.c_ulonglong),
                            ("ext", ctypes.c_ulonglong)]
            m = MEM()
            m.l = ctypes.sizeof(MEM)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.total / 1024 ** 3
    except Exception:
        pass
    return None


def _os_name():
    if sys.platform.startswith("linux"):
        try:
            with open("/etc/os-release", encoding="utf-8") as f:
                for ln in f:
                    if ln.startswith("PRETTY_NAME="):
                        return ln.split("=", 1)[1].strip().strip('"') + \
                            f" (kernel {platform.release()})"
        except Exception:
            pass
    if sys.platform == "darwin":
        return f"macOS {platform.mac_ver()[0]}"
    return f"{platform.system()} {platform.release()} ({platform.version()})"


def collect_system_info(app_version=""):
    """Plain dict of non-identifying hardware / OS facts. No hostname, user
    name, serial numbers, MAC/IP addresses or file paths."""
    ram = _ram_gb()
    return {
        "OS": _os_name(),
        "Architecture": platform.machine() or "unknown",
        "CPU": _cpu(),
        "GPU": "; ".join(_gpus()),
        "RAM": f"{ram:.1f} GB" if ram else "unknown",
        "Python": platform.python_version(),
        "App version": app_version,
    }


# ── report formatting / delivery ──────────────────────────────────────────
def build_report(app_name, app_version, rtype, name, title, description, sysinfo=None):
    """(subject, body) for the e-mail."""
    tag = dict(REPORT_TYPES).get(rtype, "OTHER")
    subject = f"[{app_name}] [{tag}] {title.strip()}"
    lines = [
        "=== FEEDBACK REPORT ===",
        f"App:     {app_name}",
        f"Version: {app_version}",
        f"Type:    {rtype}",
        f"From:    {name.strip() or '(not given)'}",
        f"Title:   {title.strip()}",
        "",
        "--- Description ---",
        description.strip(),
        "",
    ]
    if sysinfo:
        lines.append("--- System information (included by the user) ---")
        lines += [f"{k}: {v}" for k, v in sysinfo.items()]
    else:
        lines.append("--- System information: not included ---")
    return subject, "\n".join(lines)


def send_via_endpoint(endpoint, to_addr, subject, body, timeout=15, extra=None):
    """POST the report to a relay. Raises on any failure."""
    payload = json.dumps({"to": to_addr, "subject": subject, "body": body,
                          **(extra or {})}).encode("utf-8")
    req = urllib.request.Request(endpoint, data=payload, method="POST",
                                 headers={"Content-Type": "text/plain;charset=utf-8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        text = r.read().decode("utf-8", "replace")
        if r.status >= 400 or '"ok":false' in text.replace(" ", "").lower():
            raise RuntimeError(f"The relay rejected the report ({r.status}): {text[:120]}")


def _open_shortened(make_url, body, limit):
    """Open make_url(body), shortening the body until the link fits `limit`.
    Returns True if the whole body fit."""
    full = len(body)
    while True:
        url = make_url(body)
        if len(url) <= limit or len(body) < 200:
            break
        body = body[: int(len(body) * 0.85)]
    webbrowser.open(url)
    return len(body) == full


def open_mail_client(to_addr, subject, body):
    """Open the default mail client (mailto:) with the report pre-filled.
    Returns True if the whole body fit. Fails silently on systems with no mail
    client registered - which is why the window also offers Gmail and Copy."""
    return _open_shortened(
        lambda b: ("mailto:" + urllib.parse.quote(to_addr) + "?subject=" +
                   urllib.parse.quote(subject) + "&body=" + urllib.parse.quote(b)),
        body, _MAILTO_LIMIT)


def open_gmail(to_addr, subject, body):
    """Open a Gmail compose tab in the browser with the report pre-filled
    (works without any mail program installed; the user signs in to their own
    account and presses Send)."""
    return _open_shortened(
        lambda b: "https://mail.google.com/mail/?" + urllib.parse.urlencode(
            {"view": "cm", "fs": "1", "to": to_addr, "su": subject, "body": b},
            quote_via=urllib.parse.quote),
        body, 6000)


# ── the window ────────────────────────────────────────────────────────────
def open_feedback(root, app_name, app_version, to_addr, colors=None, endpoint=None):
    c = {"bg": "#1a1b2e", "card": "#1e1f33", "surface": "#2a2b45", "border": "#3a3b5c",
         "fg": "#c0caf5", "dim": "#565f89", "accent": "#7dcfff",
         "good": "#9ece6a", "bad": "#f7768e"}
    c.update(colors or {})
    F = ("Segoe UI", 9)
    FB = ("Segoe UI", 9, "bold")

    top = tk.Toplevel(root)
    top.title(f"Leave Feedback - {app_name}")
    top.configure(bg=c["bg"])
    top.transient(root)
    top.minsize(480, 560)
    pad = {"padx": 14}

    def label(text, **kw):
        return tk.Label(top, text=text, bg=c["bg"], fg=kw.pop("fg", c["fg"]),
                        font=kw.pop("font", F), **kw)

    def entry(var):
        return tk.Entry(top, textvariable=var, bg=c["surface"], fg=c["fg"],
                        insertbackground=c["fg"], relief="flat", font=F,
                        highlightthickness=1, highlightbackground=c["border"],
                        highlightcolor=c["accent"])

    label("Leave Feedback", fg=c["accent"], font=("Segoe UI", 12, "bold")).pack(
        anchor="w", padx=14, pady=(12, 0))
    label(f"{app_name}  -  version {app_version}", fg=c["dim"],
          font=("Segoe UI", 8)).pack(anchor="w", padx=14, pady=(0, 8))

    label("Report type", font=FB).pack(anchor="w", **pad)
    rtype = tk.StringVar(value=REPORT_TYPES[0][0])
    ttk.Combobox(top, textvariable=rtype, state="readonly",
                 values=[t for t, _ in REPORT_TYPES]).pack(fill="x", padx=14, pady=(2, 8))

    label("Your name (optional)", font=FB).pack(anchor="w", **pad)
    name = tk.StringVar()
    entry(name).pack(fill="x", padx=14, pady=(2, 8), ipady=3)

    label("Title *", font=FB).pack(anchor="w", **pad)
    title = tk.StringVar()
    entry(title).pack(fill="x", padx=14, pady=(2, 0), ipady=3)
    label("e.g. UI is not working / Crashes on startup / Feature suggestion: custom themes",
          fg=c["dim"], font=("Segoe UI", 8)).pack(anchor="w", padx=14, pady=(0, 8))

    label("Description *", font=FB).pack(anchor="w", **pad)
    box = tk.Frame(top, bg=c["border"], padx=1, pady=1)
    box.pack(fill="both", expand=True, padx=14, pady=(2, 8))
    desc = tk.Text(box, height=8, bg=c["surface"], fg=c["fg"], insertbackground=c["fg"],
                   relief="flat", wrap="word", font=F, undo=True)
    desc.pack(fill="both", expand=True)

    use_sys = tk.BooleanVar(value=False)
    sys_box = tk.Text(top, height=7, bg=c["card"], fg=c["dim"], relief="flat",
                      font=("TkFixedFont", 8), wrap="word", state="disabled")
    cache = {}

    def toggle_sys():
        if use_sys.get():
            if "info" not in cache:
                cache["info"] = collect_system_info(app_version)
            sys_box.config(state="normal")
            sys_box.delete("1.0", "end")
            sys_box.insert("1.0", "This will be included in the report:\n" + "\n".join(
                f"  {k}: {v}" for k, v in cache["info"].items()))
            sys_box.config(state="disabled")
            sys_box.pack(fill="x", padx=14, pady=(0, 8))
        else:
            sys_box.pack_forget()

    ttk.Checkbutton(top, text="Include my computer specifications",
                    variable=use_sys, command=toggle_sys).pack(anchor="w", padx=14, pady=(0, 4))

    status = tk.Label(top, text="", bg=c["bg"], fg=c["dim"], font=F,
                      wraplength=440, justify="left")
    status.pack(anchor="w", padx=14, pady=(2, 4))

    def say(text, color):
        status.config(text=text, fg=color)

    def get_report():
        t = " ".join(title.get().split())[:MAX_TITLE]
        d = desc.get("1.0", "end").strip()
        if not t:
            say("Please enter a title.", c["bad"]); return None
        if len(t) < 4:
            say("The title is too short.", c["bad"]); return None
        if not d:
            say("Please describe the problem or suggestion.", c["bad"]); return None
        if len(d) < 10:
            say("The description is too short to be useful.", c["bad"]); return None
        if len(d) > MAX_DESC:
            say(f"The description is too long ({len(d)} of {MAX_DESC} characters).",
                c["bad"]); return None
        info = cache.get("info") if use_sys.get() else None
        return build_report(app_name, app_version, rtype.get(), name.get(), t, d, info)

    def copy_report():
        r = get_report()
        if not r:
            return
        top.clipboard_clear()
        top.clipboard_append(f"To: {to_addr}\nSubject: {r[0]}\n\n{r[1]}")
        say("Report copied. Paste it into an email to " + to_addr, c["good"])

    def submit():
        r = get_report()
        if not r:
            return
        subject, body = r
        if endpoint:
            send_btn.config(state="disabled")
            say("Sending...", c["dim"])

            def work():
                try:
                    send_via_endpoint(endpoint, to_addr, subject, body, extra={
                        "app": app_name, "version": app_version,
                        "type": dict(REPORT_TYPES).get(rtype.get(), "OTHER")})
                    err = None
                except Exception as e:
                    err = str(e)

                def done():
                    send_btn.config(state="normal")
                    if err:
                        say(f"Could not send: {err[:140]}\nYour text is still here - try "
                            f"again, or use 'Open in Gmail' / 'Copy report'.", c["bad"])
                    else:
                        say("Thank you! Your report was sent.", c["good"])
                        top.after(1800, top.destroy)
                try:
                    top.after(0, done)
                except Exception:
                    pass
            threading.Thread(target=work, daemon=True).start()
        else:
            whole = open_mail_client(to_addr, subject, body)
            say("Tried to open your email app with the report filled in. If nothing "
                "appeared, use 'Open in Gmail' or 'Copy report'."
                + ("" if whole else "\nThe report was too long for the link and was "
                   "shortened: use 'Copy report' for the full text."), c["dim"])

    def gmail():
        r = get_report()
        if not r:
            return
        whole = open_gmail(to_addr, *r)
        say("Opened Gmail in your browser with the report filled in - press Send there."
            + ("" if whole else "\nIt was shortened: use 'Copy report' for the full text."),
            c["good"])

    bar = tk.Frame(top, bg=c["bg"])
    bar.pack(fill="x", padx=14, pady=(0, 12))

    def btn(text, cmd, bg, fg=None, bold=False):
        return tk.Button(bar, text=text, command=cmd, bg=bg, fg=fg or c["fg"],
                         activebackground=bg, relief="flat", bd=0, padx=12, pady=5,
                         cursor="hand2", font=FB if bold else F)

    send_btn = btn("Send report" if endpoint else "Email app", submit, c["accent"],
                   fg=c["bg"], bold=True)
    send_btn.pack(side="left")
    btn("Open in Gmail", gmail, c["surface"]).pack(side="left", padx=6)
    btn("Copy report", copy_report, c["surface"]).pack(side="left")
    btn("Cancel", top.destroy, c["surface"]).pack(side="right")
    label("Sent to " + to_addr, fg=c["dim"], font=("Segoe UI", 8)).pack(
        anchor="w", padx=14, pady=(0, 8))
    top.grab_set()
    return top


# (Arrows of War's feedback_kit/apps_script.gs is a hardened version of this: it fixes the
# recipient server-side, strips newlines from the subject and caps the body.)
# Paste into https://script.google.com (new project), then Deploy > New deployment >
# Web app, "Execute as: Me", "Who has access: Anyone". Use the /exec URL as `endpoint`.
# It mails the report to the account that owns the script, with no password in the app.
RELAY_APPS_SCRIPT = """
function doPost(e) {
  try {
    var d = JSON.parse(e.postData.contents);
    MailApp.sendEmail(Session.getEffectiveUser().getEmail(),
                      String(d.subject).slice(0, 200), String(d.body).slice(0, 20000));
    return ContentService.createTextOutput('{"ok":true}');
  } catch (err) {
    return ContentService.createTextOutput('{"ok":false}');
  }
}
"""
