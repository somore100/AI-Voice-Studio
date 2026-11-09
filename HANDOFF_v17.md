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
* Local API autostart (branch feat/api-autostart): `autostart.py` (login modes off/window/background via XDG .desktop, Windows Run key, macOS LaunchAgent; single-instance via loopback port 47653), `applog.py` (tee stdout/stderr to `<settings dir>/app.log`), `--background` flag, "At login" selector + "Open log" in the API section, API-start preference now saved on toggle. Pure logic tested for real (Linux file, sockets, log); GUI flow, Windows registry and macOS plist NOT run.
* MCP server (`mcp_server.py`, stdlib JSON-RPC over stdio, tools speak/list_voices/transcribe/status; bridges to the Local API, reads port+key from prefs.json, auto-starts `main.py --background`; `speak` saves only a plain filename into the output folder, never overwrites). Tested end to end against the real api_server with a fake backend (initialize, tools, traversal-safe naming, word timestamps). NOT yet registered/run in a real client with the real app. Register: `claude mcp add ai-voice-studio -- <venv python> <path>/mcp_server.py`. `main.py --mcp` runs it before any heavy import (works frozen on all platforms: the Windows CI build has console=True, Linux/macOS keep stdio); `ensure_running` launches the packaged app via $APPIMAGE/sys.executable `--background`; API section has a Copy MCP command button. Source-run path tested; the frozen paths (PyInstaller picking up `import mcp_server`, AppImage/.app/.exe `--mcp`) are NOT tested until the CI build is run.
* Self-test (`selftest.py`, `main.py --selftest`): PASS/FAIL per step against the live API + MCP (speed/volume/pitch/depth verified by length/loudness/spectral centroid). Validated against a fake backend (healthy passes; a backend ignoring speed/depth is reported FAIL). NOT yet run against the real app: run `python selftest.py` and check pitch/depth directions with real voices.
* Headless engine (`headless.py`, `main.py --headless`, alias `--background`): Local API with no window/Tk; control port 47654 (info/stop; "starting" until the API listens); GUI attaches via `autostart.headless_probe()` instead of starting a second API (`_attach_engine`; the API button then stops the engine); login mode "background" now launches `--headless`; the old hide/show-window background mode was removed. `_voice_catalog()` is now module-level (no window state). Runner tested as real subprocesses (probe, second engine refused, busy API port, stop, SIGTERM, restart after stop; control sockets use SO_REUSEADDR / SO_EXCLUSIVEADDRUSE on Windows) and `main.py --headless` run with a stubbed tkinter. NOT tested: the window attaching (needs Tk), Windows console hiding.
* API docs `docs/API.md` + `examples/` (curl, Python client + narrate pipeline, OpenAI SDK, Node). Node and OpenAI-SDK examples untested (not installed here).
* Self-test pitch/depth checks now use real measurements (median f0; voiced-frame brightness) calibrated on real Kokoro speech.
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
