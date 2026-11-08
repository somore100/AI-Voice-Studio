# AI-Voice-Studio

**Speak, listen, translate and change your voice - with AI models that run on your own computer.**

AI-Voice-Studio is a desktop app that puts text-to-speech, speech-to-text, subtitles, translation and a live voice changer behind one simple interface. It wraps open-source models, so you do not have to wrestle with each model, its dependencies and its command line separately.

![Platforms](https://img.shields.io/badge/platforms-Windows%20%7C%20Linux%20%7C%20macOS-blue)
![Python](https://img.shields.io/badge/python-3.12-blue)
![License](https://img.shields.io/badge/license-Source--Available%20v1.0-orange)
![Status](https://img.shields.io/badge/status-active%20development-green)

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

Other programs can use this app's voices and Whisper instead of installing their own models. Turn it on in the **Local API** section (it listens on `127.0.0.1` only, optional token). It speaks the OpenAI format, so any app with a "custom / local OpenAI provider" setting works: base URL `http://127.0.0.1:8765/v1`.

```bash
curl http://127.0.0.1:8765/v1/audio/speech -H "Content-Type: application/json" \
  -d '{"model":"kokoro","voice":"af_heart","input":"Hello there"}' -o hello.wav
curl http://127.0.0.1:8765/v1/audio/transcriptions -F file=@hello.wav -F model=whisper-1
```

Endpoints: `/v1/audio/speech`, `/v1/audio/transcriptions`, `/v1/audio/translations`, `/v1/models`, `/v1/voices`. Extra speech fields: `language`, `pitch`, `volume`, `depth`.

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
* A full test of the packaged builds takes 45-60 minutes, so Windows and macOS builds are tested less often than Linux.

## 🧭 What's next

* Test the Windows / macOS virtual microphone on real machines
* Test Live Pitch on Windows and macOS (implemented, untested)
* Even lower voice-changer delay (streaming speech recognition)

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
