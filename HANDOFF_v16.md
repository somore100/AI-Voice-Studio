# AI Voice Studio - Handoff v16

Project: `/home/domore100/AI_Workspace/projects/Local/ai_voice_studio` (in the Claude sandbox: `/run/host/home/domore100/...`).
Python 3.12 + Tkinter. Main file `main.py`, helpers `audio_fx.py`, `curve_editor.py`, `voice_finder.py`, `live_pitch.py`, `subtitles.py`, `api_server.py`, `engines/`.

## Environment notes
* `git` is not installed in the Claude sandbox: use `distrobox-host-exec git ...`. `wpctl`/`pactl` likewise need `distrobox-host-exec` there (run them plainly in the user's own terminal).
* The sandbox cannot run the GUI or audio; check with `python3 -m py_compile main.py`.

## Git state
* Branch `feat/roadmap-voice-changer-latency`, all work committed locally, **not pushed, no PR yet**.
* Untracked on purpose: `main.sync-conflict-*.py`, `README.sync-conflict-*.md` (old Syncthing copies; delete once confirmed unneeded).

## Done (compile-checked; user-tested = works)
1. Voice changer latency: fast-Whisper warm-up, shorter pause thresholds. (user-tested)
2. Selected-text-only speed/pitch in the TTS tab. (user-tested, works)
3. Windows/macOS virtual mic via PyAudio into VB-Cable / BlackHole. (UNTESTED, needs real machines)
4. Live Pitch on Windows/macOS via `_PyAudioOut`. (UNTESTED)
5. Voice changer streams TTS per sentence: playback starts on sentence 1 while the rest synthesize. (user-tested)
6. Mini-mode equalizer bars follow the real mic level (`_MIC_LEVEL`, set in `_DCBlockStream.read`). (user-tested)
7. Streaming recognition for Vosk: `listen_vosk` inside `_vc_pipeline` feeds Vosk while you speak; the worker receives finished text (a `str`) instead of PCM. Whisper paths unchanged. (UNTESTED at runtime)
8. Resample guard added in `_tts_synth_sel`.

## Next
* Test streaming Vosk (STT engine Vosk in the voice changer): phrases not cut or doubled, "hear" ~0s in `VC timing`. Uses `audioop` (Python <=3.12 or `audioop-lts`).
* Push the branch and open a PR into `main`.
* Build and test on Windows/macOS (virtual mic + Live Pitch).
* Whisper still waits for end of phrase; speculative partial transcription would be the next latency step.
* Known gap: depth/effects can sound metallic at extremes.
* Seen once on closing the app: `terminate called without an active exception` (core dump) right after mic check, closed during startup. Likely native thread at shutdown; not reproduced.

## Useful pointers in `main.py`
* Voice changer: `_vc_pipeline` (`listen_vosk`, `worker`), `_vc_live_loop`, `_vc_play`, `_PyAudioOut`, `_vmic_*`
* Mic: `_open_mic`, `_DCBlockStream`, `_MIC_LEVEL`; mini bars `_animate_eq`
* TTS: `preview_voice`, `generate_voice`, `_sel_capture`, `_tts_synth_sel`, `_apply_tts_fx`
