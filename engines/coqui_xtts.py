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

    def download():
        import torch, torch.serialization
        try:
            from TTS.tts.configs.xtts_config import XttsConfig
            torch.serialization.add_safe_globals([XttsConfig])
        except Exception:
            pass
        from TTS.api import TTS
        TTS(model_name="tts_models/multilingual/multi-dataset/xtts_v2",
            progress_bar=False, gpu=False)

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
        return []  # XTTS uses language, not a fixed speaker list

    def synthesize(text, voice, out_path, language=None):
        _get_instance().tts_to_file(
            text=text, language=language or "en", file_path=out_path)

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
