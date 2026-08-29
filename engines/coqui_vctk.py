"""VCTK (English, 109 speakers) via Coqui TTS - tts_models/en/vctk/vits.

Reference implementation of the EngineSpec interface - copy this file's
shape when adding a new engine (Piper, Kokoro, Fish Speech, MeloTTS,
ChatTTS, ...).
"""
import os

from .base import EngineSpec, dir_has_substantial_file
from .paths import get_tts_cache_dir

_instance = None  # lazy-loaded TTS() instance, cached for reuse


def build(models_base):
    local_path = os.path.join(models_base, "vctk")

    def is_installed():
        if dir_has_substantial_file(local_path):
            return True
        cache = get_tts_cache_dir()
        if not os.path.isdir(cache):
            return False
        return any(
            dir_has_substantial_file(os.path.join(cache, d))
            for d in os.listdir(cache) if "vctk" in d
        )

    def download():
        from TTS.api import TTS
        TTS(model_name="tts_models/en/vctk/vits", progress_bar=False, gpu=False)

    def _get_instance():
        global _instance
        if _instance is None:
            from TTS.api import TTS
            if os.path.isdir(local_path):
                _instance = TTS(
                    model_path=local_path,
                    config_path=os.path.join(local_path, "config.json"),
                    progress_bar=False, gpu=False)
            else:
                _instance = TTS(model_name="tts_models/en/vctk/vits",
                                 progress_bar=False, gpu=False)
        return _instance

    def list_voices():
        return sorted(_get_instance().speakers or [])

    def synthesize(text, voice, out_path, language=None):
        _get_instance().tts_to_file(text=text, speaker=voice, file_path=out_path)

    return EngineSpec(
        key="vctk",
        display_name="VCTK English voices",
        approx_size="~150 MB",
        description="English TTS (100+ voices)",
        license="Apache 2.0",
        requires_tos=False,
        is_installed=is_installed,
        download=download,
        list_voices=list_voices,
        synthesize=synthesize,
    )
