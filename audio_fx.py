"""Post-processing for synthesized speech: speed and pitch.

Works on any engine's WAV output, in place. Speed changes the duration
without changing pitch; pitch shifts in semitones without changing the
duration. Needs librosa + soundfile (both already installed as coqui-tts
dependencies and listed in requirements.txt / the PyInstaller specs).
"""
import os
import tempfile


def apply_fx(path, speed=1.0, pitch=0.0):
    """Rewrite the WAV at `path` with the given effects.

    speed:  1.0 = unchanged, 2.0 = twice as fast, 0.5 = half speed.
    pitch:  semitones, 0 = unchanged (+12 = one octave up).
    Returns True if the file was modified, False if nothing needed doing.
    """
    speed = float(speed)
    pitch = float(pitch)
    do_speed = abs(speed - 1.0) >= 0.01
    do_pitch = abs(pitch) >= 0.05
    if not (do_speed or do_pitch):
        return False

    import numpy as np
    import librosa
    import soundfile as sf

    y, sr = librosa.load(path, sr=None, mono=True)
    if y.size == 0:
        return False
    if do_pitch:
        y = librosa.effects.pitch_shift(y, sr=sr, n_steps=pitch)
    if do_speed:
        y = librosa.effects.time_stretch(y, rate=speed)

    peak = float(np.max(np.abs(y)))
    if peak > 0.99:                      # avoid clipping after processing
        y = y * (0.98 / peak)

    fd, tmp = tempfile.mkstemp(suffix=".wav", dir=os.path.dirname(path) or ".")
    os.close(fd)
    try:
        sf.write(tmp, y, sr, subtype="PCM_16")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return True
