"""Post-processing for synthesized speech: speed and pitch, constant or
following curves drawn over the speech.

Works on any engine's WAV output, in place. Needs librosa + soundfile (both
already installed as coqui-tts dependencies); scipy is used for smooth
curves when available.

apply_fx(path, speed, pitch, volume=1.0)        constant speed / pitch / volume
apply_fx(..., depth=d)                          + formant shift in semitones, pitch unchanged
                                                (+ = formants up/lighter, - = deeper)
apply_fx(path, speed, pitch, curves=state)      state from the curve editor:
    {"smooth": bool, "speed": [(x, mult), ...], "pitch": [(x, semitones), ...],
     "volume": [(x, gain), ...]}
    x is the position in the ORIGINAL speech, 0..1. The app uses EITHER the
    sliders OR the curves (it passes neutral slider values when curves are
    on); if both are given anyway they combine (speeds multiply, semitones
    add, gains multiply).
"""
import os
import tempfile

import numpy as np

SPEED_MIN, SPEED_MAX = 0.5, 2.0
PITCH_MIN, PITCH_MAX = -12.0, 12.0
VOL_MIN, VOL_MAX = 0.0, 2.0
DEPTH_MIN, DEPTH_MAX = -8.0, 8.0     # "depth" in semitones of formant shift


def curve_func(points, smooth=True, lo=None, hi=None):
    """Return f(x) -> y for curve points [(x, y), ...] over x in 0..1."""
    pts = sorted((float(x), float(y)) for x, y in points)
    clean = []
    for x, y in pts:
        x = min(max(x, 0.0), 1.0)
        if clean and x - clean[-1][0] < 1e-4:
            clean[-1] = (clean[-1][0], y)
        else:
            clean.append((x, y))
    if not clean:
        clean = [(0.0, 0.0)]
    if clean[0][0] > 0.0:
        clean.insert(0, (0.0, clean[0][1]))
    if clean[-1][0] < 1.0:
        clean.append((1.0, clean[-1][1]))
    xs = np.array([p[0] for p in clean])
    ys = np.array([p[1] for p in clean])
    interp = None
    if smooth and len(xs) >= 3:
        try:
            from scipy.interpolate import PchipInterpolator
            interp = PchipInterpolator(xs, ys)
        except Exception:
            interp = None

    def f(x):
        x = np.clip(np.asarray(x, dtype=np.float64), 0.0, 1.0)
        y = interp(x) if interp is not None else np.interp(x, xs, ys)
        if lo is not None:
            y = np.clip(y, lo, hi)
        return y
    return f


def _is_flat(points, value):
    return all(abs(float(y) - value) < 1e-6 for _x, y in points)


def length_factor(curves, speed=1.0):
    """Output length / input length for the given speed settings (<1 = shorter)."""
    f = curve_func(curves["speed"], curves.get("smooth", True), SPEED_MIN, SPEED_MAX)
    tau = np.linspace(0, 1, 2001)
    return float(np.mean(1.0 / (f(tau) * max(speed, 1e-3))))


def _stretch_variable(y, rate_fn, n_fft=2048, hop=512):
    """Phase-vocoder time stretch with a rate that changes along the signal.
    rate_fn(tau) = input frames consumed per output frame (tau = source 0..1).
    Returns (stretched signal, source position tau for every output sample)."""
    import librosa
    D = librosa.stft(y, n_fft=n_fft, hop_length=hop)
    F, T = D.shape
    steps = [0.0]
    while steps[-1] < T - 1:
        tau = steps[-1] / max(T - 1, 1)
        steps.append(steps[-1] + float(rate_fn(tau)))
    steps = np.array(steps[:-1])
    k = np.arange(F)
    phi_adv = 2.0 * np.pi * hop * k / n_fft
    Dp = np.pad(D, [(0, 0), (0, 2)], mode="constant")
    phase_acc = np.angle(D[:, 0])
    out = np.empty((F, len(steps)), dtype=np.complex128)
    for j, st in enumerate(steps):
        i = int(st)
        a = st - i
        c0, c1 = Dp[:, i], Dp[:, i + 1]
        mag = (1.0 - a) * np.abs(c0) + a * np.abs(c1)
        out[:, j] = mag * np.exp(1j * phase_acc)
        dphi = np.angle(c1) - np.angle(c0) - phi_adv
        dphi -= 2.0 * np.pi * np.round(dphi / (2.0 * np.pi))
        phase_acc = phase_acc + phi_adv + dphi
    y1 = librosa.istft(out, hop_length=hop, n_fft=n_fft)
    m = np.arange(len(y1))
    frame = np.clip(m / hop, 0, len(steps) - 1)
    tau_m = np.interp(frame, np.arange(len(steps)), steps) / max(T - 1, 1)
    return y1, np.clip(tau_m, 0.0, 1.0)


def _apply_curves(y, sr, speed, pitch, curves):
    sf = curve_func(curves["speed"], curves.get("smooth", True), SPEED_MIN, SPEED_MAX)
    pf = curve_func(curves["pitch"], curves.get("smooth", True), PITCH_MIN, PITCH_MAX)
    spd = lambda t: np.clip(speed * sf(t), 0.25, 4.0)
    rat = lambda t: 2.0 ** ((pitch + pf(t)) / 12.0)
    # stage 1: pitch-preserving stretch at speed/ratio; stage 2: resample at ratio
    y1, tau_m = _stretch_variable(y, lambda t: float(spd(t) / rat(t)))
    rho = rat(tau_m)
    t_cum = np.concatenate([[0.0], np.cumsum(1.0 / rho)])
    n_out = int(t_cum[-1])
    m_n = np.interp(np.arange(n_out), t_cum, np.arange(len(t_cum)))
    return np.interp(m_n, np.arange(len(y1)), y1).astype(np.float32)


# ── timeline helpers (used by the curve editor and the TTS tab) ──────────

def load_wav_mono(path):
    """(float32 mono samples, sample rate)"""
    import soundfile as sf
    y, sr = sf.read(path, dtype="float32", always_2d=True)
    return y.mean(axis=1).astype(np.float32), int(sr)


def write_wav(path, y, sr):
    import soundfile as sf
    sf.write(path, np.clip(y, -1.0, 1.0), int(sr), subtype="PCM_16")


def split_sentences(text, limit=260):
    """Split text into sentence units (one synthesis call each). Splits at
    . ! ? and line breaks; an over-long sentence is cut at a comma/space."""
    import re
    units = []
    for para in re.split(r"\n+", text or ""):
        for s in re.split(r"(?<=[.!?\u3002\uff01\uff1f])\s+", para.strip()):
            s = s.strip()
            while len(s) > limit:
                cut = max(s.rfind(", ", 0, limit), s.rfind("; ", 0, limit),
                          s.rfind(" ", 0, limit))
                cut = cut if cut > 40 else limit
                units.append(s[:cut + 1].strip())
                s = s[cut + 1:].strip()
            if s and re.search(r"\w", s):
                units.append(s)
    return units


def stitch(parts, sr, gap_s=0.18):
    """Join audio pieces with a short silence. Returns (audio, [(t0, t1)])
    where (t0, t1) is each piece's span in seconds."""
    gap = np.zeros(int(sr * gap_s), dtype=np.float32)
    out, spans, pos = [], [], 0
    for i, y in enumerate(parts):
        y = np.asarray(y, dtype=np.float32)
        spans.append((pos / sr, (pos + y.size) / sr))
        out.append(y)
        pos += y.size
        if i < len(parts) - 1:
            out.append(gap)
            pos += gap.size
    return (np.concatenate(out) if out else np.zeros(0, np.float32)), spans


def find_pauses(y, sr, min_gap=0.10, rel_thresh=0.04):
    """Centres (seconds) of quiet gaps between words/sentences - safe places
    to put an edit without cutting a word."""
    hop = max(1, int(sr * 0.01))
    n = y.size // hop
    if n < 3:
        return []
    rms = np.sqrt((y[:n * hop].reshape(n, hop) ** 2).mean(axis=1))
    quiet = rms < max(float(rms.max()) * rel_thresh, 1e-4)
    out, i = [], 0
    need = int(round(min_gap / 0.01))
    while i < n:
        if quiet[i]:
            j = i
            while j < n and quiet[j]:
                j += 1
            if j - i >= need and i > 3 and j < n - 3:     # skip the edges
                out.append(((i + j) / 2.0) * 0.01)
            i = j
        else:
            i += 1
    return out


def wave_peaks(y, i0, i1, ncols):
    """(min, max) per pixel column for samples [i0, i1)."""
    i0, i1 = max(0, int(i0)), min(y.size, int(i1))
    if i1 - i0 < 2 or ncols < 1:
        z = np.zeros(max(ncols, 1), dtype=np.float32)
        return z, z
    if i1 - i0 <= ncols:
        idx = (i0 + (np.arange(ncols) * (i1 - i0)) // ncols).astype(int)
        v = y[np.minimum(idx, y.size - 1)]
        return v, v
    idx = (i0 + (np.arange(ncols) * (i1 - i0)) // ncols).astype(int)
    seg = y[i0:i1]
    rel = idx - i0
    return np.minimum.reduceat(seg, rel), np.maximum.reduceat(seg, rel)


def _soft_limit(y, knee=0.9):
    """Keep boosted audio from clipping without undoing the boost."""
    a = np.abs(y)
    over = a > knee
    if np.any(over):
        w = 1.0 - knee
        y = y.copy()
        y[over] = np.sign(y[over]) * (knee + w * np.tanh((a[over] - knee) / w))
    return y


def formant_shift(y, sr, semitones, n_fft=2048, hop=512):
    """Move the formants (the voice's 'body' / apparent throat size) by
    `semitones` WITHOUT changing the pitch or the duration.

    Positive = formants up (smaller, lighter, "chipmunk-ish" body),
    negative = formants down (bigger, deeper body). Method: split each STFT
    frame into a smooth spectral envelope (cepstral liftering = the
    formants) and the fine structure (the pitch harmonics), warp ONLY the
    envelope along the frequency axis, keep the original phase so the
    harmonics - and so the pitch - stay where they were.
    """
    import librosa
    y = np.asarray(y, dtype=np.float32)
    if abs(semitones) < 0.05 or y.size < n_fft:
        return y
    f = 2.0 ** (float(semitones) / 12.0)
    S = librosa.stft(y, n_fft=n_fft, hop_length=hop)
    mag = np.abs(S)
    logm = np.log(mag + 1e-7)
    cep = np.fft.irfft(logm, n=n_fft, axis=0)
    L = max(8, int(sr / 450.0))              # keep quefrencies below ~f0 max
    lift = np.zeros(n_fft)
    lift[:L] = 1.0
    lift[-(L - 1):] = 1.0
    env = np.fft.rfft(cep * lift[:, None], axis=0).real
    K = env.shape[0]
    src = np.clip(np.arange(K) / f, 0.0, K - 1.0)
    i0 = np.floor(src).astype(int)
    i1 = np.minimum(i0 + 1, K - 1)
    w = (src - i0)[:, None]
    env2 = env[i0] * (1.0 - w) + env[i1] * w
    gain = np.exp(np.clip(env2 - env, -3.0, 3.0))      # at most +-26 dB
    S2 = (mag * gain) * np.exp(1j * np.angle(S))
    y2 = librosa.istft(S2, hop_length=hop, length=y.size).astype(np.float32)
    r_in = float(np.sqrt(np.mean(y * y)) + 1e-9)
    r_out = float(np.sqrt(np.mean(y2 * y2)) + 1e-9)
    return (y2 * min(max(r_in / r_out, 0.25), 4.0)).astype(np.float32)


def apply_fx(path, speed=1.0, pitch=0.0, curves=None, volume=1.0, depth=0.0):
    """Rewrite the WAV at `path`. Returns True if the file was modified."""
    speed = float(speed)
    pitch = float(pitch)
    volume = float(volume)
    depth = min(max(float(depth), DEPTH_MIN), DEPTH_MAX)
    vol_pts = (curves or {}).get("volume")
    vol_curve = bool(vol_pts) and not _is_flat(vol_pts, 1.0)
    tp_curves = bool(curves) and not (
        _is_flat(curves["speed"], 1.0) and _is_flat(curves["pitch"], 0.0))
    do_speed = abs(speed - 1.0) >= 0.01
    do_pitch = abs(pitch) >= 0.05
    do_vol = abs(volume - 1.0) >= 0.01
    do_depth = abs(depth) >= 0.05
    if not (tp_curves or vol_curve or do_speed or do_pitch or do_vol or do_depth):
        return False

    import librosa
    import soundfile as sf

    y, sr = librosa.load(path, sr=None, mono=True)
    if y.size == 0:
        return False
    if vol_curve:                        # gain follows the ORIGINAL speech
        vf = curve_func(vol_pts, curves.get("smooth", True), VOL_MIN, VOL_MAX)
        y = (y * vf(np.linspace(0.0, 1.0, y.size))).astype(np.float32)
    if do_vol:
        y = (y * np.float32(volume)).astype(np.float32)
    if tp_curves:
        y = _apply_curves(y, sr, speed, pitch, curves)
    else:
        if do_pitch:
            y = librosa.effects.pitch_shift(y, sr=sr, n_steps=pitch)
        if do_speed:
            y = librosa.effects.time_stretch(y, rate=speed)

    if do_depth:                         # last: moves formants, keeps pitch
        y = formant_shift(y, sr, depth)
    peak = float(np.max(np.abs(y))) if y.size else 0.0
    if vol_curve or do_vol:              # boosted: limit, don't rescale
        y = np.clip(_soft_limit(y), -1.0, 1.0)
    elif peak > 0.99:                    # avoid clipping after processing
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
