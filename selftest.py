"""End-to-end self-test for AI Voice Studio's Local API and MCP server.

    python selftest.py              # from source (starts the app in the background if needed)
    AI_Voice_Studio --selftest      # packaged build, any platform
    ... [--no-mcp]                  # skip the MCP handshake step

Prints PASS / FAIL / SKIP per step and exits 1 if anything failed. It needs the
speech and recognition models installed. Nothing is written except temporary
audio, which is deleted afterwards.

Reusable for other apps with an OpenAI-style audio API: change the TEXT and the
checks in `run()`.
"""
import array
import io
import json
import math
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
import wave

import mcp_server as M

TEXT = "Hello there, this is a self test of the voice studio."


# ── tiny HTTP client that keeps the status code ───────────────────────────
def http(method, path, body=None, headers=None, key=None, timeout=300):
    h = dict(headers or {})
    key = M.api_key() if key is None else key
    if key:
        h["Authorization"] = "Bearer " + key
    req = urllib.request.Request(M.api_base() + path, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def speak(**fields):
    body = json.dumps(dict(input=TEXT, response_format="wav", **fields)).encode()
    st, data = http("POST", "/audio/speech", body, {"Content-Type": "application/json"})
    if st != 200 or data[:4] != b"RIFF":
        raise AssertionError(f"HTTP {st}: {data[:150]!r}")
    return data


# ── audio measurements (stdlib; numpy only for the optional spectral checks) ──
def wav_info(data):
    with wave.open(io.BytesIO(data), "rb") as w:
        n, sr, ch, sw = w.getnframes(), w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(n)
    if sw != 2:
        raise AssertionError(f"expected 16-bit audio, got {sw * 8}-bit")
    a = array.array("h"); a.frombytes(raw)
    return dict(dur=n / float(sr), sr=sr, ch=ch, samples=a)


def rms(samples):
    return math.sqrt(sum(x * x for x in samples) / max(1, len(samples)))


def centroid(info):
    """Spectral centroid in Hz (needs numpy), or None."""
    try:
        import numpy as np
    except ImportError:
        return None
    y = np.asarray(info["samples"], dtype=np.float32)[::info["ch"]]
    spec = np.abs(np.fft.rfft(y * np.hanning(len(y))))
    freqs = np.fft.rfftfreq(len(y), 1.0 / info["sr"])
    return float((freqs * spec).sum() / max(spec.sum(), 1e-9))


def words(s):
    return [w for w in "".join(c.lower() if c.isalnum() else " " for c in s).split()]


# ── the checks ────────────────────────────────────────────────────────────
class Report:
    def __init__(self):
        self.rows = []

    def check(self, name, fn):
        t = time.time()
        try:
            res = fn()
            status, note = ("SKIP", res[1]) if isinstance(res, tuple) and res[0] == "skip" \
                else ("PASS", res if isinstance(res, str) else "")
        except AssertionError as e:
            status, note = "FAIL", str(e)
        except Exception as e:
            status, note = "FAIL", f"{type(e).__name__}: {e}"
        self.rows.append((name, status, note))
        print(f"  [{status}] {name}" + (f"  - {note}" if note else "") +
              f"   ({time.time() - t:.1f}s)", flush=True)

    @property
    def failed(self):
        return sum(1 for r in self.rows if r[1] == "FAIL")


def run(with_mcp=True):
    rep, ctx = Report(), {}
    print(f"AI Voice Studio self-test  ->  {M.api_base()}", flush=True)

    def reachable():
        M.ensure_running()
        st, data = http("GET", "/models")
        assert st == 200, f"HTTP {st}"
        models = json.loads(data)["data"]
        ctx["tts"] = [m["id"] for m in models if m["capabilities"] == "tts"]
        ctx["stt"] = [m["id"] for m in models if m["capabilities"] == "stt"]
        assert ctx["tts"], "no speech engine installed"
        return f"speech: {', '.join(ctx['tts'])}; recognition: {', '.join(ctx['stt']) or 'none'}"
    rep.check("API reachable, models listed", reachable)
    if ctx.get("tts") is None:
        print("Cannot continue: the API is not reachable.")
        return 1

    def auth():
        if not M.api_key():
            return ("skip", "no API key set")
        st, _ = http("GET", "/models", key="wrong-key")
        assert st == 401, f"a wrong key got HTTP {st}, expected 401"
        return "wrong key rejected"
    rep.check("API key enforced", auth)

    def voices():
        st, data = http("GET", "/voices")
        v = json.loads(data).get("voices", [])
        assert st == 200 and v, "no voices returned"
        return f"{len(v)} voices"
    rep.check("voices listed", voices)

    def baseline():
        ctx["base"] = wav_info(speak())
        d = ctx["base"]["dur"]
        assert d > 0.5, f"audio only {d:.2f}s long"
        ctx["base_rms"], ctx["base_c"] = rms(ctx["base"]["samples"]), centroid(ctx["base"])
        assert ctx["base_rms"] > 50, "audio is silent"
        return f"{d:.1f}s, {ctx['base']['sr']} Hz"
    rep.check("speech: baseline", baseline)
    if "base" not in ctx:
        return 1
    base = ctx["base"]

    def speed():
        fast, slow = wav_info(speak(speed=2.0))["dur"], wav_info(speak(speed=0.5))["dur"]
        assert fast < base["dur"] * 0.7, f"speed 2.0 gave {fast:.1f}s vs {base['dur']:.1f}s"
        assert slow > base["dur"] * 1.4, f"speed 0.5 gave {slow:.1f}s vs {base['dur']:.1f}s"
        return f"2x: {fast:.1f}s, 1x: {base['dur']:.1f}s, 0.5x: {slow:.1f}s"
    rep.check("effect: speed changes the length", speed)

    def volume():
        r = rms(wav_info(speak(volume=0.5))["samples"]) / ctx["base_rms"]
        assert 0.35 < r < 0.65, f"volume 0.5 gave {r:.2f}x the loudness"
        return f"0.5 -> {r:.2f}x loudness"
    rep.check("effect: volume changes the loudness", volume)

    def pitch():
        up, dn = wav_info(speak(pitch=6)), wav_info(speak(pitch=-6))
        assert abs(up["dur"] / base["dur"] - 1) < 0.2, "pitch changed the length"
        cu, cd = centroid(up), centroid(dn)
        if cu is None:
            assert up["samples"] != base["samples"], "pitch +6 changed nothing"
            return "changed the audio (install numpy for a direction check)"
        assert cu > ctx["base_c"] > cd, f"brightness {cd:.0f} / {ctx['base_c']:.0f} / {cu:.0f} Hz not ordered"
        return f"brightness -6: {cd:.0f} Hz < 0: {ctx['base_c']:.0f} Hz < +6: {cu:.0f} Hz"
    rep.check("effect: pitch moves the voice", pitch)

    def depth():
        deep, thin = wav_info(speak(depth=4)), wav_info(speak(depth=-4))
        cdp, cth = centroid(deep), centroid(thin)
        if cdp is None:
            assert deep["samples"] != base["samples"], "depth +4 changed nothing"
            return "changed the audio (install numpy for a direction check)"
        assert cdp < ctx["base_c"] < cth, f"brightness {cdp:.0f} / {ctx['base_c']:.0f} / {cth:.0f} Hz not ordered"
        return f"deeper: {cdp:.0f} Hz < normal: {ctx['base_c']:.0f} Hz < thinner: {cth:.0f} Hz"
    rep.check("effect: depth makes the voice deeper / thinner", depth)

    def bad_input():
        st, _ = http("POST", "/audio/speech", b'{"input": ""}', {"Content-Type": "application/json"})
        assert st == 400, f"empty text got HTTP {st}, expected 400"
        return "empty text rejected"
    rep.check("bad request is rejected cleanly", bad_input)

    def transcribe(fields=()):
        data = speak()
        b = uuid.uuid4().hex
        parts = [f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
                 for k, v in (("model", "whisper-1"),) + tuple(fields)]
        parts.append((f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="t.wav"\r\n'
                      "Content-Type: audio/wav\r\n\r\n").encode() + data + b"\r\n")
        parts.append(f"--{b}--\r\n".encode())
        st, out = http("POST", "/audio/transcriptions", b"".join(parts),
                       {"Content-Type": f"multipart/form-data; boundary={b}"})
        assert st == 200, f"HTTP {st}: {out[:150]!r}"
        return json.loads(out)

    def roundtrip():
        if not ctx["stt"]:
            return ("skip", "no recognition model installed")
        got = transcribe()["text"]
        want = words(TEXT)
        hit = sum(1 for w in want if w in words(got)) / len(want)
        assert hit >= 0.7, f"only {hit:.0%} of the words came back: {got!r}"
        return f"{hit:.0%} of words matched: {got!r}"
    rep.check("round trip: speech -> text matches", roundtrip)

    def word_times():
        if not ctx["stt"]:
            return ("skip", "no recognition model installed")
        res = transcribe((("response_format", "verbose_json"), ("timestamp_granularities[]", "word")))
        w = res.get("words") or []
        assert w, "no 'words' in the response"
        assert all(x["end"] >= x["start"] for x in w), "a word ends before it starts"
        assert all(w[i]["start"] <= w[i + 1]["start"] + 1e-6 for i in range(len(w) - 1)), "words out of order"
        assert w[-1]["end"] <= base["dur"] + 1.0, "timestamps run past the audio"
        return f"{len(w)} words, {w[0]['start']:.2f}s to {w[-1]['end']:.2f}s"
    rep.check("word timestamps", word_times)

    if with_mcp:
        def mcp():
            cmd = ([os.environ.get("APPIMAGE") or sys.executable, "--mcp"]
                   if getattr(sys, "frozen", False)
                   else [sys.executable, os.path.join(M.HERE, "mcp_server.py")])
            p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, text=True)
            try:
                def rpc(i, method, params=None):
                    p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": i, "method": method,
                                              "params": params or {}}) + "\n")
                    p.stdin.flush()
                    return json.loads(p.stdout.readline())
                init = rpc(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                             "clientInfo": {"name": "selftest", "version": "1"}})
                assert init["result"]["serverInfo"]["name"] == "ai-voice-studio", "bad handshake"
                names = {t["name"] for t in rpc(2, "tools/list")["result"]["tools"]}
                assert {"speak", "list_voices", "transcribe", "status"} <= names, f"tools: {names}"
                r = rpc(3, "tools/call", {"name": "status", "arguments": {}})["result"]
                assert not r["isError"], r["content"][0]["text"]
                return "handshake, tool list and status call OK"
            finally:
                p.kill()
        rep.check("MCP server: handshake and tools", mcp)

    n, bad = len(rep.rows), rep.failed
    skipped = sum(1 for r in rep.rows if r[1] == "SKIP")
    print(f"\n{n - bad - skipped} passed, {bad} failed, {skipped} skipped", flush=True)
    return 1 if bad else 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    return run(with_mcp="--no-mcp" not in argv)


if __name__ == "__main__":
    sys.exit(main())
