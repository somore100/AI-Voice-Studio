# Audiovane Local API

Text to speech and speech to text from your own programs, using the voices and models already on your computer. OpenAI-compatible, so existing OpenAI client code works by changing the base URL.

* **Base URL:** `http://127.0.0.1:8765/v1` (port is configurable). Listens on this computer only.
* **Auth:** an API key is **required**. The app creates one the first time (Local API section: *Copy key*). Send `Authorization: Bearer YOUR_KEY` on every request. Programs running as you (the MCP server, the self-test) read it from the app's settings automatically. Running without a key needs the explicit *Allow without a key* switch and is not recommended.
* **Web pages cannot use it.** Requests from a browser page on another site (an `Origin` that is not this server, or `Sec-Fetch-Site: cross-site`) are refused with 403, even with the right key.
* **Start it:** press *Start API server* in the app, or run it with no window: `Audiovane --headless` (see [Running without a window](#running-without-a-window)).
* **One request at a time.** The models are shared, so requests are processed in order. Do not fire many in parallel; queue them in your program.

## Endpoints

| Method and path | What it does |
|---|---|
| `GET /v1/models` | Installed engines (`capabilities`: `tts` or `stt`). |
| `GET /v1/voices` | Installed voices: `key`, `engine`, `voice`, `label`, `gender`, `lang`. |
| `POST /v1/audio/speech` | Text in, audio out. |
| `POST /v1/audio/transcriptions` | Audio in, text out (Whisper, Vosk), optional word times. |
| `POST /v1/audio/translations` | Audio in, English text out. |
| `GET /health` | `{"status":"ok"}`. |

## Speech: `POST /v1/audio/speech` (JSON body)

| Field | Meaning | Range, default |
|---|---|---|
| `input` | Text to say (required). | up to the server limit |
| `model` | Engine: `kokoro`, `vctk`, `xtts`. | first installed |
| `voice` | Voice. Best: the `key` from `/v1/voices`, e.g. `kokoro:af_heart`. | engine default |
| `language` | Language code (matters for `xtts`). | `en` |
| `speed` | Speaking speed. | 0.25 to 4, `1` |
| `pitch` | Semitones, length unchanged. | -12 to 12, `0` |
| `volume` | Loudness. | 0 to 2, `1` |
| `depth` | Voice depth (formants), pitch unchanged. Positive is deeper. | -8 to 8, `0` |
| `response_format` | `wav` (always available), `mp3`, `flac`, `ogg`, `opus` (if supported on this machine). | `wav` |

The response body is the audio file.

## Transcription: `POST /v1/audio/transcriptions` (multipart form)

| Field | Meaning |
|---|---|
| `file` | The audio (wav, mp3, flac, ogg, ...; needs ffmpeg for some formats). |
| `model` | `whisper-1` (Whisper) or `vosk`. |
| `language` | Language code, optional (Whisper auto-detects). |
| `response_format` | `json` (default, `{"text": ...}`), `text`, `srt`, `vtt`, `verbose_json`. |
| `timestamp_granularities[]` | `word` with `verbose_json` adds `"words": [{"word","start","end"}]` (seconds). |

## Limits

* Speech requests must be `Content-Type: application/json`; transcription requests `multipart/form-data` with a `Content-Length` (no chunked bodies).
* Uploads are recognised by their **content**, not their file name: WAV, FLAC, OGG/Opus, MP3, AAC, M4A/MP4, WebM/MKV, AIFF. Playlists and other text formats are refused (415).
* Audio: at most 1 hour, 8 channels, 4-192 kHz; request bodies up to 200 MB (speech JSON 1 MB, text 20,000 characters).
* One job runs at a time and up to 4 wait; more get `429` with `Retry-After`. Too many open connections get `503`.

## Errors

Every error is JSON: `{"error": {"message": "...", "type": "invalid_request_error"}}` with the HTTP status: `400` bad input, `401` wrong or missing key, `403` browser/cross-site request or foreign host, `404` unknown endpoint or missing model, `408` slow upload, `411` missing `Content-Length`, `413` too large or too long, `415` wrong content type or unsupported audio, `429` busy, `503` engine not installed or server full. Internal errors say "Internal error (see the app log)"; details are in `app.log`.

## How to structure your integration

1. **One client object** that holds the base URL and key (environment variables `AVS_API_URL`, `AVS_API_KEY`), one method per endpoint, and one exception type. See [`examples/python_client.py`](../examples/python_client.py).
2. **Discover, do not hard-code.** Call `/v1/models` and `/v1/voices` at start-up and pick from what is installed; another user's machine may have different engines.
3. **Check it is running first** (`/v1/models`) and show a clear message if not, instead of a raw connection error.
4. **Work in a pipeline.** Typical shape: `text -> /audio/speech -> wav` then `wav -> /audio/transcriptions (words) -> captions / lip-sync / karaoke timing`. Keep the audio and the timing JSON side by side.
5. **Queue requests; set long timeouts.** The first request loads a model and can take a while; later ones are quick. Use a timeout of a few minutes, not seconds.
6. **Keep effects in one place.** Pass `speed`, `pitch`, `volume` and `depth` as one settings dict per character/voice so every line of that character sounds the same.
7. **Verify on your own machine** with the built-in checker: `python selftest.py` (or `Audiovane --selftest`).

Examples: [`curl.sh`](../examples/curl.sh), [`python_client.py`](../examples/python_client.py) (narrate scenes and get word timings), [`openai_sdk.py`](../examples/openai_sdk.py), [`node_client.mjs`](../examples/node_client.mjs).

## Running without a window

`Audiovane --headless` runs the engine and the API with no window at all (older `--background` still works). Start it by hand, or choose *Run in the background* under *When I log in to this computer* in the app's Local API section. Opening the app later attaches to the running engine; closing the window does not stop it. *Stop background engine* in the app (or `SIGTERM` / closing the process) ends it. Logs go to `app.log` in the settings folder.

## Use it from AI assistants (MCP)

`Audiovane --mcp` (or `mcp_server.py` from source) is an MCP server with the tools `speak`, `list_voices`, `transcribe` and `status`. Press *Copy MCP command* in the app for the exact `claude mcp add` line for your install.
