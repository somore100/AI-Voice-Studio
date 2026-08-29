"""Aggregates every available TTS engine into one lookup table.

main.py drives its Models table, download flow, and license-consent
flow entirely off this dict - it never hardcodes an engine's name,
path, or download logic itself. To add a new engine (Piper, Kokoro,
Fish Speech, MeloTTS, ChatTTS, ...):

  1. Write a new module in this package with a build(models_base)
     function that returns an EngineSpec (copy coqui_vctk.py's shape -
     it's the simplest reference implementation; coqui_xtts.py shows
     the extra requires_tos=True path for engines with a license
     click-through).
  2. Add one line to get_tts_engines() below.

Nothing else in the app needs to change - the Models table rows, the
Check All / Download Missing buttons, per-engine license dialogs, and
the voice dropdown all populate themselves from this dict.
"""
from . import coqui_vctk, coqui_xtts


def get_tts_engines(models_base):
    return {
        "vctk": coqui_vctk.build(models_base),
        "xtts": coqui_xtts.build(models_base),
        # Future engines go here, e.g.:
        # "piper":       piper.build(models_base),
        # "kokoro":      kokoro.build(models_base),
        # "fish_speech": fish_speech.build(models_base),
        # "melo":        melo.build(models_base),
        # "chattts":     chattts.build(models_base),
    }
