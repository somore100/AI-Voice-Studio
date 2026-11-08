# AI Voice Studio - Handoff v17

Project: `/home/domore100/AI_Workspace/projects/Local/ai_voice_studio` (Claude sandbox: `/run/host/home/domore100/...`).
Python 3.12 + Tkinter. `main.py`, `audio_fx.py`, `curve_editor.py`, `voice_finder.py`, `live_pitch.py`, `subtitles.py`, `api_server.py`, `feedback.py`, `engines/`.

## Environment notes
* `git`/`gh` are not installed in the Claude sandbox: use `distrobox-host-exec git ...` / `distrobox-host-exec gh ...`. `wpctl` etc. run plainly in the user's own terminal.
* Sandbox cannot run the GUI or audio and has no tkinter (stub it to test pure logic). Check with `python3 -m py_compile main.py`.
* If the voice changer says the mic is "pure silence": the default PipeWire source got muted again. `wpctl set-mute @DEFAULT_AUDIO_SOURCE@ 0 && wpctl set-volume @DEFAULT_AUDIO_SOURCE@ 0.8`.

## Git state
* Everything is on `main` (PRs #1 and #3 merged). Feature branches deleted.
* `main` is protected by a ruleset (no deletion, no force push; PRs not required).
* Lesson: when stacking PRs, retarget the second to `main` (or merge only after the base is retargeted) or it merges into the old branch.

## Done (user-tested on Linux unless noted)
* Voice changer: fast-Whisper warm-up, shorter pauses, TTS streamed per sentence, Vosk streaming (`listen_vosk`, worker accepts pre-recognized text), click/typing/hallucination filtering (`_voiced_seconds`, `_VC_JUNK`, VAD + no-speech filter), one clear error on a muted/unopenable mic.
* TTS tab: selected-text-only speed/pitch.
* Mini-mode bars follow the real mic level (`_MIC_LEVEL`).
* Leave Feedback: `feedback.py` (reusable, stdlib only) + footer button; sends via the shared Google Apps Script relay (`FEEDBACK_ENDPOINT` in main.py, same one as Arrows of War, goes to support.somore100@gmail.com); fallbacks Open in Gmail / mail app / Copy. Verified end to end.
* Local API: word timestamps (`timestamp_granularities[]=word` + `verbose_json` -> `words`), repeated multipart fields are merged. **Compile-checked and multipart-tested only; not run against a live server.**
* UNTESTED: Windows/macOS virtual mic and Live Pitch (PyAudio output).

## Next (also in README "What's next")
1. Run the API word-timestamp request against the live server (Whisper, fast-Whisper and Vosk paths).
2. Build and test on Windows/macOS; set up GitHub Actions builds.
3. Latency: partial transcription for Whisper, real VAD for end-of-phrase, chunked TTS.
4. Quality: metallic effects at extremes; larger Vosk models.
5. Tests for audio_fx / feedback / API parsing; Python 3.13 (`audioop`).
* Seen once: `terminate called without an active exception` when closing the app during startup. Not reproduced.

## Pointers in `main.py`
* Voice changer: `_vc_pipeline` (`listen_vosk`, `worker`), `_vc_live_loop`, `_vc_play`, `_PyAudioOut`, `_vmic_*`
* Mic: `_open_mic`, `_DCBlockStream`, `_MIC_LEVEL`; mini bars `_animate_eq`
* TTS: `preview_voice`, `generate_voice`, `_sel_capture`, `_tts_synth_sel`, `_apply_tts_fx`
* API backend: `_ApiBackend.stt` (words), `api_server.py` `_transcribe`
* Feedback: `AIApp.open_feedback`, `feedback.py`
