"""Regression tests for the hardened api_server.py (fake backend, loopback only,
ephemeral ports). Run:  <venv python> -B -m unittest -v test_hardening
Needs numpy + soundfile; the ffmpeg tests are skipped when ffmpeg or tests/media is missing."""
import http.client
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import api_server as A

import numpy as np
import soundfile as sf

MEDIA = os.path.join(HERE, "media")
# the ffmpeg / format tests need ffmpeg AND the fixture files (tests/media, not committed: 8 MB)
FF = shutil.which("ffmpeg") if os.path.isdir(MEDIA) else None
KEY = "avs-test-key-0123456789"
EVIL = {"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"}


class Backend:
    def __init__(self):
        self.calls, self.gate, self.entered = [], None, threading.Semaphore(0)

    def models(self): return {"tts": ["fake"], "stt": ["whisper-1"]}
    def voices(self): return [{"key": "fake:a"}]

    def tts(self, text, *a):
        self.calls.append(("tts", text))
        self.entered.release()
        if self.gate is not None:
            self.gate.wait(30)
        fd, p = tempfile.mkstemp(suffix=".wav"); os.close(fd)
        sf.write(p, np.zeros(1600, dtype=np.float32), 16000, subtype="PCM_16")
        return p

    def stt(self, wav, model, language, translate, **kw):
        i = sf.info(wav)
        self.calls.append(("stt", i.frames))
        return {"text": json.dumps({"sr": i.samplerate, "ch": i.channels, "sub": i.subtype,
                                    "dur": round(i.frames / i.samplerate, 3)})}


def start(token=KEY, **kw):
    be = Backend()
    srv = A.ApiServer(be, 0, token, log=lambda *a: None, **kw)
    srv.start()
    return srv, be, srv._httpd.server_address[1]


def call(port, method, path, body=None, headers=None, key=KEY, timeout=60):
    h = dict(headers or {})
    if key:
        h["Authorization"] = "Bearer " + key
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        return r.status, dict(r.getheaders()), r.read()
    finally:
        c.close()


def raw(port, data, wait=3.0, shut=False):
    s = socket.create_connection(("127.0.0.1", port)); s.sendall(data)
    if shut: s.shutdown(socket.SHUT_WR)
    s.settimeout(wait); out = b""
    try:
        while True:
            d = s.recv(65536)
            if not d: break
            out += d
    except socket.timeout:
        out += b"<<still open>>"
    s.close()
    return out


def multipart(data, fname="a.wav", fields=(("model", "whisper-1"),)):
    b = uuid.uuid4().hex
    out = [f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields]
    out.append(f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{fname}"\r\n'
               "Content-Type: application/octet-stream\r\n\r\n".encode() + data + b"\r\n")
    out.append(f"--{b}--\r\n".encode())
    return b"".join(out), {"Content-Type": f"multipart/form-data; boundary={b}"}


def upload(port, data, fname="a.wav", extra=None, **kw):
    body, h = multipart(data, fname)
    h.update(extra or {})
    return call(port, "POST", "/v1/audio/transcriptions", body, h, **kw)


def speech(port, headers=None, body=None, **kw):
    h = {"Content-Type": "application/json"}; h.update(headers or {})
    return call(port, "POST", "/v1/audio/speech", body or b'{"input":"hello"}', h, **kw)


def ffgen(name, *args):
    os.makedirs(MEDIA, exist_ok=True)
    p = os.path.join(MEDIA, name)
    if not os.path.exists(p):
        subprocess.run([FF, "-v", "error", "-y", *args, p], check=True)
    return p


def rd(p):
    with open(p, "rb") as f:
        return f.read()


# ───────────────────────────── H1: auth + origin ─────────────────────────────
class AuthAndOrigin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv, cls.be, cls.port = start()
        cls.wav = io_wav(1.0)

    @classmethod
    def tearDownClass(cls): cls.srv.stop()

    def setUp(self): self.be.calls.clear()

    def test_key_is_required_by_default(self):
        with self.assertRaises(ValueError):
            A.ApiServer(Backend(), 0, "")
        A.ApiServer(Backend(), 0, "", allow_no_key=True)       # explicit opt-out still possible

    def test_ensure_token_creates_private_persistent_key(self):
        d = tempfile.mkdtemp(); p = os.path.join(d, "sub", "prefs.json")
        os.makedirs(os.path.dirname(p)); open(p, "w").write('{"api_port": 9000}')  # noqa
        t1 = A.ensure_token(p); t2 = A.ensure_token(p)
        self.assertTrue(t1.startswith("avs-") and len(t1) >= 40)
        self.assertEqual(t1, t2)
        self.assertEqual(json.load(open(p))["api_port"], 9000)
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)
        shutil.rmtree(d)

    def test_every_sensitive_endpoint_needs_the_key(self):
        body, mh = multipart(self.wav)
        cases = [("GET", "/v1/models", None, {}), ("GET", "/v1/voices", None, {}), ("GET", "/voices", None, {}),
                 ("POST", "/v1/audio/speech", b'{"input":"x"}', {"Content-Type": "application/json"}),
                 ("POST", "/v1/audio/transcriptions", body, mh), ("POST", "/v1/audio/translations", body, mh)]
        for m, p, b, h in cases:
            for k in (None, "wrong", KEY + "x", KEY[:-1]):
                st, hd, _ = call(self.port, m, p, b, h, key=k)
                self.assertEqual(st, 401, f"{m} {p} key={k!r}")
            self.assertEqual(call(self.port, m, p, b, h)[0], 200, f"{m} {p} with key")
        self.assertEqual(call(self.port, "GET", "/health", key=None)[0], 200)
        self.assertEqual(len([c for c in self.be.calls]), 3)       # only the 3 keyed POSTs ran

    def test_cross_origin_is_refused_even_with_the_right_key(self):
        body, mh = multipart(self.wav)
        for extra in (EVIL, {"Origin": "null"}, {"Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "same-site"},
                      {"Origin": "http://127.0.0.1:1"}, {"Origin": f"http://127.0.0.1:{self.port}.evil.example"}):
            for m, p, b, h in (("GET", "/v1/models", None, {}), ("GET", "/v1/voices", None, {}),
                               ("GET", "/health", None, {}), ("GET", "/", None, {}),
                               ("POST", "/v1/audio/speech", b'{"input":"x"}', {"Content-Type": "application/json"}),
                               ("POST", "/v1/audio/transcriptions", body, mh),
                               ("POST", "/v1/audio/translations", body, mh)):
                st, _, _ = call(self.port, m, p, b, {**h, **extra})
                self.assertEqual(st, 403, f"{m} {p} {extra}")
        self.assertEqual(self.be.calls, [])

    def test_own_origin_and_allowlisted_origin_work(self):
        self.assertEqual(speech(self.port, {"Origin": f"http://127.0.0.1:{self.port}", "Sec-Fetch-Site": "same-origin"})[0], 200)
        self.assertEqual(speech(self.port, {"Origin": f"http://localhost:{self.port}"})[0], 200)
        srv, be, port = start(allowed_origins=["http://localhost:3000"])
        try:
            self.assertEqual(speech(port, {"Origin": "http://localhost:3001"})[0], 403)
            self.assertEqual(speech(port, {"Origin": "http://localhost:3000", "Sec-Fetch-Site": "same-site"})[0], 200)
            self.assertEqual(speech(port, {"Origin": "http://localhost:3000"})[0], 200)
        finally:
            srv.stop()

    def test_speech_refuses_cors_simple_content_types(self):
        for ct in ("text/plain;charset=UTF-8", "application/x-www-form-urlencoded", "multipart/form-data; boundary=x", ""):
            st, _, _ = call(self.port, "POST", "/v1/audio/speech", b'{"input":"x"}', {"Content-Type": ct} if ct else {})
            self.assertEqual(st, 415, ct)
        self.assertEqual(self.be.calls, [])
        self.assertEqual(speech(self.port, {"Content-Type": "application/json; charset=utf-8"})[0], 200)

    def test_preflight_and_other_methods_are_refused(self):
        st, h, _ = call(self.port, "OPTIONS", "/v1/audio/speech", None,
                        {"Origin": "https://evil.example", "Access-Control-Request-Method": "POST",
                         "Access-Control-Request-Headers": "authorization,content-type"}, key=None)
        self.assertEqual(st, 405)
        self.assertNotIn("Access-Control-Allow-Origin", h)
        for m in ("PUT", "DELETE", "PATCH"):
            self.assertEqual(call(self.port, m, "/v1/audio/speech", b"{}")[0], 405)

    def test_no_cors_headers_and_hardening_headers(self):
        st, h, _ = call(self.port, "GET", "/v1/models")
        self.assertNotIn("Access-Control-Allow-Origin", h)
        self.assertEqual(h.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(h.get("Cross-Origin-Resource-Policy"), "same-origin")

    def test_foreign_host_header_is_refused(self):
        self.assertEqual(call(self.port, "GET", "/v1/models", headers={"Host": "evil.example"})[0], 403)

    def test_rejected_request_does_not_leave_its_body_as_a_second_request(self):
        smuggled = b"GET /v1/voices HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: Bearer " + KEY.encode() + b"\r\n\r\n"
        out = raw(self.port, b"POST /v1/audio/speech HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\n"
                             b"Content-Length: %d\r\n\r\n" % len(smuggled) + smuggled)
        self.assertEqual(out.count(b"HTTP/1.1 "), 1)
        self.assertIn(b"401", out.split(b"\r\n")[0])
        self.assertNotIn(b"<<still open>>", out)

    def test_bad_json_shapes(self):
        for b in (b"[]", b'"x"', b"5", b"{", b'{"input":"x","speed":NaN}', b'{"input":"x","voice":["a"]}',
                  b'{"input":"x","response_format":{"a":1}}'):
            self.assertEqual(speech(self.port, body=b)[0], 400, b)

    def test_500_does_not_echo_exception_text(self):
        class Boom(Backend):
            def tts(self, *a): raise RuntimeError("/home/secret/path/model.pt missing")
        srv = A.ApiServer(Boom(), 0, KEY, log=lambda *a: None); srv.start()
        try:
            st, _, d = speech(srv._httpd.server_address[1])
            self.assertEqual(st, 500); self.assertNotIn(b"secret", d)
        finally:
            srv.stop()


def io_wav(seconds, sr=16000, ch=1):
    import io
    b = io.BytesIO()
    t = np.arange(int(sr * seconds)) / sr
    y = (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    sf.write(b, np.stack([y] * ch, axis=1), sr, format="WAV", subtype="PCM_16")
    return b.getvalue()


# ───────────────────── request exhaustion: bodies, time, queue ─────────────────────
class RequestLimits(unittest.TestCase):
    def test_content_length_validation_happens_before_reading(self):
        srv, be, port = start()
        try:
            base = b"POST /v1/audio/speech HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nAuthorization: Bearer " + KEY.encode() + b"\r\n"
            for hdr, want in ((b"Content-Length: -1\r\n", b"400"), (b"Content-Length: abc\r\n", b"400"),
                              (b"Content-Length: 1e3\r\n", b"400"), (b"Content-Length: +5\r\n", b"400"),
                              (b"", b"411"), (b"Transfer-Encoding: chunked\r\n", b"411"),
                              (b"Content-Length: %d\r\n" % (A.MAX_JSON_BODY + 1), b"413"),
                              (b"Content-Length: 99999999999999999999\r\n", b"400")):
                t = time.time()
                out = raw(port, base + hdr + b"\r\n" + b'{"input":"' + b"A" * 50 + b'"}', shut=False)
                self.assertIn(want, out.split(b"\r\n")[0], hdr)
                self.assertNotIn(b"<<still open>>", out, hdr)
                self.assertLess(time.time() - t, 2.5, hdr)
            mp = b"POST /v1/audio/transcriptions HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: multipart/form-data; boundary=x\r\nAuthorization: Bearer " + KEY.encode() + b"\r\n"
            out = raw(port, mp + b"Content-Length: %d\r\n\r\n" % (A.MAX_BODY + 1))
            self.assertIn(b"413", out.split(b"\r\n")[0])
            self.assertEqual(be.calls, [])
        finally:
            srv.stop()

    def test_slow_and_stalled_clients_are_dropped(self):
        old = A.SOCKET_TIMEOUT, A.BODY_READ_TIMEOUT
        A.SOCKET_TIMEOUT, A.BODY_READ_TIMEOUT = 1.0, 2.0
        srv, be, port = start()
        try:
            hdr = (b"POST /v1/audio/speech HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\n"
                   b"Authorization: Bearer " + KEY.encode() + b"\r\nContent-Length: 1000\r\n\r\n")
            t = time.time(); out = raw(port, hdr + b'{"input":"', wait=6)           # stalls mid-body
            self.assertIn(b"408", out.split(b"\r\n")[0]); self.assertLess(time.time() - t, 3.0)
            t = time.time(); out = raw(port, b"POST /v1/audio/speech HTTP/1.1\r\nHost: 127.", wait=6)   # stalls mid-headers
            self.assertNotIn(b"<<still open>>", out); self.assertLess(time.time() - t, 3.0)
            # trickle: one byte every 0.4 s never trips the idle timeout, the total deadline must
            s = socket.create_connection(("127.0.0.1", port)); s.sendall(hdr); t = time.time(); closed = False
            s.settimeout(0.01)
            while time.time() - t < 8:
                try:
                    s.sendall(b"a")
                except OSError:
                    closed = True; break
                try:
                    if s.recv(4096)[:12].endswith(b"408"): closed = True; break
                except socket.timeout:
                    pass
                except OSError:
                    closed = True; break
                time.sleep(0.4)
            s.close()
            self.assertTrue(closed); self.assertLess(time.time() - t, 4.5)
            self.assertEqual(speech(port)[0], 200)                                  # still healthy
        finally:
            srv.stop(); A.SOCKET_TIMEOUT, A.BODY_READ_TIMEOUT = old

    def test_job_queue_is_bounded_and_overload_gets_429(self):
        old = A.MAX_QUEUED_JOBS; A.MAX_QUEUED_JOBS = 2
        srv, be, port = start(); be.gate = threading.Event()
        res = []
        try:
            def one(): res.append(speech(port, timeout=40))
            ts = [threading.Thread(target=one) for _ in range(8)]
            ts[0].start(); self.assertTrue(be.entered.acquire(timeout=5))          # 1 running
            for t in ts[1:]: t.start()
            time.sleep(1.0)
            early = [r for r in res]                                               # refused immediately
            self.assertEqual(sorted(r[0] for r in early), [429] * 5)
            self.assertTrue(all(r[1].get("Retry-After") for r in early))
            be.gate.set(); [t.join() for t in ts]
            self.assertEqual(sorted(r[0] for r in res), [200] * 3 + [429] * 5)     # 1 running + 2 queued
            self.assertEqual(len(be.calls), 3)
            self.assertEqual(speech(port)[0], 200)                                 # slots were released
        finally:
            be.gate.set(); srv.stop(); A.MAX_QUEUED_JOBS = old

    def test_connection_cap_gets_503(self):
        old = A.MAX_CONNECTIONS; A.MAX_CONNECTIONS = 6
        srv, be, port = start()
        socks = []
        try:
            for _ in range(6):
                s = socket.create_connection(("127.0.0.1", port)); s.sendall(b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\n"); socks.append(s)
            time.sleep(0.3)
            out = raw(port, b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
            self.assertIn(b"503", out.split(b"\r\n")[0]); self.assertIn(b"Retry-After", out)
            for s in socks: s.close()
            time.sleep(0.5)
            self.assertEqual(call(port, "GET", "/health")[0], 200)
        finally:
            for s in socks: s.close()
            srv.stop(); A.MAX_CONNECTIONS = old

    def test_inflight_body_budget(self):
        old = A.MAX_INFLIGHT_BODY_BYTES; A.MAX_INFLIGHT_BODY_BYTES = 3 * 1024 * 1024
        srv, be, port = start()
        try:
            hdr = lambda n: (b"POST /v1/audio/transcriptions HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: multipart/form-data; boundary=x\r\n"
                             b"Authorization: Bearer " + KEY.encode() + b"\r\nContent-Length: %d\r\n\r\n" % n)
            s = socket.create_connection(("127.0.0.1", port)); s.sendall(hdr(2 * 1024 * 1024) + b"x" * 1000)   # holds 2 MB of budget
            time.sleep(0.3)
            out = raw(port, hdr(2 * 1024 * 1024))
            self.assertIn(b"429", out.split(b"\r\n")[0])
            s.close(); time.sleep(0.5)
            self.assertEqual(upload(port, io_wav(1.0))[0], 200)
        finally:
            srv.stop(); A.MAX_INFLIGHT_BODY_BYTES = old


# ───────────────────── N1: uploads cannot steer ffmpeg to other files ─────────────────────
@unittest.skipUnless(FF, "ffmpeg or tests/media not available")
class IndirectInputs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv, cls.be, cls.port = start()
        cls.victims = {e: ffgen(f"victim.{e}", "-f", "lavfi", "-i", "sine=frequency=300:duration=5", "-ac", "1")
                       for e in ("mp3", "m4a", "flac", "ogg", "mkv", "ts", "aac", "mp4", "wav")}

    @classmethod
    def tearDownClass(cls): cls.srv.stop()

    def setUp(self): self.be.calls.clear()

    def hls(self, target):
        return f"#EXTM3U\n#EXT-X-TARGETDURATION:10\n#EXTINF:5,\n{target}\n#EXT-X-ENDLIST\n".encode()

    def test_playlists_are_rejected_under_every_file_name(self):
        for ext, v in self.victims.items():
            for target in (v, "file://" + v):
                for fname in ("a.m3u8", "a.m3u", "a.mp3", "a.wav", "a.bin", "a", "a.m3u8.wav", f"a.{ext}"):
                    st, _, d = upload(self.port, self.hls(target), fname)
                    self.assertEqual(st, 415, (ext, fname, d))
        self.assertEqual(self.be.calls, [])

    def test_other_script_like_formats_are_rejected(self):
        v = self.victims["mp3"]
        tmp_victim = os.path.join(tempfile.gettempdir(), "avsplanted.mp3"); shutil.copy(v, tmp_victim)
        try:
            payloads = {
                "ffconcat-abs": f"ffconcat version 1.0\nfile '{v}'\n".encode(),
                "ffconcat-rel": b"ffconcat version 1.0\nfile 'avsplanted.mp3'\n",
                "concat-noheader": f"file '{v}'\n".encode(),
                "sdp": b"v=0\no=- 0 0 IN IP4 127.0.0.1\ns=x\nc=IN IP4 127.0.0.1\nt=0 0\nm=audio 5004 RTP/AVP 0\n",
                "dash": b'<?xml version="1.0"?><MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static"><Period><AdaptationSet><Representation id="1"><BaseURL>'
                        + v.encode() + b"</BaseURL></Representation></AdaptationSet></Period></MPD>",
                "ffmetadata": b";FFMETADATA1\ntitle=x\n",
                "lavfi-ish": b"sine=frequency=440:duration=99999",
                "bare-path": v.encode(),
                "empty": b"",
            }
            for name, p in payloads.items():
                for fname in ("a.ffconcat", "a.m3u8", "a.sdp", "a.mpd", "a.txt", "a.mp3"):
                    st, _, d = upload(self.port, p, fname)
                    self.assertIn(st, (415, 400), (name, fname, d))
                    self.assertNotEqual(st, 200)
            self.assertEqual(self.be.calls, [])
        finally:
            os.remove(tmp_victim)

    def test_polyglots_with_a_valid_magic_still_cannot_reach_other_files(self):
        v = self.victims["mp3"]
        for magic in (b"ID3\x03\x00\x00\x00\x00\x00\x0a" + b"\x00" * 10, b"\xff\xfb\x90\x00", b"\xff\xf1\x50\x80",
                      b"OggS\x00\x02" + b"\x00" * 20, b"fLaC\x00\x00\x00\x22", b"RIFF\x24\x00\x00\x00WAVE",
                      b"\x1a\x45\xdf\xa3\x80", b"\x00\x00\x00\x18ftypisom", b"FORM\x00\x00\x00\x10AIFF"):
            st, _, d = upload(self.port, magic + b"\n" + self.hls(v), "a.m3u8")
            self.assertNotEqual(st, 200, magic)
            for c in self.be.calls:                       # if anything decoded, it must not be the 5 s victim
                self.assertLess(c[1] / 16000.0, 1.0, magic)

    def test_ffmpeg_command_itself_refuses_playlists_for_every_allowed_demuxer(self):
        """Second layer: even if sniffing were bypassed, the pinned demuxer and the
        whitelists stop ffmpeg from following a reference."""
        d = tempfile.mkdtemp()
        try:
            src = os.path.join(d, "upload.bin"); out = os.path.join(d, "o.wav")
            for ext, v in self.victims.items():
                open(src, "wb").write(self.hls(v))
                for fmt in ("wav", "flac", "ogg", "mp3", "aac", "aiff", "mov", "matroska"):
                    if os.path.exists(out): os.remove(out)
                    r = subprocess.run(A.ffmpeg_decode_cmd(FF, fmt, src, out), cwd=d, capture_output=True, timeout=30)
                    ok = r.returncode == 0 and os.path.exists(out) and sf.info(out).frames > 16000
                    self.assertFalse(ok, (ext, fmt))
            # whitelist alone (no -f): ffmpeg probes "hls" from the .m3u8 name and must be refused
            m3 = os.path.join(d, "a.m3u8"); open(m3, "wb").write(self.hls(self.victims["mp3"]))
            for wl, expect_blocked in (([], False), (["-format_whitelist", A.FFMPEG_FORMAT_WHITELIST], True),
                                       (["-protocol_whitelist", "file", "-format_whitelist", A.FFMPEG_FORMAT_WHITELIST], True)):
                if os.path.exists(out): os.remove(out)
                r = subprocess.run([FF, "-nostdin", "-v", "error", *wl, "-i", m3, "-ac", "1", "-ar", "16000", "-y", out],
                                   cwd=d, capture_output=True, timeout=30)
                decoded = r.returncode == 0 and os.path.exists(out) and sf.info(out).frames > 16000
                self.assertEqual(decoded, not expect_blocked, wl)     # first row proves the attack is live without the fix
        finally:
            shutil.rmtree(d)

    def test_client_file_name_never_reaches_the_filesystem(self):
        before = set(os.listdir(tempfile.gettempdir()))
        for fname in ("x.wav/../../y.sh", "..\\..\\evil.bat", "a.b c;$(id)", "a." + "A" * 300, "a.m3u8"):
            self.assertEqual(upload(self.port, io_wav(1.0), fname)[0], 200, fname)
        self.assertEqual(set(os.listdir(tempfile.gettempdir())) - before, set())


# ───────────────────── legitimate formats still decode (both decoders) ─────────────────────
FORMATS = [  # name, ffmpeg args after the 3 s source
    ("pcm16_16k_mono.wav", ["-ar", "16000", "-ac", "1"]), ("pcm16_8k_mono.wav", ["-ar", "8000", "-ac", "1"]),
    ("pcm16_44k_stereo.wav", ["-ar", "44100", "-ac", "2"]), ("pcm24_48k_stereo.wav", ["-ar", "48000", "-ac", "2", "-c:a", "pcm_s24le"]),
    ("float_48k.wav", ["-ar", "48000", "-c:a", "pcm_f32le"]), ("surround51_48k.wav", ["-ar", "48000", "-ac", "6"]),
    ("hi_96k.flac", ["-ar", "96000", "-ac", "2"]), ("a.flac", ["-ar", "44100"]),
    ("vorbis.ogg", ["-c:a", "libvorbis", "-ar", "44100"]), ("opus.ogg", ["-c:a", "libopus", "-ar", "48000"]),
    ("opus.opus", ["-c:a", "libopus"]), ("cbr.mp3", ["-ar", "44100", "-b:a", "128k"]),
    ("id3.mp3", ["-ar", "22050", "-id3v2_version", "3", "-metadata", "title=t"]), ("noid3.mp3", ["-ar", "44100", "-id3v2_version", "0", "-write_xing", "0"]),
    ("a.m4a", ["-c:a", "aac"]), ("faststart.m4a", ["-c:a", "aac", "-movflags", "+faststart"]),
    ("adts.aac", ["-c:a", "aac", "-f", "adts"]), ("a.aiff", ["-ar", "44100"]),
    ("opus.webm", ["-c:a", "libopus"]), ("a.mka", ["-c:a", "flac"]), ("a.3gp", ["-c:a", "aac", "-ar", "16000", "-ac", "1"]),
]
VIDEO = [("video.mp4", ["-c:v", "mpeg4", "-c:a", "aac"]), ("video.mkv", ["-c:v", "mpeg4", "-c:a", "libvorbis"]),
         ("video.webm", ["-c:v", "libvpx", "-c:a", "libopus"]), ("video.mov", ["-c:v", "mpeg4", "-c:a", "aac"])]


@unittest.skipUnless(FF, "ffmpeg or tests/media not available")
class LegitimateUploads(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv, cls.be, cls.port = start()
        cls.files = []
        for name, args in FORMATS:
            try: cls.files.append(ffgen(name, "-f", "lavfi", "-i", "sine=frequency=440:duration=3", *args))
            except subprocess.CalledProcessError: print("   (encoder missing, skipped fixture)", name)
        for name, args in VIDEO:
            try: cls.files.append(ffgen(name, "-f", "lavfi", "-i", "testsrc=size=64x64:rate=5:duration=3", "-f", "lavfi", "-i", "sine=frequency=440:duration=3", *args))
            except subprocess.CalledProcessError: print("   (encoder missing, skipped fixture)", name)

    @classmethod
    def tearDownClass(cls): cls.srv.stop()

    def check(self, label):
        bad = []
        for p in self.files:
            st, _, d = upload(self.port, rd(p), "upload")               # file name carries no hint
            if st != 200:
                bad.append((os.path.basename(p), st, d[:80])); continue
            info = json.loads(json.loads(d)["text"])
            self.assertEqual((info["sr"], info["ch"], info["sub"]), (16000, 1, "PCM_16"), p)
            self.assertAlmostEqual(info["dur"], 3.0, delta=0.2, msg=p)
        return bad

    def test_all_formats_default_path(self):
        self.assertEqual(self.check("default"), [])

    def test_all_formats_through_ffmpeg_only(self):
        orig = A._decode_sndfile; A._decode_sndfile = lambda s, o: False
        try: self.assertEqual(self.check("ffmpeg"), [])
        finally: A._decode_sndfile = orig

    def test_without_ffmpeg_libsndfile_formats_still_work(self):
        orig = A.shutil.which; A.shutil.which = lambda *_a, **_k: None
        try:
            bad = {b[0] for b in self.check("no-ffmpeg")}
        finally:
            A.shutil.which = orig
        need_ffmpeg = {"a.m4a", "faststart.m4a", "adts.aac", "opus.webm", "a.mka", "a.3gp",
                       "video.mp4", "video.mkv", "video.webm", "video.mov"}
        self.assertTrue(bad <= need_ffmpeg, bad - need_ffmpeg)

    def test_speech_response_formats(self):
        for fmt, magic in (("wav", b"RIFF"), ("flac", b"fLaC"), ("ogg", b"OggS"), ("mp3", None), (None, b"RIFF")):
            b = json.dumps({"input": "hello", **({"response_format": fmt} if fmt else {})}).encode()
            st, h, d = speech(self.port, body=b)
            self.assertEqual(st, 200)
            if magic: self.assertEqual(d[:4], magic, fmt)


# ───────────────────── N2: decoded-audio limits ─────────────────────
@unittest.skipUnless(FF, "ffmpeg or tests/media not available")
class DecodeLimits(unittest.TestCase):
    def setUp(self):
        self.saved = {k: getattr(A, k) for k in ("MAX_AUDIO_SECONDS", "MAX_DECODE_SAMPLES", "DECODE_TIMEOUT", "FFMPEG_TIMEOUT", "MAX_CHANNELS")}
        self.srv, self.be, self.port = start()

    def tearDown(self):
        self.srv.stop()
        for k, v in self.saved.items(): setattr(A, k, v)

    def test_duration_limit_both_decoders(self):
        A.MAX_AUDIO_SECONDS = 10.0
        ok_wav, long_wav = io_wav(9.0), io_wav(12.0)
        self.assertEqual(upload(self.port, ok_wav)[0], 200)
        self.assertEqual(upload(self.port, long_wav)[0], 413)
        long_m4a = rd(ffgen("long12.m4a", "-f", "lavfi", "-i", "sine=frequency=440:duration=12", "-c:a", "aac"))
        ok_m4a = rd(ffgen("ok9.m4a", "-f", "lavfi", "-i", "sine=frequency=440:duration=9", "-c:a", "aac"))
        self.assertEqual(upload(self.port, ok_m4a)[0], 200)
        self.assertEqual(upload(self.port, long_m4a)[0], 413)
        self.assertEqual(len(self.be.calls), 2)

    def test_channel_and_rate_limits(self):
        for name, args in (("ch16.wav", ["-ac", "16", "-ar", "8000"]), ("ch9.flac", None), ("r384k.wav", ["-ar", "384000"]),
                           ("r2k.wav", ["-ar", "2000"])):
            if args is None:
                import io
                b = io.BytesIO(); sf.write(b, np.zeros((8000, 9), dtype=np.float32), 8000, format="WAV", subtype="PCM_16"); data = b.getvalue()
            else:
                data = rd(ffgen(name, "-f", "lavfi", "-i", "sine=frequency=440:duration=2", *args))
            st, _, d = upload(self.port, data)
            self.assertEqual(st, 413, (name, d))
        self.assertEqual(self.be.calls, [])

    def test_bomb_is_rejected_from_the_header_before_decoding(self):
        bomb = rd(ffgen("bomb300.flac", "-f", "lavfi", "-i", "anullsrc=r=192000:cl=7.1", "-t", "300", "-c:a", "flac", "-compression_level", "8"))
        self.assertLess(len(bomb), 200_000)
        t = time.time(); st, _, d = upload(self.port, bomb)
        self.assertEqual(st, 413, d); self.assertLess(time.time() - t, 1.0)
        self.assertEqual(self.be.calls, [])

    def test_limits_hold_when_the_header_hides_the_length(self):
        """FLAC STREAMINFO total_samples = 0 means 'unknown'; a WAV data size can lie.
        The running counters must stop the decode, not the header."""
        A.MAX_AUDIO_SECONDS = 10.0
        flac = bytearray(rd(ffgen("len30.flac", "-f", "lavfi", "-i", "sine=frequency=440:duration=30", "-ar", "16000", "-c:a", "flac")))
        self.assertEqual(flac[:4], b"fLaC")
        flac[21] &= 0xF0; flac[22:26] = b"\x00\x00\x00\x00"            # total samples -> unknown
        st, _, d = upload(self.port, bytes(flac))
        self.assertEqual(st, 413, d)
        wav = bytearray(io_wav(30.0)); i = wav.find(b"data"); wav[i + 4:i + 8] = b"\x10\x00\x00\x00"; wav[4:8] = b"\x24\x00\x00\x00"
        st, _, d = upload(self.port, bytes(wav))                         # header claims 16 bytes of audio
        self.assertIn(st, (400, 413), d)
        for c in self.be.calls: self.assertLessEqual(c[1] / 16000.0, 10.0)

    def test_work_budget_and_decode_deadline(self):
        A.MAX_DECODE_SAMPLES = 16000 * 5
        self.assertEqual(upload(self.port, io_wav(4.0))[0], 200)
        self.assertEqual(upload(self.port, io_wav(4.0, ch=2))[0], 413)       # 8 s of samples
        A.MAX_DECODE_SAMPLES = self.saved["MAX_DECODE_SAMPLES"]
        A.DECODE_TIMEOUT = -1.0
        self.assertEqual(upload(self.port, io_wav(4.0))[0], 413)
        A.DECODE_TIMEOUT = self.saved["DECODE_TIMEOUT"]
        A.FFMPEG_TIMEOUT = 0.001
        self.assertEqual(upload(self.port, rd(ffgen("ok9.m4a", "-f", "lavfi", "-i", "sine=frequency=440:duration=9", "-c:a", "aac")))[0], 413)

    def test_truncated_and_corrupt_files_fail_cleanly(self):
        good = rd(ffgen("a.flac", "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-ar", "44100"))
        for data in (good[:len(good) // 2], good[:60], b"fLaC" + os.urandom(3000), b"RIFF\x00\x00\x00\x00WAVE" + os.urandom(500),
                     b"\x00\x00\x00\x18ftypisom" + os.urandom(2000), b"OggS" + os.urandom(2000), b"\xff\xfb" + os.urandom(5)):
            st, _, d = upload(self.port, data)
            self.assertIn(st, (200, 400, 413), d[:80])
            self.assertNotIn(b"Traceback", d)
        self.assertEqual(upload(self.port, io_wav(1.0))[0], 200)

    def test_no_temp_files_left_behind(self):
        before = set(os.listdir(tempfile.gettempdir()))
        upload(self.port, io_wav(2.0)); upload(self.port, b"#EXTM3U\n"); upload(self.port, b"fLaC" + os.urandom(100))
        upload(self.port, rd(ffgen("ok9.m4a", "-f", "lavfi", "-i", "sine=frequency=440:duration=9", "-c:a", "aac")))
        self.assertEqual(set(os.listdir(tempfile.gettempdir())) - before, set())


if __name__ == "__main__":
    unittest.main(verbosity=2)
