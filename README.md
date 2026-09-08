AI Voice Studio
A local, all-in-one AI voice toolkit — text-to-speech, speech-to-text, voice changing, and translation, unified in one lightweight interface. No cloud, no subscriptions, full control.

Many local AI tools focus on text and image generation, but local voice AI is still fragmented and often requires complicated setups. AI Voice Studio brings TTS, STT, voice changing, and translation together into one easy-to-run local app — built for people who want to experiment with voice AI without handing their data to a cloud provider.

Features
🗣️ Text-to-Speech (TTS)
🎙️ Speech-to-Text (STT)
🎭 AI voice changing
🌐 Translation tools
💻 Local AI workflow — everything runs on your machine
🧩 Unified interface for all voice processing tasks
Current Status
🟡 In development
Component
Status
Python implementation (Linux + Windows)
✅ Available
Core functionality
✅ Working
Windows installer
✅ Auto-built via GitHub Actions
Linux AppImage
🔨 In progress
Packaging / executable builds
🔨 Needs improvement

Requirements
Python 3.10 — required. The TTS engine this project depends on does not support Python 3.12, and 3.11 is untested.
Linux only: portaudio19-dev and python3-dev system packages (needed for PyAudio)
~3–5 GB free disk space for models (downloaded on first run)
Installation
Bash
Building
Windows installer: built automatically by GitHub Actions on every push to main (see .github/workflows/build.yml), or locally via build_manager.py.
Linux AppImage: build instructions coming soon.
Roadmap
[ ] API access — call voice creation from other apps (coming soon)
[ ] Linux AppImage packaging
[ ] Better executable builds
[ ] Improved UI
[ ] More local AI model support (edge-tts, Kokoro TTS)
[ ] Voice changer
[ ] Easier model management
[ ] Performance improvements
[ ] Download progress bar
Contributing
Issues and pull requests are welcome. If you hit a bug or have a feature idea, open an issue — especially around Linux packaging, which is the area most in need of help right now.
License

MIT
<img width="817" height="695" alt="AI_voice_studio" src="https://github.com/user-attachments/assets/bda9a7f6-6b42-42c5-9651-b0b3ad299cc3" />
<img width="817" height="695" alt="Ai_voice_studio 2026-08-24 18-48-10" src="https://github.com/user-attachments/assets/8b3a1d86-9509-4504-9222-c439fbe0d950" />
<img width="817" height="695" alt="Ai_voice_studio 2026-08-24 18-47-37" src="https://github.com/user-attachments/assets/a7ccb209-ca22-44ea-b5dd-2b9000b077ae" />
