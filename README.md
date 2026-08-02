# AI Voice Studio
 
A local AI voice toolkit focused on making voice AI more accessible through a unified interface.
 
AI Voice Studio provides tools for text-to-speech (TTS), speech-to-text (STT), voice changing, and translation features. The goal is to create a lightweight local alternative to cloud-based voice platforms, especially for users who want more control over their AI tools.
 
## Features
 
- Text-to-Speech (TTS)
- Speech-to-Text (STT)
- AI voice changing
- Translation tools
- Local AI workflow support
- Unified voice processing interface
## Why?
 
Many local AI tools focus on text generation and image generation, but local voice solutions are still limited and often require complicated setups.
 
AI Voice Studio aims to provide an easier way to experiment with local voice AI.
 
## Current Status
 
🟡 In development
 
- Python implementation available (Linux + Windows)
- Core functionality working
- Windows installer builds automatically via GitHub Actions
- Linux AppImage build in progress
- Packaging and executable builds still need improvement
## Requirements
 
- **Python 3.10** (required — the TTS engine this project depends on does not support Python 3.12, and 3.11 is untested here)
- Linux: `portaudio19-dev` and `python3-dev` system packages (needed for PyAudio)
- ~3-5 GB free disk space for models (downloaded on first run)
## Installation
 
Clone the repository:
 
```bash
git clone https://github.com/somore100/ai-voice-studio.git
cd ai-voice-studio
```
 
Create and activate a virtual environment (use `--system-site-packages` to avoid `pkg_resources` import errors):
 
```bash
python3.10 -m venv venv --system-site-packages
source venv/bin/activate      # Windows: venv\Scripts\activate
```
 
Install dependencies:
 
```bash
pip install --upgrade pip
pip install -r requirements.txt
```
 
Run:
 
```bash
python main.py
```
 
## Building
 
- **Windows installer**: handled automatically by GitHub Actions on push to `main` (see `.github/workflows/build.yml`), or locally via `build_manager.py`.
- **Linux AppImage**: build instructions coming soon.
## Roadmap
 
- [ ] Linux AppImage packaging
- [ ] Better executable builds
- [ ] Improved UI
- [ ] More local AI model support (edge-tts, Kokoro TTS)
- [ ] Voice changer
- [ ] Easier model management
- [ ] Performance improvements
- [ ] loading bar for dowlads
## License
 
MIT
