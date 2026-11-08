"""MCP server for AI Voice Studio (standard library only).

Lets Claude Code, Claude Desktop and other MCP clients use this app's voices and
speech recognition: "say that out loud with AI Voice Studio", "transcribe this
recording". It is a thin bridge to the app's Local API, so the app has to be
running with the API on. If it is not, this server starts it in the background
(`main.py --background`) when it can.

Run (the client launches it for you):

    /path/to/venv/bin/python /path/to/mcp_server.py        # from source
    AI_Voice_Studio.AppImage --mcp                         # packaged build (any platform)

Settings (all optional; by default it reads the port and key the app saved):
    AVS_API_URL         e.g. http://127.0.0.1:8765/v1
    AVS_API_KEY         the API key, if you set one
    AVS_OUTPUT_DIR      where speak() saves audio (default: the app's output folder,
                        else ~/Documents/AI Voice Studio)
    AVS_MCP_NO_LAUNCH=1 never start the app automatically

stdout carries the protocol, so everything diagnostic goes to stderr.
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import wave

SERVER_NAME = "ai-voice-studio"
SERVER_VERSION = "1.0.0"
SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
HERE = os.path.dirname(os.path.abspath(__file__))


def log(*a):
    print("[avs-mcp]", *a, file=sys.stderr, flush=True)


# ── finding the app's API ─────────────────────────────────────────────────
def _prefs():
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    try:
        with open(os.path.join(base, "AI Voice Studio", "prefs.json"), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def api_base():
    url = os.environ.get("AVS_API_URL")
    if url:
        return url.rstrip("/")
    return f"http://127.0.0.1:{_prefs().get('api_port', 8765)}/v1"


def api_key():
    return os.environ.get("AVS_API_KEY") or str(_prefs().get("api_token", "") or "")


class ToolError(Exception):
    pass


def _request(method, path, body=None, headers=None, timeout=300):
    h = dict(headers or {})
    if api_key():
        h["Authorization"] = "Bearer " + api_key()
    req = urllib.request.Request(api_base() + path, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8", "replace"))["error"]["message"]
        except Exception:
            msg = f"HTTP {e.code}"
        if e.code == 401:
            msg += (" Set AVS_API_KEY for this MCP server, or copy the key from "
                    "AI Voice Studio's Local API section.")
        raise ToolError(f"AI Voice Studio API: {msg}")
    except (urllib.error.URLError, ConnectionError, OSError) as e:
        raise ConnectionError(str(e))


def ensure_running():
    """Make sure the API answers; start the app in the background if needed."""
    try:
        _request("GET", "/models", timeout=5)
        return
    except ConnectionError:
        pass
    if getattr(sys, "frozen", False):       # packaged app (AppImage: $APPIMAGE is the real file)
        cmd = [os.environ.get("APPIMAGE") or sys.executable, "--background"]
        workdir = os.path.dirname(os.path.abspath(cmd[0]))
    else:
        main_py = os.path.join(HERE, "main.py")
        cmd, workdir = ([sys.executable, main_py, "--background"], HERE) \
            if os.path.exists(main_py) else (None, HERE)
    if os.environ.get("AVS_MCP_NO_LAUNCH") or cmd is None:
        raise ToolError("AI Voice Studio is not running. Open it and press 'Start API server' "
                        "in the Local API section (or set it to run in the background at login).")
    log("API not reachable - starting AI Voice Studio in the background")
    subprocess.Popen(cmd, cwd=workdir, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=(os.name != "nt"))
    deadline = time.time() + 90                   # the models take a while to load
    while time.time() < deadline:
        time.sleep(1.5)
        try:
            _request("GET", "/models", timeout=5)
            return
        except ConnectionError:
            continue
    raise ToolError("Started AI Voice Studio but its Local API did not come up. Open the app "
                    "and press 'Start API server' (if the app was already open, its API may be off).")


def call(method, path, **kw):
    ensure_running()
    return _request(method, path, **kw)


# ── tools ─────────────────────────────────────────────────────────────────
def _output_dir():
    d = (os.environ.get("AVS_OUTPUT_DIR") or _prefs().get("last_folder")
         or os.path.join(os.path.expanduser("~/Documents"), "AI Voice Studio"))
    os.makedirs(d, exist_ok=True)
    return d


def _free_name(folder, name):
    base, ext = os.path.splitext(name)
    p, n = os.path.join(folder, name), 2
    while os.path.exists(p):
        p = os.path.join(folder, f"{base}-{n}{ext}")
        n += 1
    return p


def tool_status(args):
    models = json.loads(call("GET", "/models"))["data"]
    tts = [m["id"] for m in models if m.get("capabilities") == "tts"]
    stt = [m["id"] for m in models if m.get("capabilities") == "stt"]
    return (f"AI Voice Studio is running at {api_base()}\n"
            f"Speech engines: {', '.join(tts) or 'none installed'}\n"
            f"Recognition models: {', '.join(stt) or 'none installed'}\n"
            f"Audio is saved to: {_output_dir()}")


def tool_list_voices(args):
    voices = json.loads(call("GET", "/voices")).get("voices", [])
    eng = (args.get("engine") or "").lower()
    lang = (args.get("language") or "").lower()
    rows = [v for v in voices
            if (not eng or v.get("engine") == eng)
            and (not lang or lang in (v.get("lang") or "").lower() or v.get("lang") == "*")]
    if not rows:
        return "No matching voices."
    lines = [f"{v['key']}  -  {v.get('label', '')}  [{v.get('gender') or '?'}, {v.get('lang')}]"
             for v in rows[:150]]
    more = f"\n... and {len(rows) - 150} more; filter with engine/language." if len(rows) > 150 else ""
    return "Use the first column as the `voice` for speak().\n" + "\n".join(lines) + more


def tool_speak(args):
    text = str(args.get("text") or "").strip()
    if not text:
        raise ToolError("'text' is required.")
    payload = {"input": text, "response_format": "wav"}
    for k in ("voice", "model", "language"):
        if args.get(k):
            payload[k] = str(args[k])
    for k in ("speed", "pitch", "volume", "depth"):
        if args.get(k) is not None:
            payload[k] = args[k]
    data = call("POST", "/audio/speech", body=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"})
    if data[:4] != b"RIFF":
        raise ToolError("The API did not return audio: " + data[:200].decode("utf-8", "replace"))
    name = os.path.basename(str(args.get("filename") or "").strip()) or (
        "avs-" + time.strftime("%Y%m%d-%H%M%S") + "-" +
        (re.sub(r"[^A-Za-z0-9]+", "-", text)[:30].strip("-") or "speech") + ".wav")
    if not name.lower().endswith(".wav"):
        name += ".wav"
    path = _free_name(_output_dir(), name)
    with open(path, "wb") as f:
        f.write(data)
    try:
        with wave.open(path, "rb") as w:
            dur = w.getnframes() / float(w.getframerate())
        info = f" ({dur:.1f} s)"
    except Exception:
        info = ""
    return f"Saved speech to {path}{info}"


def _multipart(fields, fname, data):
    b = uuid.uuid4().hex
    out = []
    for k, v in fields:
        out.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    out.append((f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{fname}"\r\n'
                "Content-Type: application/octet-stream\r\n\r\n").encode() + data + b"\r\n")
    out.append(f"--{b}--\r\n".encode())
    return b"".join(out), f"multipart/form-data; boundary={b}"


def tool_transcribe(args):
    path = os.path.expanduser(str(args.get("path") or ""))
    if not os.path.isfile(path):
        raise ToolError(f"No such audio file: {path}")
    if os.path.getsize(path) > 200 * 1024 * 1024:
        raise ToolError("That file is larger than 200 MB.")
    with open(path, "rb") as f:
        data = f.read()
    words = bool(args.get("word_timestamps"))
    fields = [("model", str(args.get("model") or "whisper-1"))]
    if args.get("language"):
        fields.append(("language", str(args["language"])))
    if words:
        fields += [("response_format", "verbose_json"), ("timestamp_granularities[]", "word")]
    body, ctype = _multipart(fields, os.path.basename(path), data)
    res = json.loads(call("POST", "/audio/transcriptions", body=body,
                          headers={"Content-Type": ctype}))
    if not words:
        return res.get("text", "")
    lines = [res.get("text", ""), "", "word timestamps (seconds):"]
    lines += [f"{w['start']:.2f}-{w['end']:.2f}  {w['word']}" for w in res.get("words", [])]
    return "\n".join(lines)


TOOLS = {
    "speak": (tool_speak,
              "Turn text into speech with AI Voice Studio's local voices and save it as a WAV file. "
              "Returns the file path.",
              {"text": {"type": "string", "description": "What to say."},
               "voice": {"type": "string", "description": "Voice key from list_voices, e.g. 'kokoro:af_heart'. Optional."},
               "model": {"type": "string", "description": "Engine: kokoro, vctk or xtts. Optional."},
               "language": {"type": "string", "description": "Language code (matters for xtts). Optional."},
               "speed": {"type": "number", "description": "0.25-4, default 1."},
               "pitch": {"type": "number", "description": "Semitones, -12 to 12, default 0."},
               "volume": {"type": "number", "description": "0-2, default 1."},
               "depth": {"type": "number", "description": "Voice depth, -8 to 8, default 0."},
               "filename": {"type": "string", "description": "File name only (no folders); saved in the output folder, never overwriting."}},
              ["text"]),
    "list_voices": (tool_list_voices,
                    "List the installed voices (key, description, gender, language).",
                    {"engine": {"type": "string", "description": "Filter: kokoro, vctk or xtts."},
                     "language": {"type": "string", "description": "Filter by language code, e.g. 'en'."}},
                    []),
    "transcribe": (tool_transcribe,
                   "Transcribe a local audio file to text with Whisper or Vosk, optionally with per-word timestamps.",
                   {"path": {"type": "string", "description": "Path to the audio file."},
                    "language": {"type": "string", "description": "Language code, e.g. 'en'. Optional (auto-detect)."},
                    "model": {"type": "string", "description": "whisper-1 (default) or vosk."},
                    "word_timestamps": {"type": "boolean", "description": "Include start/end time for every word."}},
                   ["path"]),
    "status": (tool_status,
               "Check that AI Voice Studio is running and see which engines and models are installed.",
               {}, []),
}


def tool_list():
    return [{"name": n, "description": d,
             "inputSchema": {"type": "object", "properties": props, "required": req}}
            for n, (_f, d, props, req) in TOOLS.items()]


# ── JSON-RPC over stdio ───────────────────────────────────────────────────
def handle(msg):
    """Returns a response dict, or None for notifications."""
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}

    def ok(result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def err(code, text):
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": text}}

    if "id" not in msg:                      # notification (initialized, cancelled, ...)
        return None
    if method == "initialize":
        want = params.get("protocolVersion")
        return ok({"protocolVersion": want if want in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[0],
                   "capabilities": {"tools": {}},
                   "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION}})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": tool_list()})
    if method == "tools/call":
        name = params.get("name")
        if name not in TOOLS:
            return err(-32602, f"Unknown tool: {name}")
        try:
            text, bad = TOOLS[name][0](params.get("arguments") or {}), False
        except ToolError as e:
            text, bad = str(e), True
        except Exception as e:
            log("tool crashed:", repr(e))
            text, bad = f"Unexpected error: {e}", True
        return ok({"content": [{"type": "text", "text": text}], "isError": bad})
    return err(-32601, f"Method not found: {method}")


def main():
    log(f"started; API at {api_base()}")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        for m in (msg if isinstance(msg, list) else [msg]):
            resp = handle(m)
            if resp is not None:
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()


if __name__ == "__main__":
    main()
