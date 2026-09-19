"""
Captions / subtitles generation (.srt / .vtt) from an audio or video file.

Pipeline:
  1. extract_audio()      - ffmpeg pulls a clean mono 16kHz wav out of
                             whatever the user gave us (mp4, mkv, mp3, ...).
  2. transcribe_words()   - Whisper transcribes the WHOLE file in one call
                             with word_timestamps=True. We deliberately do
                             NOT pre-slice the file into fixed-size chunks
                             ourselves before transcribing - Whisper's own
                             internal silence/VAD handling already finds
                             natural segment boundaries, and slicing blind
                             risks cutting audio mid-word/mid-sentence right
                             at the slice boundary, which fixed-size
                             chunking cannot avoid.
  3. chunk_into_captions() - groups the flat word stream into caption-sized
                             cards (char/duration limits), only ever
                             breaking BETWEEN words (never mid-word, since
                             we have per-word boundaries to snap to), and
                             preferring to break at a natural pause
                             (a gap between one word's end and the next
                             word's start) once a caption has enough
                             content, rather than always hard-cutting at
                             the char/duration ceiling.
  4. write_srt()/write_vtt() - format + write the caption list to disk.
"""

import os
import shutil
import subprocess
import textwrap


def ffmpeg_path():
    """Returns the path to the ffmpeg executable on PATH, or None."""
    return shutil.which("ffmpeg")


def extract_audio(input_path, out_wav_path):
    """Extract mono 16kHz PCM wav from any audio/video file ffmpeg can
    read. Raises RuntimeError with ffmpeg's own stderr tail on failure
    (corrupt file, unsupported codec, etc.) instead of a bare non-zero
    exit code, so the caller can show something actually useful."""
    exe = ffmpeg_path()
    if not exe:
        raise RuntimeError(
            "ffmpeg was not found on your system PATH.\n\n"
            "Captions need ffmpeg to extract audio from audio/video files. "
            "Install it (e.g. 'sudo apt install ffmpeg' on Linux, "
            "'brew install ffmpeg' on macOS, or a build from "
            "ffmpeg.org on Windows) and make sure it's on PATH, "
            "then try again."
        )
    cmd = [exe, "-y", "-i", input_path, "-ac", "1", "-ar", "16000",
           "-vn", out_wav_path]
    result = subprocess.run(cmd, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
    if result.returncode != 0 or not os.path.isfile(out_wav_path):
        tail = (result.stderr or "")[-2000:]
        raise RuntimeError(f"ffmpeg failed to extract audio:\n{tail}")


def transcribe_words(model, wav_path, language=None):
    """Runs Whisper on the whole file at once and returns a flat list of
    {"word", "start", "end"} dicts spanning the entire file. `model` is
    an already-loaded whisper model (see main.py's get_whisper_model())."""
    result = model.transcribe(wav_path, language=language, fp16=False,
                               word_timestamps=True)
    words = []
    for seg in result.get("segments", []):
        for w in seg.get("words", []) or []:
            if w.get("start") is None or w.get("end") is None:
                continue
            words.append({
                "word": w["word"],
                "start": float(w["start"]),
                "end": float(w["end"]),
            })
    return words


def _wrap_text(text, max_chars_per_line, max_lines):
    lines = textwrap.wrap(text, width=max_chars_per_line,
                           break_long_words=False, break_on_hyphens=False)
    if not lines:
        return text
    return "\n".join(lines[:max_lines])


def chunk_into_captions(words, max_chars_per_line=42, max_lines=2,
                         max_duration=7.0, min_chars_before_pause_break=15,
                         silence_gap=0.4):
    """Groups a flat word-timestamp stream into caption cards.

    max_chars_per_line / max_lines - readability cap (default matches the
        common ~42-char, 2-line subtitle convention).
    max_duration - hard cap on how long a single caption stays on screen,
        regardless of pauses (very long silence-free speech gets split
        even with no natural pause to break at).
    silence_gap - a gap (seconds) between one word's end and the next
        word's start at or above this is treated as a natural pause -
        i.e. where a voice trails off/drops - and preferred as a break
        point once the caption already has some content, rather than
        always waiting for the hard char/duration ceiling.
    min_chars_before_pause_break - avoids breaking into trivially tiny
        captions on every micro-pause; a pause only triggers a break once
        the current caption has at least this many characters.

    Returns a list of {"start", "end", "text"} dicts.
    """
    max_chars = max_chars_per_line * max_lines
    captions = []
    current = []

    def current_text():
        return "".join(w["word"] for w in current)

    def flush():
        if not current:
            return
        text = current_text().strip()
        if text:
            captions.append({
                "start": current[0]["start"],
                "end": current[-1]["end"],
                "text": _wrap_text(text, max_chars_per_line, max_lines),
            })
        current.clear()

    for w in words:
        if current:
            gap = w["start"] - current[-1]["end"]
            prospective = (current_text() + w["word"]).strip()
            duration_if_added = w["end"] - current[0]["start"]
            over_length   = len(prospective) > max_chars
            over_duration = duration_if_added > max_duration
            natural_pause = (gap >= silence_gap and
                              len(current_text().strip()) >= min_chars_before_pause_break)
            if over_length or over_duration or natural_pause:
                flush()
        current.append(w)
    flush()
    return captions


def _format_time(seconds, comma):
    if seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    h, total_ms = divmod(total_ms, 3600000)
    m, total_ms = divmod(total_ms, 60000)
    s, ms = divmod(total_ms, 1000)
    sep = "," if comma else "."
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def format_srt_time(seconds):
    return _format_time(seconds, comma=True)


def format_vtt_time(seconds):
    return _format_time(seconds, comma=False)


def write_srt(captions, path):
    with open(path, "w", encoding="utf-8") as f:
        for i, c in enumerate(captions, start=1):
            f.write(f"{i}\n")
            f.write(f"{format_srt_time(c['start'])} --> {format_srt_time(c['end'])}\n")
            f.write(c["text"] + "\n\n")


def write_vtt(captions, path):
    with open(path, "w", encoding="utf-8") as f:
        f.write("WEBVTT\n\n")
        for c in captions:
            f.write(f"{format_vtt_time(c['start'])} --> {format_vtt_time(c['end'])}\n")
            f.write(c["text"] + "\n\n")
