"""Local HTTP API so other programs can use this app's TTS / speech-to-text
instead of installing their own models.

OpenAI-compatible endpoints (so "custom / local OpenAI provider" settings work):
    GET  /v1/models
    POST /v1/audio/speech          {"input", "model", "voice", "speed", "response_format"}
    POST /v1/audio/transcriptions  multipart: file, model, language, response_format
    POST /v1/audio/translations    multipart: file (spoken audio -> English text)
Extras:
    GET  /v1/voices   GET /health
    /v1/audio/speech also accepts: language, pitch, volume, depth

Stdlib only. The actual work is done by a `backend` object (see main.py's
_ApiBackend), so this file has no dependency on the GUI or the models.
Binds to 127.0.0.1 only and rejects requests whose Host header is not local
(blocks DNS-rebinding from web pages). Optional bearer token.
"""
import io
import json
import os
import shutil
import subprocess
import tempfile
import threading
from email.parser import BytesParser
from email.policy import default as _email_policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_BODY = 200 * 1024 * 1024       # 200 MB upload cap
MAX_TEXT = 20000                   # characters of TTS input


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


# ---- audio helpers (lazy imports: numpy/soundfile only when used) ----------
def encode_audio(wav_path, fmt):
    """Return (bytes, content_type) for the WAV at wav_path in the requested
    format. Falls back to WAV when the format can't be written."""
    fmt = (fmt or "wav").lower()
    if fmt != "wav":
        try:
            import soundfile as sf
            want = {"mp3": "MP3", "flac": "FLAC", "ogg": "OGG", "opus": "OGG"}.get(fmt)
            if want and want in sf.available_formats():
                y, sr = sf.read(wav_path, dtype="float32")
                buf = io.BytesIO()
                sub = {"MP3": None, "FLAC": None, "OGG": "OPUS" if fmt == "opus" else "VORBIS"}[want]
                if sub and sub not in sf.available_subtypes(want):
                    sub = None
                sf.write(buf, y, sr, format=want, subtype=sub)
                ctype = {"mp3": "audio/mpeg", "flac": "audio/flac",
                         "ogg": "audio/ogg", "opus": "audio/ogg"}[fmt]
                return buf.getvalue(), ctype
        except Exception:
            pass
    with open(wav_path, "rb") as f:
        return f.read(), "audio/wav"


def decode_to_wav16k(data, filename=""):
    """Decode uploaded audio (wav/flac/ogg/mp3...) to a mono 16 kHz WAV temp
    file. Returns its path (caller deletes it)."""
    import numpy as np
    import soundfile as sf
    y = sr = None
    try:
        y, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
        y = y.mean(axis=1)
    except Exception:
        ff = shutil.which("ffmpeg")
        if not ff:
            raise ApiError(400, "Could not decode this audio format. Send WAV, FLAC "
                                "or OGG (or install ffmpeg for mp3/m4a/webm).")
        suffix = os.path.splitext(filename or "")[1] or ".bin"
        src = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        try:
            src.write(data); src.close()
            out = subprocess.run(
                [ff, "-v", "error", "-i", src.name, "-f", "f32le", "-ac", "1",
                 "-ar", "16000", "-"], capture_output=True, timeout=120)
            if out.returncode != 0 or not out.stdout:
                raise ApiError(400, "ffmpeg could not decode the audio.")
            y, sr = np.frombuffer(out.stdout, dtype=np.float32), 16000
        finally:
            try: os.remove(src.name)
            except OSError: pass
    if sr != 16000 and y.size:
        try:
            import librosa
            y = librosa.resample(y, orig_sr=sr, target_sr=16000)
        except Exception:
            from scipy.signal import resample_poly
            from math import gcd
            g = gcd(int(sr), 16000)
            y = resample_poly(y, 16000 // g, int(sr) // g).astype(np.float32)
    if y.size < 160:
        raise ApiError(400, "Audio is empty.")
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False); tmp.close()
    sf.write(tmp.name, y.astype(np.float32), 16000, subtype="PCM_16")
    return tmp.name


def parse_multipart(content_type, body):
    """-> ({field: str}, {field: (filename, bytes)})"""
    msg = BytesParser(policy=_email_policy).parsebytes(
        b"Content-Type: " + content_type.encode("latin-1") +
        b"\r\nMIME-Version: 1.0\r\n\r\n" + body)
    fields, files = {}, {}
    if not msg.is_multipart():
        raise ApiError(400, "Expected multipart/form-data.")
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        fn = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        if fn is not None:
            files[name] = (fn, payload)
        else:
            fields[name] = payload.decode("utf-8", "replace").strip()
    return fields, files


def _fmt_ts(t, comma):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{',' if comma else '.'}{ms:03d}"


def _status_page(api):
    base = f"http://127.0.0.1:{api.port}/v1"
    key = ("Required: send <code>Authorization: Bearer YOUR_KEY</code>"
           if api.token else "Not set (anyone on this computer can use it)")
    return f"""<!doctype html><meta charset="utf-8"><title>AI Voice Studio API</title>
<body style="font-family:system-ui;background:#1a1b26;color:#c0caf5;max-width:640px;margin:40px auto;padding:0 16px">
<h2 style="color:#9ece6a">&#10003; AI Voice Studio API is running</h2>
<p>Base URL: <code>{base}</code><br>API key: {key}</p>
<ul><li><code>POST /v1/audio/speech</code> &ndash; text to speech</li>
<li><code>POST /v1/audio/transcriptions</code> &ndash; speech to text</li>
<li><code>POST /v1/audio/translations</code> &ndash; speech to English text</li>
<li><code>GET /v1/models</code>, <code>GET /v1/voices</code></li></ul>
<p style="opacity:.7">This page is only visible on this computer.</p></body>"""


# ---- server -----------------------------------------------------------------
class ApiServer:
    """backend must provide:
        models() -> {"tts": [str], "stt": [str]}
        voices() -> [dict(engine, voice, label, gender, lang)]
        tts(text, model, voice, language, speed, pitch, volume, depth) -> wav path
        stt(wav16k_path, model, language, translate) -> {"text", "language", "segments"?}
    Backend methods may raise ApiError. They are called one at a time."""

    def __init__(self, backend, port=8765, token="", log=print):
        self.backend, self.port, self.token, self.log = backend, int(port), token or "", log
        self._httpd = None
        self._thread = None
        self._lock = threading.Lock()      # models are heavy: one job at a time

    @property
    def running(self):
        return self._httpd is not None

    def start(self):
        if self._httpd:
            return
        api = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            server_version = "AIVoiceStudio"

            def log_message(self, fmt, *a):
                api.log(f"[AVS] API {self.address_string()} {fmt % a}")

            # -- plumbing
            def _send(self, status, body, ctype="application/json", extra=None):
                if isinstance(body, (dict, list)):
                    body = json.dumps(body).encode("utf-8")
                elif isinstance(body, str):
                    body = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def _err(self, status, msg):
                self._send(status, {"error": {"message": msg, "type": "invalid_request_error"}})

            def _guard(self, public=False):
                host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
                if host not in ("127.0.0.1", "localhost", "::1"):
                    self._err(403, "Forbidden host.")
                    return False
                if api.token and not public:
                    auth = self.headers.get("Authorization", "")
                    if auth != "Bearer " + api.token:
                        self._err(401, "Missing or wrong API token.")
                        return False
                return True

            def _body(self):
                n = int(self.headers.get("Content-Length") or 0)
                if n > MAX_BODY:
                    raise ApiError(413, "Request too large.")
                return self.rfile.read(n) if n else b""

            def _run(self, fn):
                try:
                    fn()
                except ApiError as e:
                    self._err(e.status, e.message)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                except Exception as e:
                    api.log(f"[AVS] API error: {e!r}")
                    try: self._err(500, f"{type(e).__name__}: {e}")
                    except Exception: pass

            # -- routes
            def do_GET(self):
                path = self.path.split("?")[0].rstrip("/")
                if not self._guard(public=path in ("", "/health")): return
                def go():
                    if path == "/health":
                        self._send(200, {"status": "ok", "app": "AI Voice Studio"})
                    elif path == "":
                        self._send(200, _status_page(api), "text/html; charset=utf-8")
                    elif path == "/v1/models":
                        m = api.backend.models()
                        data = [{"id": i, "object": "model", "owned_by": "ai-voice-studio",
                                 "capabilities": "tts"} for i in m.get("tts", [])]
                        data += [{"id": i, "object": "model", "owned_by": "ai-voice-studio",
                                  "capabilities": "stt"} for i in m.get("stt", [])]
                        self._send(200, {"object": "list", "data": data})
                    elif path in ("/v1/voices", "/voices"):
                        self._send(200, {"voices": api.backend.voices()})
                    else:
                        raise ApiError(404, "Unknown endpoint.")
                self._run(go)

            def do_POST(self):
                if not self._guard(): return
                path = self.path.split("?")[0].rstrip("/")
                def go():
                    body = self._body()
                    if path == "/v1/audio/speech":
                        self._speech(body)
                    elif path in ("/v1/audio/transcriptions", "/v1/audio/translations"):
                        self._transcribe(body, translate=path.endswith("translations"))
                    else:
                        raise ApiError(404, "Unknown endpoint.")
                self._run(go)

            def _speech(self, body):
                try:
                    req = json.loads(body.decode("utf-8") or "{}")
                except ValueError:
                    raise ApiError(400, "Body must be JSON.")
                text = str(req.get("input") or req.get("text") or "").strip()
                if not text:
                    raise ApiError(400, "'input' is empty.")
                if len(text) > MAX_TEXT:
                    raise ApiError(400, f"'input' is longer than {MAX_TEXT} characters.")
                def num(k, d, lo, hi):
                    try: return min(max(float(req.get(k, d)), lo), hi)
                    except (TypeError, ValueError): raise ApiError(400, f"'{k}' must be a number.")
                with api._lock:
                    wav = api.backend.tts(
                        text, req.get("model"), req.get("voice"), req.get("language"),
                        num("speed", 1.0, 0.25, 4.0), num("pitch", 0.0, -12.0, 12.0),
                        num("volume", 1.0, 0.0, 2.0), num("depth", 0.0, -8.0, 8.0))
                try:
                    data, ctype = encode_audio(wav, req.get("response_format"))
                finally:
                    try: os.remove(wav)
                    except OSError: pass
                self._send(200, data, ctype)

            def _transcribe(self, body, translate):
                ct = self.headers.get("Content-Type", "")
                if "multipart/form-data" not in ct:
                    raise ApiError(400, "Send multipart/form-data with a 'file' field.")
                fields, files = parse_multipart(ct, body)
                if "file" not in files:
                    raise ApiError(400, "Missing 'file'.")
                fn, data = files["file"]
                wav = decode_to_wav16k(data, fn)
                try:
                    with api._lock:
                        res = api.backend.stt(wav, fields.get("model"),
                                              fields.get("language") or None, translate)
                finally:
                    try: os.remove(wav)
                    except OSError: pass
                text = res.get("text", "")
                fmt = (fields.get("response_format") or "json").lower()
                segs = res.get("segments") or []
                if fmt == "text":
                    self._send(200, text + "\n", "text/plain; charset=utf-8")
                elif fmt in ("srt", "vtt") and segs:
                    out = ["WEBVTT\n"] if fmt == "vtt" else []
                    for i, s in enumerate(segs, 1):
                        if fmt == "srt": out.append(str(i))
                        out.append(f"{_fmt_ts(s['start'], fmt == 'srt')} --> "
                                   f"{_fmt_ts(s['end'], fmt == 'srt')}")
                        out.append(s["text"].strip() + "\n")
                    self._send(200, "\n".join(out), "text/plain; charset=utf-8")
                elif fmt == "verbose_json":
                    self._send(200, {"task": "translate" if translate else "transcribe",
                                     "language": res.get("language"), "text": text,
                                     "segments": segs})
                else:
                    self._send(200, {"text": text})

        self._httpd = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        self.log(f"[AVS] API server listening on http://127.0.0.1:{self.port}")

    def stop(self):
        if self._httpd:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            finally:
                self._httpd = None
                self.log("[AVS] API server stopped")
