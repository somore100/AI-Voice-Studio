# AI-Voice-Studio

An offline desktop app that puts text-to-speech, speech-to-text, translation and a live voice changer behind one simple interface. It wraps open-source models, so you do not have to wrestle with each model, its dependencies and its command line separately.

> **Status:** Active development

<img width="817" height="695" alt="AI_voice_studio" src="https://github.com/user-attachments/assets/bda9a7f6-6b42-42c5-9651-b0b3ad299cc3" />

## ✨ Features

**Text-to-Speech** (runs locally, no cloud)
* Three engines in one app: **VCTK** (100+ English voices), **XTTS-v2** (17 languages, voice cloning) and **Kokoro** (fast, natural, 54 voices in 8 languages)
* Speed, pitch and volume sliders - or type an exact value
* **Depth** control: changes the "body" of a voice (deeper or lighter) without changing its pitch
* **Curve editor:** draw speed, pitch and volume curves over a waveform timeline with sentence markers, zoom and snap-to-pause
* Preview, save to WAV, favourite voices

**Speech-to-Text**
* **Whisper** and **Vosk** engines, many languages
* Captions: turn audio or video into SRT / VTT subtitles (needs the `ffmpeg` binary)

**Translator**
* Text translation between many languages

**Voice changer**
* *TTS pipeline:* your microphone is transcribed and re-spoken in a chosen voice, with its own spoken-language setting (or auto-detect with Whisper)
* *Live Pitch:* instant pitch shifting
* Optional virtual microphone for calls and chat apps (Linux, via PipeWire / PulseAudio)

**Quality of life**
* Searchable drop-downs for every long list (languages, voices, microphones)
* Models & Setup panel: download, check and uninstall models from inside the app
* Your settings are remembered between launches
* Dark theme

## 📦 Installation

Builds for Windows, Linux (AppImage) and macOS are produced by GitHub Actions: open the **Actions** tab, choose **Build All Platforms** and download the artifact for your system (or check the Releases page if a release has been published).

On first use, open **Models & Setup** and download the models you want. They are stored on your machine; nothing is sent to a server when you generate speech.

### Run from source

Requirements: Python 3.12, plus a few system tools.

```bash
git clone https://github.com/somore100/AI-Voice-Studio.git
cd AI-Voice-Studio
python3.12 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

System tools: `ffmpeg` (captions), `espeak-ng` (some voices), PortAudio (microphone input). On Linux, the voice changer's virtual microphone needs `pactl` / `paplay` (PipeWire or PulseAudio).

Where things are stored: models live in `./models/` when running from source (packaged Linux builds use `~/.local/share/AI Voice Studio/models`); settings are saved to a small `settings.json` in your user config folder.

## 🚧 Known gaps

* The virtual microphone is Linux-only for now (Windows VB-Cable and macOS BlackHole support are not done).
* Frozen builds take 45-60 minutes per test cycle, so Windows and macOS builds get tested less often than Linux.
* Depth, like the other effects, is applied after speech is generated, so very large settings can sound slightly metallic.

## 🤝 Contributing

Contributions are welcome: bug reports, feature ideas, interface and documentation improvements, fixes, integrations and performance work. For a larger change, please open an issue first so the approach can be discussed.

## ⚠️ Third-party models and software

AI-Voice-Studio uses third-party models, libraries and tools. They are **not** covered by this project's license and remain under their own licenses and terms - see [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md). If you redistribute a build, you are responsible for complying with the licenses of everything included in it.

## 📄 License

AI-Voice-Studio is released under the **AI-Voice-Studio Source-Available License v1.0** - see [LICENSE.txt](LICENSE.txt) for the full text, which is the only authoritative version. In short:

* You may view, study, use (personally or commercially) and modify the code.
* You may create non-commercial forks and independent add-ons.
* You may build larger commercial products or services that use AI-Voice-Studio as a component, as long as they add substantial functionality of their own.
* You may **not** sell AI-Voice-Studio itself, sell a substantially derived fork, or rebrand it as a competing product without written permission.
* Keep the license and copyright notices, and do not imply official endorsement.

## 👤 Author

Created and maintained by **somore100**. If you build something interesting with it, feel free to share it!

<img width="817" height="695" alt="Ai_voice_studio 2026-08-24 18-48-10" src="https://github.com/user-attachments/assets/8b3a1d86-9509-4504-9222-c439fbe0d950" />
<img width="817" height="695" alt="Ai_voice_studio 2026-08-24 18-47-37" src="https://github.com/user-attachments/assets/a7ccb209-ca22-44ea-b5dd-2b9000b077ae" />
