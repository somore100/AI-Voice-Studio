"""Shared interface + helpers for pluggable TTS engines.

Adding a new engine (Piper, Kokoro, Fish Speech, MeloTTS, ChatTTS, ...)
means: write one new module in this package with a build(models_base)
function returning an EngineSpec (see coqui_vctk.py for the reference
shape), then add one line in registry.py. Nothing in main.py's Models
table, download flow, or license-consent flow needs to change - all of
that drives off this registry instead of per-engine if/elif chains.
"""
from dataclasses import dataclass
from typing import Callable, List, Optional
import os


def dir_has_substantial_file(dirpath: str, min_bytes: int = 10 * 1024 * 1024) -> bool:
    """True if dirpath exists and holds at least one file >= min_bytes.

    Every engine's is_installed() should use this (or an equivalent
    size check) rather than a bare os.path.isdir()/os.listdir() check.
    Downloaders routinely create the destination folder immediately,
    before any content lands in it, so folder-existence alone reports
    "installed" for a download that was interrupted partway through
    (app closed mid-download, lost connection, etc.) and never actually
    finished. This bit us for real with XTTS-v2: a folder existed but
    was 4KB against an expected ~1.8GB.
    """
    if not os.path.isdir(dirpath):
        return False
    for root, _dirs, files in os.walk(dirpath):
        for fname in files:
            try:
                if os.path.getsize(os.path.join(root, fname)) >= min_bytes:
                    return True
            except OSError:
                continue
    return False


@dataclass
class EngineSpec:
    key: str                      # unique id: "vctk", "xtts", "piper", ...
    display_name: str             # shown in the Models table
    approx_size: str              # human string for the UI, e.g. "~1.8 GB"
    description: str              # short one-liner for the Models table
    license: str = ""             # informational only, shown in tooltips/docs
    requires_tos: bool = False    # True if a license click-through is needed
    tos_title: str = ""
    tos_text: str = ""

    # -- capability functions, all provided by the concrete engine module --

    # is_installed() -> bool
    #   Cheap enough to call on every "Check All" / startup check.
    is_installed: Optional[Callable[[], bool]] = None

    # download() -> None
    #   BLOCKING call. The caller (main.py) runs it on a background
    #   thread and catches exceptions - engines should just raise on
    #   failure rather than swallowing errors themselves.
    download: Optional[Callable[[], None]] = None

    # list_voices() -> list[str]
    #   Speaker/voice IDs this engine offers, or [] for a single-voice
    #   engine. Used to populate the voice dropdown when selected.
    list_voices: Optional[Callable[[], List[str]]] = None

    # synthesize(text, voice, out_path, language) -> None
    #   Renders `text` to a wav at out_path. `voice` is one of the IDs
    #   from list_voices(), or None. `language` is a language code for
    #   multilingual engines, or None for single-language ones.
    synthesize: Optional[Callable[[str, Optional[str], str, Optional[str]], None]] = None
