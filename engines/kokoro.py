"""Kokoro-82M (54 voices, several languages) via kokoro-onnx.

Runs on CPU through ONNX Runtime. Licenses: kokoro-onnx = MIT, Kokoro
model = Apache 2.0. Phonemes come from espeak-ng, which the
`espeakng-loader` package (a kokoro-onnx dependency) supplies.

Two files live in <models_base>/kokoro/ (~120 MB total, int8 build):
  kokoro-v1.0.int8.onnx   the model
  voices-v1.0.bin         voice style vectors (an .npz archive)
"""
import os
import re
import threading
import urllib.request
import wave

import numpy as np

from .base import EngineSpec

BASE_URL = ("https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
            "model-files-v1.0/")
MODEL_FILE = "kokoro-v1.0.int8.onnx"
VOICES_FILE = "voices-v1.0.bin"
# name -> (approx size in bytes, minimum size that counts as "complete")
_FILES = {MODEL_FILE: (92_361_271, 85_000_000),
          VOICES_FILE: (28_214_398, 25_000_000)}
SAMPLE_RATE = 24000

# first letter of a voice id -> espeak language code
_LANG = {"a": "en-us", "b": "en-gb", "e": "es", "f": "fr-fr", "h": "hi",
         "i": "it", "j": "ja", "p": "pt-br", "z": "cmn"}
_LANG_NAME = {"a": "US English", "b": "UK English", "e": "Spanish",
              "f": "French", "h": "Hindi", "i": "Italian", "j": "Japanese",
              "p": "Portuguese", "z": "Chinese"}

_instance = None
_lock = threading.Lock()   # espeak is not thread-safe -> one synth at a time


def lang_for_voice(voice):
    return _LANG.get(voice[:1], "en-us")


def describe_voice(voice):
    """'af_heart' -> 'heart (US English, female)'."""
    lang = _LANG_NAME.get(voice[:1], "?")
    gender = {"f": "female", "m": "male"}.get(voice[1:2], "")
    name = voice.split("_", 1)[-1]
    return f"{name} ({lang}{', ' + gender if gender else ''})"


def split_text(text, limit=240):
    """Sentence-ish chunks so no single call gets near Kokoro's token cap."""
    parts = []
    for para in re.split(r"\n+", text):
        for s in re.split(r"(?<=[.!?\u3002\uff01\uff1f])\s+", para.strip()):
            s = s.strip()
            while len(s) > limit:                    # very long sentence
                cut = max(s.rfind(", ", 0, limit), s.rfind("; ", 0, limit),
                          s.rfind(" ", 0, limit))
                cut = cut if cut > 40 else limit
                parts.append(s[:cut + 1].strip())
                s = s[cut + 1:].strip()
            if s:
                parts.append(s)
    chunks, cur = [], ""
    for p in parts:                                  # merge tiny neighbours
        if cur and len(cur) + len(p) + 1 <= limit:
            cur += " " + p
        else:
            if cur:
                chunks.append(cur)
            cur = p
    if cur:
        chunks.append(cur)
    return chunks


def build(models_base):
    folder = os.path.join(models_base, "kokoro")
    model_path = os.path.join(folder, MODEL_FILE)
    voices_path = os.path.join(folder, VOICES_FILE)

    def is_installed():
        for name, (_approx, minimum) in _FILES.items():
            p = os.path.join(folder, name)
            try:
                if os.path.getsize(p) < minimum:
                    return False
            except OSError:
                return False
        return True

    def download(progress_cb=None):
        os.makedirs(folder, exist_ok=True)
        total = sum(a for a, _m in _FILES.values())
        done_before = 0
        for name, (approx, minimum) in _FILES.items():
            dest = os.path.join(folder, name)
            if os.path.exists(dest) and os.path.getsize(dest) >= minimum:
                done_before += approx
                continue
            tmp = dest + ".part"
            req = urllib.request.Request(BASE_URL + name,
                                         headers={"User-Agent": "AI-Voice-Studio"})
            with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
                expected = int(r.headers.get("Content-Length") or 0)
                got = 0
                while True:
                    block = r.read(256 * 1024)
                    if not block:
                        break
                    f.write(block)
                    got += len(block)
                    if progress_cb:
                        progress_cb(done_before + got, total)
            if got < minimum or (expected and got != expected):
                os.remove(tmp)
                raise RuntimeError(f"{name}: download incomplete "
                                   f"({got} of {expected or approx} bytes)")
            os.replace(tmp, dest)       # only a finished file gets the real name
            done_before += approx

    def _get():
        global _instance
        if _instance is None:
            from kokoro_onnx import Kokoro
            _instance = Kokoro(model_path, voices_path)
        return _instance

    def list_voices():
        """Voice ids straight from the voices archive (no model load)."""
        if not is_installed():
            return []
        with np.load(voices_path) as z:
            return sorted(z.files)

    def synthesize(text, voice, out_path, language=None):
        voice = voice or "af_heart"
        lang = lang_for_voice(voice)
        pieces = []
        gap = np.zeros(int(SAMPLE_RATE * 0.12), dtype=np.float32)
        with _lock:
            k = _get()
            for chunk in split_text(text):
                audio, sr = k.create(chunk, voice=voice, speed=1.0, lang=lang)
                pieces += [np.asarray(audio, dtype=np.float32), gap]
        if not pieces:
            raise ValueError("Nothing to speak.")
        y = np.concatenate(pieces[:-1])
        pcm = (np.clip(y, -1.0, 1.0) * 32767).astype("<i2")
        with wave.open(out_path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(pcm.tobytes())

    return EngineSpec(
        key="kokoro",
        display_name="Kokoro voices",
        approx_size="~120 MB",
        description="Fast, natural TTS (54 voices)",
        license="Apache 2.0 (model) / MIT (kokoro-onnx)",
        requires_tos=False,
        is_installed=is_installed,
        download=download,
        list_voices=list_voices,
        synthesize=synthesize,
    )
