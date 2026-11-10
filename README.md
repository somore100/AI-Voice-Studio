# AI-Voice-Studio

**Speak, listen, translate and change your voice - with AI models that run on your own computer.**

AI-Voice-Studio is a desktop app that puts text-to-speech, speech-to-text, subtitles, translation and a live voice changer behind one simple interface. It wraps open-source models, so you do not have to wrestle with each model, its dependencies and its command line separately.

![Platforms](https://img.shields.io/badge/platforms-Windows%20%7C%20Linux%20%7C%20macOS-blue)
![Python](https://img.shields.io/badge/python-3.12-blue)
![License](https://img.shields.io/badge/license-Source--Available%20v1.0-orange)
![Status](https://img.shields.io/badge/status-active%20development-green)
[![Architecture diagram](https://gitdiagram.com/diagram-badge.svg)](https://gitdiagram.com/somore100/ai-voice-studio?utm_source=readme&utm_medium=badge)

<img width="817" height="695" alt="AI Voice Studio" src="https://github.com/user-attachments/assets/bda9a7f6-6b42-42c5-9651-b0b3ad299cc3" />

## ✨ What it does

### 🎙️ Text-to-Speech

Three engines in one app - pick whichever suits the job:

| Engine | Good for | Voices | Download |
|---|---|---|---|
| **Kokoro** | Fast, natural speech, even on a CPU | 54 voices, 8 languages | ~120 MB |
| **VCTK** | English with lots of choice | 100+ English voices, favourites and male/female filter | ~150 MB |
| **XTTS-v2** | Many languages and voice cloning | 17 languages, preset speakers or a cloned voice | ~1.8 GB |

Shape the result after it is generated:

* **Speed, Pitch, Volume** sliders - or just type an exact value (`150` = 150 %)
* **Depth** - makes a voice deeper and bigger, or lighter and smaller, **without changing its pitch**
* **Selected text only** - tick it, select words in the text box, and give just those words their own speed and pitch
* **Curve editor** - draw speed, pitch and volume curves over a zoomable waveform timeline with sentence markers, snap-to-pause, a zoom readout and a "play original" button, so you can slow down one sentence or lift the pitch on one word-sized stretch
* Preview (one at a time), save to WAV
* **Find a voice by traits** - tick Pitch / Brightness / Liveliness, drag the sliders, filter by gender and language, and the app ranks all your installed voices by how close they are (each voice is measured once, then remembered)

### 👂 Speech-to-Text and subtitles

* **Whisper** (accurate) and **Vosk** (light and fast) engines, 17 spoken languages
* Transcribe your microphone, or a whole audio / video file
* **Captions:** turn audio or video into **SRT** or **VTT** subtitles with word-level timing

### 🌍 Translator

* Translate text between a long list of languages (more than 100)
* Uses Google Translate's web endpoint, so this one feature **needs an internet connection**

### 🎭 Voice changer

* **TTS pipeline:** your microphone is transcribed and re-spoken in the voice you choose (Kokoro, VCTK or XTTS), with its own "spoken language" setting or Whisper auto-detect
* **Live Pitch:** instant pitch shifting with very low delay
* Optional **virtual microphone** so call and chat apps can hear it (Linux, via PipeWire / PulseAudio)
* Echo protection while your own speakers are on

### 🧰 Quality of life

* **Models & Setup** panel: download, verify and uninstall models from inside the app
* **Search-as-you-type** drop-downs for every long list (languages, voices, microphones)
* Your choices are **remembered between launches**
* Dark theme

## 🔒 Privacy

Speech generation, speech recognition and the voice changer run **locally**. Nothing you type or say is sent to a server by them. Internet is only used to download models and for the Translator (your text goes to Google Translate).

## 📦 Installation

### Ready-made builds

Builds for **Windows**, **Linux (AppImage)** and **macOS** are produced by GitHub Actions. Open the **Actions** tab, choose **Build All Platforms**, open the latest successful run and download the artifact for your system (or check the **Releases** page if a release has been published).

On first use open **Models & Setup** and download the models you want. They are stored on your computer.

### Run from source

You need **Python 3.12** plus a few system tools.

```bash
git clone https://github.com/somore100/AI-Voice-Studio.git
cd AI-Voice-Studio
python3.12 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

System tools:

| Tool | Needed for |
|---|---|
| `ffmpeg` | Captions and transcribing audio / video files |
| `espeak-ng` | Some voices |
| PortAudio | Microphone input |
| `pactl` / `paplay` (PipeWire or PulseAudio) | The voice changer's virtual microphone on Linux |

Where things live: models are stored in `./models/` when you run from source (packaged Linux builds use `~/.local/share/AI Voice Studio/models`); settings are saved in a small `settings.json` in your user config folder.

## 🔌 Local API

Other programs can use this app's voices and Whisper instead of installing their own models. Turn it on in the **Local API** section (it listens on `127.0.0.1` only and needs an API key, which the app creates for you; websites cannot use it). It speaks the OpenAI format, so any app with a "custom / local OpenAI provider" setting works: base URL `http://127.0.0.1:8765/v1`.

```bash
KEY="paste the key from the app (Local API -> Copy key)"
curl http://127.0.0.1:8765/v1/audio/speech -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model":"kokoro","voice":"af_heart","input":"Hello there"}' -o hello.wav
curl http://127.0.0.1:8765/v1/audio/transcriptions -H "Authorization: Bearer $KEY" -F file=@hello.wav -F model=whisper-1
# word-level times (for karaoke captions / sync): verbose_json + word granularity
curl http://127.0.0.1:8765/v1/audio/transcriptions -H "Authorization: Bearer $KEY" -F file=@hello.wav -F model=whisper-1 \
  -F response_format=verbose_json -F "timestamp_granularities[]=word"
```

Full reference and how to structure an integration: [docs/API.md](docs/API.md); working examples (curl, Python, OpenAI SDK, Node) are in [examples/](examples/).

Endpoints: `/v1/audio/speech`, `/v1/audio/transcriptions`, `/v1/audio/translations`, `/v1/models`, `/v1/voices`. Extra speech fields: `language`, `speed` (0.25-4), `pitch` (-12 to 12 semitones), `volume` (0-2), `depth` (-8 to 8, positive is deeper). Transcriptions return segment times by default and a `words` list (`word`, `start`, `end`) when you ask for word granularity.

**Start automatically / without a window:** in the Local API section, *Start when the app opens* turns the server on at launch, and *When I log in to this computer* can open the app, or **run the engine in the background with no window at all** (`AI_Voice_Studio --headless`). Open the app any time and its window attaches to the running engine; closing the window leaves the engine running, and *Stop background engine* ends it. This starts at login, not before you sign in. Everything the app prints is also written, with timestamps, to `app.log` in the settings folder (*Open log* button), which is how you check a background run.

## 🤖 MCP server (use it from Claude and other AI tools)

`mcp_server.py` lets MCP clients such as Claude Code or Claude Desktop use your local voices: *"say this out loud with AI Voice Studio"*, *"transcribe this recording"*. It is a small bridge to the Local API (no extra pip package), reads the port and key the app saved, and starts the app in the background if it is not running.

Tools: `speak` (text to a WAV in your output folder, never overwriting), `list_voices`, `transcribe` (optionally with word timestamps), `status`.

Claude Code (run once; use your own paths, and the venv's Python):

```bash
claude mcp add ai-voice-studio -- /path/to/ai_voice_studio/venv/bin/python /path/to/ai_voice_studio/mcp_server.py
```

**Packaged builds** have it built in: run the app with `--mcp` instead of a script. Easiest: in the app's **Local API** section press **Copy MCP command** and paste it in a terminal. By hand:

```bash
# Linux AppImage
claude mcp add --scope user ai-voice-studio -- /path/to/AI_Voice_Studio.AppImage --mcp
# macOS
claude mcp add --scope user ai-voice-studio -- "/Applications/AI Voice Studio.app/Contents/MacOS/AI_Voice_Studio" --mcp
# Windows
claude mcp add --scope user ai-voice-studio -- "C:\Program Files\AI Voice Studio\AI_Voice_Studio.exe" --mcp
```

Optional environment variables: `AVS_API_URL`, `AVS_API_KEY`, `AVS_OUTPUT_DIR`, `AVS_MCP_NO_LAUNCH=1`.

## ✅ Self-test

Check that the Local API, the background engine and the MCP server really work on your machine. In the app: **Local API → Run self-test** (live PASS / FAIL lines, *Copy results*, *Open log*). From a terminal:

```bash
python selftest.py                 # from source
./AI_Voice_Studio.AppImage --selftest      # packaged build (Windows: AI_Voice_Studio.exe --selftest)
```

It starts a temporary background engine if none is running (and stops it again; it never stops one that was already running), then checks: API reachable, key enforced, voices, speech, **speed / volume / pitch / depth actually change the audio** (length, loudness, pitch, voice depth), a speech-to-text round trip, word timestamps, the MCP handshake, and that the background engine runs without a window, refuses a twin, and stops cleanly. Exit code 1 if anything failed; everything is also written to `app.log`. `--no-mcp` skips the MCP step. It needs the speech and recognition models installed.

**Testing a downloaded build** (e.g. the CI artifact on Linux), no Python needed:

```bash
chmod +x AI_Voice_Studio*.AppImage
./AI_Voice_Studio*.AppImage --selftest      # packaged app, headless engine and MCP in one go
```

On Windows run the same `--selftest` flag from a terminal; on macOS use `"/Applications/AI Voice Studio.app/Contents/MacOS/AI_Voice_Studio" --selftest`. The log is `app.log` in the settings folder (Linux `~/.config/AI Voice Studio/`, macOS `~/Library/Application Support/AI Voice Studio/`, Windows `%APPDATA%\AI Voice Studio\`).

## 🗂️ Project layout

| File | Purpose |
|---|---|
| `main.py` | The application and its interface |
| `engines/` | The TTS engines (Kokoro, VCTK, XTTS-v2), model paths and downloads |
| `audio_fx.py` | Speed, pitch, volume and depth processing, curve maths |
| `curve_editor.py` | The curve editor window |
| `voice_finder.py` | Voice measurements and the "find a voice by traits" window |
| `live_pitch.py` | Real-time pitch shifter for the voice changer |
| `subtitles.py` | Caption generation (SRT / VTT) |
| `*.spec`, `build.py`, `build_appimage.sh`, `installer_public.iss` | Packaging for the three platforms |
| `THIRD_PARTY_LICENSES.md` | Licenses of everything the app uses |

## 🚧 Known gaps

* On Windows and macOS the virtual microphone needs [VB-Cable](https://vb-audio.com/Cable/) / [BlackHole](https://existential.audio/blackhole/) installed first (Linux creates it automatically). This path is new and has had little testing. Live Pitch now also uses PyAudio output there, equally untested.
* Depth and the other effects are applied after speech is generated, so extreme settings can sound slightly metallic.
* Voice changer with Whisper still waits for the end of a phrase; only Vosk recognizes while you speak.
* A full test of the packaged builds takes 45-60 minutes, so Windows and macOS builds are tested less often than Linux.

## 🧭 What's next

**Shipped recently:** headless engine mode, API docs and examples, end-to-end self-test (`--selftest`), MCP server for Claude and other AI tools, start the Local API at launch / login (also in the background), a log file, faster voice changer (fast-Whisper warm-up, sentence-by-sentence speech, Vosk recognizes while you talk), click / typing / hallucination filtering, extra speed and pitch for selected text, Live Pitch and virtual mic code for Windows and macOS, in-app **Leave Feedback**, word timestamps in the Local API.

**Next up**
* Test the Windows and macOS builds on real machines (virtual microphone, Live Pitch)
* Automated Windows / macOS builds on GitHub Actions, so releases need less manual testing

**Lower voice-changer delay**
* Whisper still waits for the end of your phrase; transcribe while you talk (partial results) the way Vosk already does
* Smarter end-of-phrase detection with a real voice-activity model instead of an energy threshold
* Start speaking before the whole sentence is synthesized (chunked TTS)

**Quality**
* Cleaner pitch / depth effects at extreme settings (less metallic)
* Optional larger Vosk models for better live accuracy

**Local API**
* Streamed speech responses for long text
* Make the optional token easier to set up

**Housekeeping**
* Automated tests for the audio effects, report building and API parsing
* Python 3.13 support (the live recognizer currently uses `audioop`)

## 🤝 Contributing

Contributions are welcome: bug reports, feature ideas, interface and documentation improvements, fixes, integrations and performance work. For a larger change, please open an issue first so the approach can be discussed before significant work begins.

## ⚠️ Third-party models and software

AI-Voice-Studio is a wrapper and interface around existing open-source technology. It does not claim ownership of any third-party model, library or dataset. Those components are **not** covered by this project's license and each stays under its own license and terms - see [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md). If you redistribute a build, you are responsible for complying with the licenses of everything included in it.

## 📄 License

AI-Voice-Studio is released under the **AI-Voice-Studio Source-Available License v1.0**. [LICENSE.txt](LICENSE.txt) is the only authoritative text; in short:

* You may view, study, use (personally or commercially) and modify the code.
* You may create non-commercial forks and independent add-ons.
* You may build larger commercial products or services that use AI-Voice-Studio as a component, as long as they add substantial functionality of their own.
* You may **not** sell AI-Voice-Studio itself, sell a substantially derived fork, or rebrand it as a competing product without written permission.
* Keep the license and copyright notices, and do not imply official endorsement.

## 👤 Author

Created and maintained by **somore100**. If you build something interesting with AI-Voice-Studio, feel free to share it!

<img width="817" height="695" alt="AI Voice Studio screenshot" src="https://github.com/user-attachments/assets/8b3a1d86-9509-4504-9222-c439fbe0d950" />
<img width="817" height="695" alt="AI Voice Studio screenshot" src="https://github.com/user-attachments/assets/a7ccb209-ca22-44ea-b5dd-2b9000b077ae" />
