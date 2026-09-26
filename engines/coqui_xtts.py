"""XTTS-v2 (multilingual, 17 languages) via Coqui TTS.

Distributed under Coqui's CPML license, so requires_tos=True - see
CPML_TEXT below. main.py's generic _ensure_engine_tos() reads
requires_tos/tos_title/tos_text off this EngineSpec to show a GUI
consent dialog before ever calling download()/synthesize(), and sets
COQUI_TOS_AGREED=1 so Coqui's own code (which would otherwise block on
a terminal input() call - fatal from a background thread / a packaged
app with no terminal at all) skips its own prompt.
"""
import os

from .base import EngineSpec, dir_has_substantial_file
from .paths import get_tts_cache_dir

_instance = None  # lazy-loaded TTS() instance, cached for reuse

# XTTS-v2's checkpoint ships with a fixed set of built-in preset speaker
# latents baked in (accessible as `tts.speakers` / `speaker_manager
# .speaker_names` once the model is loaded). This list is a static
# property of every XTTS-v2 v2.0.x download - it doesn't require loading
# the (large, slow) model just to populate a voice dropdown. Source:
# https://coqui-tts.readthedocs.io/en/latest/models/xtts.html
PRESET_SPEAKERS = [
    "Claribel Dervla", "Daisy Studious", "Gracie Wise", "Tammie Ema",
    "Alison Dietlinde", "Ana Florence", "Annmarie Nele", "Asya Anara",
    "Brenda Stern", "Gitta Nikolina", "Henriette Usha", "Sofia Hellen",
    "Tammy Grit", "Tanja Adelina", "Vjollca Johnnie", "Andrew Chipper",
    "Badr Odhiambo", "Dionisio Schuyler", "Royston Min", "Viktor Eka",
    "Abrahan Mack", "Adde Michal", "Baldur Sanjin", "Craig Gutsy",
    "Damien Black", "Gilberto Mathias", "Ilkin Urbano", "Kazuhiko Atallah",
    "Ludvig Milivoj", "Suad Qasim", "Torcull Diarmuid", "Viktor Menelaos",
    "Zacharie Aimilios", "Nova Hogarth", "Maja Ruoho", "Uta Obando",
    "Lidiya Szekeres", "Chandra MacFarland", "Szofi Granger",
    "Camilla Holmström", "Lilya Stainthorpe", "Zofija Kendrick",
    "Narelle Moon", "Barbora MacLean", "Alexandra Hisakawa", "Alma María",
    "Rosemary Okafor", "Ige Behringer", "Filip Traverse",
    "Damjan Chapman", "Wulf Carlevaro", "Aaron Dreschner", "Kumar Dahl",
    "Eugenio Mataracı", "Ferran Simen", "Xavier Hayasaka", "Luis Moray",
    "Marcos Rudaski",
]

# Voice-cloning marker: EngineSpec.synthesize()'s `voice` param is a
# plain string shared across every engine (preset name, VCTK speaker
# id, ...), so rather than widen that interface for every engine just
# for XTTS's sake, a cloned voice is passed as this prefix + the
# reference clip's path. Only this module ever needs to know about it -
# main.py just builds the string via this same constant.
CLONE_PREFIX = "__clone__:"

CPML_TEXT = (
    "XTTS-v2 is distributed under Coqui's CPML license, not a fully "
    "open license.\n\n"
    "By downloading this model you agree to one of the following:\n"
    "  \u2022 You have purchased a commercial license from Coqui "
    "(licensing@coqui.ai), OR\n"
    "  \u2022 You agree to the terms of the non-commercial CPML "
    "license (https://coqui.ai/cpml)\n\n"
    "Do you agree, and want to proceed with the XTTS-v2 download?"
)


def build(models_base):
    local_path = os.path.join(models_base, "xtts_v2")

    def is_installed():
        if dir_has_substantial_file(local_path):
            return True
        cache = get_tts_cache_dir()
        if not os.path.isdir(cache):
            return False
        return any(
            dir_has_substantial_file(os.path.join(cache, d))
            for d in os.listdir(cache) if "xtts_v2" in d
        )

    def download(progress_cb=None):
        import torch, torch.serialization
        try:
            from TTS.tts.configs.xtts_config import XttsConfig
            torch.serialization.add_safe_globals([XttsConfig])
        except Exception:
            pass
        from TTS.api import TTS
        from .download_progress import progress_hook
        with progress_hook(progress_cb):
            TTS(model_name="tts_models/multilingual/multi-dataset/xtts_v2",
                progress_bar=True, gpu=False)

    def _get_instance():
        global _instance
        if _instance is None:
            import torch, torch.serialization
            try:
                from TTS.tts.configs.xtts_config import XttsConfig
                torch.serialization.add_safe_globals([XttsConfig])
            except Exception:
                pass
            from TTS.api import TTS
            if os.path.isdir(local_path):
                _instance = TTS(
                    model_path=local_path,
                    config_path=os.path.join(local_path, "config.json"),
                    progress_bar=False, gpu=False)
            else:
                _instance = TTS(model_name="tts_models/multilingual/multi-dataset/xtts_v2",
                                 progress_bar=False, gpu=False)
        return _instance

    def list_voices():
        return list(PRESET_SPEAKERS)

    def synthesize(text, voice, out_path, language=None):
        # XTTS has no "default" voice of its own - it's a cloning model,
        # so it always needs either a speaker_wav (clone from audio) or a
        # speaker name (one of the built-in presets above). Without one
        # of those, Coqui's own code raises "Neither speaker_wav nor
        # speaker_id was specified".
        if voice and voice.startswith(CLONE_PREFIX):
            speaker_wav = voice[len(CLONE_PREFIX):]
            _get_instance().tts_to_file(
                text=text, language=language or "en", speaker_wav=speaker_wav,
                file_path=out_path)
            return
        # Not a clone reference - fall back to the first preset rather
        # than ever calling tts_to_file() with neither speaker_wav nor
        # speaker if we weren't given a valid preset name.
        speaker = voice if voice in PRESET_SPEAKERS else PRESET_SPEAKERS[0]
        _get_instance().tts_to_file(
            text=text, language=language or "en", speaker=speaker,
            file_path=out_path)

    return EngineSpec(
        key="xtts",
        display_name="XTTS-v2 Multilingual",
        approx_size="~1.8 GB",
        description="Multilingual TTS (17 languages)",
        license="CPML (non-commercial / licensed)",
        requires_tos=True,
        tos_title="XTTS-v2 License (CPML)",
        tos_text=CPML_TEXT,
        is_installed=is_installed,
        download=download,
        list_voices=list_voices,
        synthesize=synthesize,
    )
