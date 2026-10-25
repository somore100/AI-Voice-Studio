# AI Voice Studio - Handoff v15

Project: `/home/domore100/AI_Workspace/projects/Local/ai_voice_studio` (host path; in the Claude sandbox it is `/run/host/home/domore100/AI_Workspace/projects/Local/ai_voice_studio`).
Python 3.12 + Tkinter desktop app. Main file `main.py` (~210 KB), helpers in `audio_fx.py`, `curve_editor.py`, `voice_finder.py`, `live_pitch.py`, `subtitles.py`, `api_server.py`, `engines/`.

## Environment notes
* `git` is NOT installed inside the Claude sandbox. Use `distrobox-host-exec git ...` (works).
* Sandbox cannot run the GUI or test audio; everything below is compile-checked only (`python3 -m py_compile main.py`).

## Git state
* Branch: `feat/roadmap-voice-changer-latency` (created from `main`). **Nothing committed yet.**
* Uncommitted changes that predate this session and came along: `api_server.py` (untracked, the Local API), edits to the three `*.spec` files, `HANDOFF_v14.md` deleted. Decide whether to commit them separately from the roadmap work.

## Done this session (all untested at runtime)
1. **Voice changer latency** (`main.py`, `_vc_pipeline`): warm-up transcribe of silence after loading faster-whisper; `pause_threshold` 0.45 -> 0.4, `non_speaking_duration` 0.35 -> 0.3; timing log message updated.
2. **Selected text only speed/pitch** (`main.py`): new row above "Save to:" in the TTS tab (`tts_sel_on`, `tts_sel_speed`, `tts_sel_pitch`). `_sel_capture()` runs on the main thread in `preview_voice` / `generate_voice`; `_tts_synth_sel()` synthesizes before/selection/after separately, applies `audio_fx.apply_fx` to the selection piece, joins with `audio_fx.stitch` (0.1 s gap). Only in Sliders mode (ignored when Curves is on). Global sliders still apply afterwards to the whole clip.
3. **Windows/macOS virtual mic** (`main.py`): `_VMIC_CABLE`, `_vmic_cable_device()`, `_CablePlayer` (PyAudio playback into "CABLE Input" / "BlackHole"); `_vmic_tools/_vmic_create/_vmic_destroy/_vmic_play` and UI hint text branch on platform. Linux path unchanged. Live Pitch mode remains Linux-only (needs `pacat`).
4. README updated (feature list, known gaps, "What's next").

## First things to do next
1. Run the app (`source venv/bin/activate && python main.py`) and test:
   * Voice changer, STT->TTS with Whisper (fast): warm-up shows, no errors, phrases not cut off by the shorter pause.
   * Selected-text effect: select a few words, tick the box, Preview and Save; check speed/pitch applies only there, and that no selection or neutral values behave like before.
2. Commit (suggest two commits: roadmap work vs. pre-existing api_server/spec changes).
3. Windows/macOS cable playback needs a real test on those systems (device name matching, sample rate, PyAudio output).

## Remaining roadmap
* Test Windows/macOS virtual mic on real machines
* Live Pitch for Windows/macOS
* Lower voice-changer delay further (streaming recognition)
* Known gap: depth/effects applied post-generation can sound metallic at extremes

## Useful pointers in `main.py`
* Voice changer: `_vc_pipeline` (STT->TTS), `_vc_live_loop` (Live Pitch), `_vc_play`, `_vmic_*`
* TTS tab: `preview_voice`, `_do_preview_inner`, `generate_voice`, `_do_save`, `_apply_tts_fx`, `_get_timed_ref` (curve editor timeline)
