"""AI Voice Studio Local API: a small client you can copy into your own project.

Standard library only. It shows the structure that works well:

    1. one client object that knows the URL and key (read from the environment),
    2. discover first (models / voices) instead of hard-coding names,
    3. one method per endpoint, errors turned into one exception type,
    4. a pipeline function on top: narrate scenes -> audio files + word timings.

Run the demo (the app, or `AI_Voice_Studio --headless`, must be running):

    AVS_API_KEY=your-key python examples/python_client.py
"""
import json
import os
import urllib.error
import urllib.request
import uuid


class VoiceStudioError(Exception):
    """Any problem talking to the API (not running, bad key, bad request...)."""


class VoiceStudio:
    def __init__(self, base_url=None, api_key=None, timeout=300):
        self.base = (base_url or os.environ.get("AVS_API_URL", "http://127.0.0.1:8765/v1")).rstrip("/")
        self.key = api_key if api_key is not None else os.environ.get("AVS_API_KEY", "")
        self.timeout = timeout

    # ---- plumbing --------------------------------------------------------
    def _call(self, method, path, body=None, content_type=None):
        headers = {"Authorization": "Bearer " + self.key} if self.key else {}
        if content_type:
            headers["Content-Type"] = content_type
        req = urllib.request.Request(self.base + path, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:           # the API sends {"error": {"message": ...}}
            try:
                msg = json.loads(e.read())["error"]["message"]
            except Exception:
                msg = f"HTTP {e.code}"
            raise VoiceStudioError(msg) from None
        except (urllib.error.URLError, OSError) as e:
            raise VoiceStudioError(f"AI Voice Studio is not reachable at {self.base} ({e})") from None

    # ---- discovery -------------------------------------------------------
    def models(self):
        """{'tts': ['kokoro', ...], 'stt': ['whisper-1', 'vosk']}"""
        out = {"tts": [], "stt": []}
        for m in json.loads(self._call("GET", "/models"))["data"]:
            out[m["capabilities"]].append(m["id"])
        return out

    def voices(self, engine=None):
        """List of dicts: key ('kokoro:af_heart'), engine, voice, label, gender, lang."""
        v = json.loads(self._call("GET", "/voices"))["voices"]
        return [x for x in v if not engine or x["engine"] == engine]

    # ---- text to speech --------------------------------------------------
    def speak(self, text, voice=None, model=None, speed=1.0, pitch=0.0, volume=1.0,
              depth=0.0, language=None):
        """Returns WAV bytes.
        speed 0.25-4 | pitch -12..12 semitones | volume 0-2 | depth -8..8 (+ = deeper)"""
        payload = {"input": text, "response_format": "wav", "speed": speed, "pitch": pitch,
                   "volume": volume, "depth": depth}
        for k, v in (("voice", voice), ("model", model), ("language", language)):
            if v:
                payload[k] = v
        return self._call("POST", "/audio/speech", json.dumps(payload).encode(), "application/json")

    # ---- speech to text --------------------------------------------------
    def transcribe(self, wav_bytes, model="whisper-1", language=None, words=False):
        """words=False -> text. words=True -> {'text', 'words': [{'word','start','end'}]}"""
        fields = [("model", model)]
        if language:
            fields.append(("language", language))
        if words:
            fields += [("response_format", "verbose_json"), ("timestamp_granularities[]", "word")]
        b = uuid.uuid4().hex
        parts = [f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
                 for k, v in fields]
        parts.append((f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="a.wav"\r\n'
                      "Content-Type: audio/wav\r\n\r\n").encode() + wav_bytes + b"\r\n")
        parts.append(f"--{b}--\r\n".encode())
        res = json.loads(self._call("POST", "/audio/transcriptions", b"".join(parts),
                                    f"multipart/form-data; boundary={b}"))
        return res if words else res["text"]


# ---- a pipeline on top: narrate scenes, get audio + word timings ----------
def srt_time(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def narrate(studio, scenes, out_dir, voice=None, **fx):
    """scenes: list of strings. Writes scene-N.wav, scene-N.json (word times) and
    scene-N.srt for each; returns the list of result dicts."""
    os.makedirs(out_dir, exist_ok=True)
    results = []
    for i, text in enumerate(scenes, 1):
        wav = studio.speak(text, voice=voice, **fx)
        timing = studio.transcribe(wav, words=True)          # word-level times for captions / karaoke
        base = os.path.join(out_dir, f"scene-{i}")
        with open(base + ".wav", "wb") as f:
            f.write(wav)
        with open(base + ".json", "w", encoding="utf-8") as f:
            json.dump(timing["words"], f, indent=1)
        with open(base + ".srt", "w", encoding="utf-8") as f:
            for n, w in enumerate(timing["words"], 1):        # one caption per word: simplest sync
                f.write(f"{n}\n{srt_time(w['start'])} --> {srt_time(w['end'])}\n{w['word']}\n\n")
        results.append({"scene": i, "wav": base + ".wav", "words": len(timing["words"])})
    return results


if __name__ == "__main__":
    studio = VoiceStudio()
    try:
        print("models:", studio.models())
        voices = studio.voices(engine="kokoro")
        print(f"{len(voices)} kokoro voices; using", voices[0]["key"] if voices else "default")
        scenes = ["The expedition left at dawn.", "By noon, the mountain was in sight."]
        for r in narrate(studio, scenes, "narration_out", voice=voices[0]["key"] if voices else None,
                         speed=0.95, depth=1.0):
            print("scene", r["scene"], "->", r["wav"], f"({r['words']} words timed)")
    except VoiceStudioError as e:
        raise SystemExit(f"Could not use AI Voice Studio: {e}")
