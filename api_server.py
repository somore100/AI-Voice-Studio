"""Local HTTP API so other programs can use this app's TTS / speech-to-text
instead of installing their own models.  (HARDENED COPY - see the audit notes.)

OpenAI-compatible endpoints (so "custom / local OpenAI provider" settings work):
    GET  /v1/models
    POST /v1/audio/speech          {"input", "model", "voice", "speed", "response_format"}
    POST /v1/audio/transcriptions  multipart: file, model, language, response_format
                                   (+ timestamp_granularities[]=word with verbose_json for word times)
    POST /v1/audio/translations    multipart: file (spoken audio -> English text)
Extras:
    GET  /v1/voices   GET /health
    /v1/audio/speech also accepts: language, pitch, volume, depth

Security model (changed):
  * An API key is REQUIRED unless the caller passes allow_no_key=True. Use
    ensure_token(prefs_path) to create and persist one on first start.
  * Requests that carry a browser Origin other than this server's own (or an
    explicitly allowed one), or Sec-Fetch-Site: cross-site / same-site, are
    refused. This is defence in depth behind the key.
  * /v1/audio/speech only accepts application/json (not a CORS "simple" type).
  * Uploads are identified by their content, never by the client's file name,
    decoded with hard limits, and ffmpeg is pinned to one demuxer and to the
    "file" protocol so playlists cannot make it open other files.
  * Bodies, connections, queued jobs and decode work are all bounded.
"""
import hmac
import io
import json
import os
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
from email.parser import HeaderParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ---- limits (module-level so an embedding app or a test can tune them) --------
MAX_BODY = 200 * 1024 * 1024       # largest upload (compressed bytes)
MAX_JSON_BODY = 1024 * 1024        # largest /audio/speech body
MAX_TEXT = 20000                   # characters of TTS input
MAX_AUDIO_SECONDS = 3600.0         # longest audio accepted for transcription
MAX_CHANNELS = 8
MIN_SAMPLE_RATE, MAX_SAMPLE_RATE = 4000, 192000
# decode "work" budget: frames x channels that we are willing to decode in-process
# (1 h of 48 kHz stereo). A 192 kHz 8-channel file hits it after 225 s.
MAX_DECODE_SAMPLES = int(3600 * 48000 * 2)
# only used when the streaming resampler (soxr) is missing and audio must be held in RAM
MAX_INPROC_MONO_BYTES = 64 * 1024 * 1024
DECODE_TIMEOUT = 120.0             # wall clock for the in-process decoder
FFMPEG_TIMEOUT = 120.0             # wall clock for ffmpeg
SOCKET_TIMEOUT = 30.0              # idle time on a connection
BODY_READ_TIMEOUT = 120.0          # total time to receive one request body
MAX_CONNECTIONS = 32               # open connections (each is one thread)
MAX_QUEUED_JOBS = 4                # speech/transcription jobs waiting behind the running one
MAX_INFLIGHT_BODY_BYTES = 256 * 1024 * 1024   # request bodies held in memory at once
MAX_MULTIPART_PARTS = 32
MAX_PART_HEADER = 8192

# ffmpeg demuxers we allow. Everything else (hls, concat, dash, sdp, image2, lavfi ...) is refused.
FFMPEG_FORMAT_WHITELIST = "wav,flac,ogg,mp3,aac,aiff,mov,mp4,m4a,3gp,3g2,mj2,matroska,webm"


class ApiError(Exception):
    def __init__(self, status, message, headers=None):
        super().__init__(message)
        self.status, self.message, self.headers = status, message, headers or {}


# ---- API key ------------------------------------------------------------------
def ensure_token(prefs_path):
    """Return the API key stored in prefs_path (JSON object, key "api_token"),
    creating and saving a random one (file mode 0600) when there is none."""
    try:
        with open(prefs_path, encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict):
            d = {}
    except (OSError, ValueError):
        d = {}
    tok = str(d.get("api_token") or "").strip()
    if tok:
        return tok
    tok = "avs-" + secrets.token_urlsafe(32)
    d["api_token"] = tok
    os.makedirs(os.path.dirname(prefs_path) or ".", exist_ok=True)
    tmp = prefs_path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, prefs_path)
    return tok


# ---- audio helpers (lazy imports: numpy/soundfile only when used) ----------
def encode_audio(wav_path, fmt):
    """Return (bytes, content_type) for the WAV at wav_path in the requested
    format. Falls back to WAV when the format can't be written."""
    fmt = (fmt or "wav")
    fmt = fmt.lower() if isinstance(fmt, str) else "wav"
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


def sniff_container(head):
    """Identify an upload by its first bytes. Returns the ffmpeg demuxer name(s)
    to try, in order. The client's file name and Content-Type are never used.
    Text formats (playlists, concat scripts, SDP ...) match nothing -> 415."""
    h = bytes(head[:16])
    if len(h) >= 12 and h[:4] in (b"RIFF", b"RF64", b"BW64") and h[8:12] == b"WAVE":
        return ["wav"]
    if h[:4] == b"fLaC":
        return ["flac"]
    if h[:4] == b"OggS":
        return ["ogg"]
    if len(h) >= 12 and h[:4] == b"FORM" and h[8:12] in (b"AIFF", b"AIFC"):
        return ["aiff"]
    if h[:4] == b"\x1a\x45\xdf\xa3":
        return ["matroska"]                      # also WebM
    if len(h) >= 8 and h[4:8] == b"ftyp":
        return ["mov"]                           # mp4 / m4a / mov / 3gp
    if h[:3] == b"ID3":
        return ["mp3", "aac"]
    if len(h) >= 2 and h[0] == 0xFF and (h[1] & 0xE0) == 0xE0:
        return ["aac"] if ((h[1] >> 1) & 3) == 0 else ["mp3"]
    raise ApiError(415, "Unsupported or unrecognised audio. Send WAV, FLAC, OGG/Opus, MP3, "
                        "AAC, M4A/MP4, WebM/MKV or AIFF.")


def _check_stream(channels, rate):
    if not 1 <= int(channels) <= MAX_CHANNELS:
        raise ApiError(413, f"Audio has {channels} channels; at most {MAX_CHANNELS} are accepted.")
    if not MIN_SAMPLE_RATE <= int(rate) <= MAX_SAMPLE_RATE:
        raise ApiError(413, f"Sample rate {rate} Hz is outside {MIN_SAMPLE_RATE}-{MAX_SAMPLE_RATE} Hz.")


def _too_long():
    return ApiError(413, f"Audio is longer than the {int(MAX_AUDIO_SECONDS)} s limit.")


def _decode_sndfile(src_path, out_path):
    """Decode with libsndfile in bounded blocks straight into a 16 kHz mono
    PCM16 WAV. libsndfile never follows references to other files. Returns
    True when done, False when it cannot open the file (caller tries ffmpeg).
    Limits are checked from the header first and enforced again while reading
    (a header can lie or say "unknown length")."""
    import numpy as np
    import soundfile as sf
    try:
        f = sf.SoundFile(src_path)
    except Exception:
        return False
    with f:
        ch, sr, frames = int(f.channels), int(f.samplerate), int(f.frames)
        _check_stream(ch, sr)
        known = 0 < frames < 2 ** 62
        if known and frames / sr > MAX_AUDIO_SECONDS:
            raise _too_long()
        if known and frames * ch > MAX_DECODE_SAMPLES:
            raise ApiError(413, "Audio is too large to decode (sample rate x channels x length). "
                                "Downmix or resample it first.")
        stream = None
        if sr != 16000:
            try:
                import soxr
                stream = soxr.ResampleStream(sr, 16000, 1, dtype="float32")
            except Exception:
                stream = None
        held = [] if (sr != 16000 and stream is None) else None      # no streaming resampler
        deadline = time.monotonic() + DECODE_TIMEOUT
        total = written = 0
        block = max(4096, min(sr, 65536))
        with sf.SoundFile(out_path, "w", samplerate=16000, channels=1, subtype="PCM_16") as out:
            while True:
                b = f.read(block, dtype="float32", always_2d=True)
                n = len(b)
                if n == 0:
                    break
                total += n
                if total / sr > MAX_AUDIO_SECONDS:
                    raise _too_long()
                if total * ch > MAX_DECODE_SAMPLES:
                    raise ApiError(413, "Audio is too large to decode (sample rate x channels x length).")
                if time.monotonic() > deadline:
                    raise ApiError(413, "Decoding this audio took too long.")
                mono = b.mean(axis=1, dtype=np.float32) if ch > 1 else b[:, 0]
                if sr == 16000:
                    y = mono
                elif stream is not None:
                    y = stream.resample_chunk(np.ascontiguousarray(mono), last=False)
                else:
                    held.append(mono.copy())
                    if total * 4 > MAX_INPROC_MONO_BYTES:
                        raise ApiError(413, "Audio is too long to convert on this machine without "
                                            "ffmpeg. Install ffmpeg or send 16 kHz audio.")
                    continue
                if len(y):
                    out.write(np.clip(y, -1.0, 1.0))
                    written += len(y)
            if stream is not None:
                y = stream.resample_chunk(np.zeros(0, dtype=np.float32), last=True)
                if len(y):
                    out.write(np.clip(y, -1.0, 1.0))
                    written += len(y)
            elif held:
                y = np.concatenate(held)
                held.clear()
                try:
                    import librosa
                    y = librosa.resample(y, orig_sr=sr, target_sr=16000)
                except Exception:
                    from math import gcd
                    from scipy.signal import resample_poly
                    g = gcd(sr, 16000)
                    y = resample_poly(y, 16000 // g, sr // g).astype(np.float32)
                out.write(np.clip(y, -1.0, 1.0))
                written += len(y)
    if written < 160:
        raise ApiError(400, "Audio is empty.")
    return True


def ffmpeg_decode_cmd(ff, fmt, src_path, out_path):
    """The one ffmpeg command line used for uploads.
      -f <fmt>              one demuxer, chosen by us from the file's magic bytes: no probing
      -format_whitelist     refuses every other demuxer even for nested opens
      -protocol_whitelist   only plain local files: no http, concat:, crypto:, subfile:, data: ...
      -map 0:a:0 -vn -sn -dn  first audio stream only
      -t                    hard length cap (one second over the limit so we can reject, not truncate)
    """
    return [ff, "-nostdin", "-hide_banner", "-v", "error",
            "-protocol_whitelist", "file", "-format_whitelist", FFMPEG_FORMAT_WHITELIST,
            "-f", fmt, "-i", src_path,
            "-map", "0:a:0", "-vn", "-sn", "-dn",
            "-ac", "1", "-ar", "16000", "-t", f"{MAX_AUDIO_SECONDS + 1.0:.3f}",
            "-c:a", "pcm_s16le", "-f", "wav", "-y", out_path]


def _decode_ffmpeg(ff, fmts, src_path, out_path, cwd):
    """Run ffmpeg (streaming file -> file, nothing buffered in Python)."""
    import soundfile as sf
    for fmt in fmts:
        try:
            r = subprocess.run(ffmpeg_decode_cmd(ff, fmt, src_path, out_path), cwd=cwd,
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=FFMPEG_TIMEOUT)
        except subprocess.TimeoutExpired:
            raise ApiError(413, "Decoding this audio took too long.")
        if r.returncode != 0:
            continue
        try:
            info = sf.info(out_path)
        except Exception:
            continue
        if info.frames / 16000.0 > MAX_AUDIO_SECONDS:
            raise _too_long()
        if info.frames < 160:
            raise ApiError(400, "Audio is empty.")
        return True
    return False


def decode_to_wav16k(data, filename=""):
    """Decode uploaded audio to a mono 16 kHz PCM16 WAV temp file and return its
    path (caller deletes it). `filename` is ignored on purpose: it is chosen by
    the client and must not influence how the bytes are interpreted."""
    fmts = sniff_container(bytes(data[:16]))
    work = tempfile.mkdtemp(prefix="avs_up_")            # private (0700): nothing else lives here
    fd, out_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    ok = False
    try:
        src = os.path.join(work, "upload.bin")
        with open(src, "wb") as f:
            f.write(data)
        try:
            ok = _decode_sndfile(src, out_path)
        except ApiError:
            raise
        except Exception:                 # corrupt / truncated for libsndfile: let ffmpeg try
            ok = False
        if not ok:
            ff = shutil.which("ffmpeg")
            if not ff:
                raise ApiError(400, "Could not decode this audio format. Send WAV, FLAC "
                                    "or OGG (or install ffmpeg for m4a/webm/aac).")
            ok = _decode_ffmpeg(ff, fmts, src, out_path, work)
            if not ok:
                raise ApiError(400, "Could not decode the audio.")
        return out_path
    finally:
        shutil.rmtree(work, ignore_errors=True)
        if not ok:
            try: os.remove(out_path)
            except OSError: pass


def parse_multipart(content_type, body):
    """-> ({field: str}, {field: (filename, bytes-like)}). Works on a memoryview:
    the file part is not copied."""
    hp = HeaderParser()
    boundary = hp.parsestr("Content-Type: " + content_type + "\r\n\r\n").get_param("boundary")
    if not boundary or len(boundary) > 70:
        raise ApiError(400, "Expected multipart/form-data with a boundary.")
    delim = b"--" + boundary.encode("latin-1", "replace")
    mv = memoryview(body)
    fields, files = {}, {}
    pos = body.find(delim)
    count = 0
    while pos != -1:
        start = pos + len(delim)
        if body[start:start + 2] == b"--":
            break
        nxt = body.find(b"\r\n" + delim, start)
        if nxt == -1:
            raise ApiError(400, "Malformed multipart body.")
        count += 1
        if count > MAX_MULTIPART_PARTS:
            raise ApiError(400, "Too many form parts.")
        hend = body.find(b"\r\n\r\n", start, min(nxt + 4, start + MAX_PART_HEADER))
        if hend == -1 or hend > nxt:
            raise ApiError(400, "Malformed multipart part.")
        part = hp.parsestr(bytes(mv[start:hend]).decode("utf-8", "replace").lstrip("\r\n") + "\r\n\r\n")
        name = part.get_param("name", header="content-disposition")
        payload = mv[hend + 4:nxt]
        if name:
            fn = part.get_filename()
            if fn is not None:
                files[name] = (fn, payload)
            else:
                if len(payload) > 65536:
                    raise ApiError(400, f"Form field '{name}' is too long.")
                val = bytes(payload).decode("utf-8", "replace").strip()
                # repeated fields (e.g. timestamp_granularities[] = word, segment) are joined
                fields[name] = fields[name] + "," + val if name in fields else val
        pos = nxt + 2
    return fields, files


def _fmt_ts(t, comma):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{',' if comma else '.'}{ms:03d}"


def _status_page(api):
    base = f"http://127.0.0.1:{api.port}/v1"
    key = ("Required: send <code>Authorization: Bearer YOUR_KEY</code> (copy it from the app)"
           if api.token else "<b>Not set</b> (any program on this computer can use the API)")
    return f"""<!doctype html><meta charset="utf-8"><title>Audiovane API</title>
<body style="font-family:system-ui;background:#1a1b26;color:#c0caf5;max-width:640px;margin:40px auto;padding:0 16px">
<h2 style="color:#9ece6a">&#10003; Audiovane API is running</h2>
<p>Base URL: <code>{base}</code><br>API key: {key}</p>
<ul><li><code>POST /v1/audio/speech</code> &ndash; text to speech</li>
<li><code>POST /v1/audio/transcriptions</code> &ndash; speech to text</li>
<li><code>POST /v1/audio/translations</code> &ndash; speech to English text</li>
<li><code>GET /v1/models</code>, <code>GET /v1/voices</code></li></ul>
<p style="opacity:.7">This page is only visible on this computer.</p></body>"""


# ---- server -----------------------------------------------------------------
class _BoundedServer(ThreadingHTTPServer):
    """One thread per connection, but never more than max_connections of them."""
    daemon_threads = True
    request_queue_size = 16
    # Windows: SO_REUSEADDR lets a second process bind the same port, so a busy
    # port would not be reported. (Not exercised in the audit: no Windows host.)
    allow_reuse_address = (os.name != "nt")

    def __init__(self, addr, handler, max_connections):
        self._slots = threading.BoundedSemaphore(max_connections)
        super().__init__(addr, handler)

    def server_bind(self):
        if os.name == "nt":
            import socket
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            try:
                request.settimeout(2)
                request.sendall(b"HTTP/1.1 503 Service Unavailable\r\nRetry-After: 5\r\n"
                                b"Connection: close\r\nContent-Length: 0\r\n\r\n")
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()

    def handle_error(self, request, client_address):
        pass                                        # timeouts / resets are routine


class ApiServer:
    """backend must provide:
        models() -> {"tts": [str], "stt": [str]}
        voices() -> [dict(engine, voice, label, gender, lang)]
        tts(text, model, voice, language, speed, pitch, volume, depth) -> wav path
        stt(wav16k_path, model, language, translate[, words=True]) ->
            {"text", "language", "segments"?, "words"?: [{"word","start","end"}]}
            (`words=True` is only passed when the client asked for word timestamps)
    Backend methods may raise ApiError. They are called one at a time.

    token           API key. Required: an empty token raises ValueError unless
                    allow_no_key=True (the user's explicit choice).
    allowed_origins extra browser origins (e.g. "http://localhost:3000") allowed
                    to call the API. This server's own origin is always allowed."""

    def __init__(self, backend, port=8765, token="", log=print, allow_no_key=False,
                 allowed_origins=()):
        token = (token or "").strip()
        if not token and not allow_no_key:
            raise ValueError("An API key is required (use ensure_token(), or pass "
                             "allow_no_key=True to run without one).")
        self.backend, self.port, self.token, self.log = backend, int(port), token, log
        self._extra_origins = {str(o).rstrip("/").lower() for o in allowed_origins}
        self._httpd = None
        self._thread = None
        self._lock = threading.Lock()      # models are heavy: one job at a time
        self._jobs = threading.BoundedSemaphore(1 + MAX_QUEUED_JOBS)
        self._mem_lock = threading.Lock()
        self._inflight = 0

    @property
    def running(self):
        return self._httpd is not None

    def _origins(self):
        p = self._httpd.server_address[1] if self._httpd else self.port
        return {f"http://127.0.0.1:{p}", f"http://localhost:{p}", f"http://[::1]:{p}"} | self._extra_origins

    def _reserve(self, n):
        with self._mem_lock:
            if self._inflight + n > MAX_INFLIGHT_BODY_BYTES and self._inflight > 0:
                return False
            self._inflight += n
            return True

    def _unreserve(self, n):
        with self._mem_lock:
            self._inflight -= n

    def start(self):
        if self._httpd:
            return
        api = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            server_version = "Audiovane"
            sys_version = ""
            timeout = SOCKET_TIMEOUT             # idle read timeout on the socket

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
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Cross-Origin-Resource-Policy", "same-origin")
                self.send_header("Cache-Control", "no-store")
                if self.close_connection:
                    self.send_header("Connection", "close")
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def _err(self, status, msg, extra=None):
                self._send(status, {"error": {"message": msg, "type": "invalid_request_error"}},
                           extra=extra)

            def _refuse(self, status, msg, extra=None):
                """Error BEFORE the body was read: the connection must not be reused,
                or the unread body would be parsed as the next request."""
                self.close_connection = True
                self._err(status, msg, extra)
                return False

            def _guard(self, public=False):
                host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
                if host not in ("127.0.0.1", "localhost", "::1"):
                    return self._refuse(403, "Forbidden host.")
                # Browser requests from other sites (defence in depth behind the key).
                origin = self.headers.get("Origin")
                if origin is not None:
                    if origin.rstrip("/").lower() not in api._origins():
                        return self._refuse(403, "Cross-origin requests are not allowed.")
                elif (self.headers.get("Sec-Fetch-Site") or "none").lower() not in ("none", "same-origin"):
                    return self._refuse(403, "Cross-origin requests are not allowed.")
                if api.token and not public:
                    auth = self.headers.get("Authorization", "")
                    if not hmac.compare_digest(auth.encode("utf-8", "replace"),
                                               ("Bearer " + api.token).encode("utf-8")):
                        return self._refuse(401, "Missing or wrong API token.",
                                            {"WWW-Authenticate": "Bearer"})
                return True

            def _length(self, limit):
                """Validated Content-Length, or an ApiError. Nothing is read here."""
                if self.headers.get("Transfer-Encoding"):
                    raise ApiError(411, "Send a Content-Length (chunked bodies are not supported).")
                raw = self.headers.get("Content-Length")
                if raw is None:
                    raise ApiError(411, "Content-Length is required.")
                raw = raw.strip()
                if not (raw.isascii() and raw.isdigit()) or len(raw) > 12:
                    raise ApiError(400, "Invalid Content-Length.")
                n = int(raw)
                if n > limit:
                    raise ApiError(413, "Request too large.")
                return n

            def _read(self, n):
                """Read exactly n bytes with an overall deadline (slow senders)."""
                buf = bytearray(n)
                mv, got = memoryview(buf), 0
                deadline = time.monotonic() + BODY_READ_TIMEOUT
                while got < n:
                    if time.monotonic() > deadline:
                        raise ApiError(408, "Request body took too long.")
                    try:
                        # readinto1 = at most one socket read, so the deadline is re-checked
                        # even when a client trickles one byte at a time
                        k = self.rfile.readinto1(mv[got:min(n, got + 1024 * 1024)])
                    except (TimeoutError, OSError):
                        raise ApiError(408, "Request body timed out.")
                    if not k:
                        raise ApiError(400, "Request body ended early.")
                    got += k
                return bytes(buf) if n <= MAX_JSON_BODY else buf

            # -- routes
            def do_GET(self):
                path = self.path.split("?")[0].rstrip("/")
                if not self._guard(public=path in ("", "/health")): return
                try:
                    if path == "/health":
                        self._send(200, {"status": "ok", "app": "Audiovane"})
                    elif path == "":
                        self._send(200, _status_page(api), "text/html; charset=utf-8")
                    elif path == "/v1/models":
                        m = api.backend.models()
                        data = [{"id": i, "object": "model", "owned_by": "audiovane",
                                 "capabilities": "tts"} for i in m.get("tts", [])]
                        data += [{"id": i, "object": "model", "owned_by": "audiovane",
                                  "capabilities": "stt"} for i in m.get("stt", [])]
                        self._send(200, {"object": "list", "data": data})
                    elif path in ("/v1/voices", "/voices"):
                        self._send(200, {"voices": api.backend.voices()})
                    else:
                        self._err(404, "Unknown endpoint.")
                except (BrokenPipeError, ConnectionResetError, TimeoutError):
                    self.close_connection = True
                except Exception as e:
                    api.log(f"[AVS] API error: {e!r}")
                    try: self._err(500, "Internal error (see the app log).")
                    except Exception: pass

            def _other(self):
                self._refuse(405, "Method not allowed.", {"Allow": "GET, POST"})
            do_OPTIONS = do_PUT = do_DELETE = do_PATCH = do_HEAD = _other

            def do_POST(self):
                if not self._guard(): return
                path = self.path.split("?")[0].rstrip("/")
                speech = path == "/v1/audio/speech"
                stt = path in ("/v1/audio/transcriptions", "/v1/audio/translations")
                ct = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                # Everything below runs before a single body byte is read.
                if not (speech or stt):
                    return self._refuse(404, "Unknown endpoint.")
                if speech and ct != "application/json":
                    return self._refuse(415, "Send application/json.")
                if stt and ct != "multipart/form-data":
                    return self._refuse(415, "Send multipart/form-data with a 'file' field.")
                try:
                    n = self._length(MAX_JSON_BODY if speech else MAX_BODY)
                except ApiError as e:
                    return self._refuse(e.status, e.message)
                if not api._jobs.acquire(blocking=False):
                    return self._refuse(429, "Busy: too many requests are waiting. Try again shortly.",
                                        {"Retry-After": "5"})
                reserved = False
                try:
                    if not api._reserve(n):
                        return self._refuse(429, "Busy: uploads in progress use the memory budget.",
                                            {"Retry-After": "5"})
                    reserved = True
                    try:
                        body = self._read(n)
                    except ApiError as e:
                        return self._refuse(e.status, e.message)
                    try:
                        if speech:
                            self._speech(body)
                        else:
                            self._transcribe(body, translate=path.endswith("translations"))
                    except ApiError as e:
                        self._err(e.status, e.message, e.headers)
                    except (BrokenPipeError, ConnectionResetError, TimeoutError):
                        self.close_connection = True
                    except Exception as e:
                        api.log(f"[AVS] API error: {e!r}")
                        try: self._err(500, "Internal error (see the app log).")
                        except Exception: pass
                finally:
                    if reserved:
                        api._unreserve(n)
                    api._jobs.release()

            def _speech(self, body):
                try:
                    req = json.loads(body.decode("utf-8") or "{}")
                except ValueError:
                    raise ApiError(400, "Body must be JSON.")
                if not isinstance(req, dict):
                    raise ApiError(400, "Body must be a JSON object.")
                text = str(req.get("input") or req.get("text") or "").strip()
                if not text:
                    raise ApiError(400, "'input' is empty.")
                if len(text) > MAX_TEXT:
                    raise ApiError(400, f"'input' is longer than {MAX_TEXT} characters.")
                def num(k, d, lo, hi):
                    try:
                        v = float(req.get(k, d))
                    except (TypeError, ValueError):
                        raise ApiError(400, f"'{k}' must be a number.")
                    if v != v:                               # NaN
                        raise ApiError(400, f"'{k}' must be a number.")
                    return min(max(v, lo), hi)
                def opt(k):
                    v = req.get(k)
                    if v is not None and (not isinstance(v, str) or len(v) > 512):
                        raise ApiError(400, f"'{k}' must be a short string.")
                    return v
                args = (text, opt("model"), opt("voice"), opt("language"),
                        num("speed", 1.0, 0.25, 4.0), num("pitch", 0.0, -12.0, 12.0),
                        num("volume", 1.0, 0.0, 2.0), num("depth", 0.0, -8.0, 8.0))
                fmt = opt("response_format")
                with api._lock:
                    wav = api.backend.tts(*args)
                try:
                    data, ctype = encode_audio(wav, fmt)
                finally:
                    try: os.remove(wav)
                    except OSError: pass
                self._send(200, data, ctype)

            def _transcribe(self, body, translate):
                fields, files = parse_multipart(self.headers.get("Content-Type", ""), body)
                if "file" not in files:
                    raise ApiError(400, "Missing 'file'.")
                _fn, data = files["file"]
                gran = (fields.get("timestamp_granularities[]")
                        or fields.get("timestamp_granularities") or "").lower()
                want_words = "word" in [g.strip() for g in gran.split(",")]
                # Decode inside the lock: decoding is CPU/disk work too, so only one runs at a time.
                with api._lock:
                    wav = decode_to_wav16k(data)
                    del data, files, body
                    try:
                        extra = {"words": True} if want_words else {}
                        res = api.backend.stt(wav, fields.get("model"),
                                              fields.get("language") or None, translate, **extra)
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
                    out = {"task": "translate" if translate else "transcribe",
                           "language": res.get("language"), "text": text,
                           "segments": segs}
                    if want_words:
                        out["words"] = res.get("words") or []
                    self._send(200, out)
                else:
                    self._send(200, {"text": text})

        self._httpd = _BoundedServer(("127.0.0.1", self.port), Handler, MAX_CONNECTIONS)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        self.log(f"[AVS] API server listening on http://127.0.0.1:{self.port}"
                 f"{'' if self.token else ' (NO API KEY: open to every local program)'}")

    def stop(self):
        if self._httpd:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            finally:
                self._httpd = None
                self.log("[AVS] API server stopped")
