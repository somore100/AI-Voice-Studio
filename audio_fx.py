"""Post-processing for synthesized speech: speed and pitch, constant or
following curves drawn over the speech.

Works on any engine's WAV output, in place. Needs librosa + soundfile (both
already installed as coqui-tts dependencies); scipy is used for smooth
curves when available.

apply_fx(path, speed, pitch, volume=1.0)        constant speed / pitch / volume
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


def _soft_limit(y, knee=0.9):
    """Keep boosted audio from clipping without undoing the boost."""
    a = np.abs(y)
    over = a > knee
    if np.any(over):
        w = 1.0 - knee
        y = y.copy()
        y[over] = np.sign(y[over]) * (knee + w * np.tanh((a[over] - knee) / w))
    return y


def apply_fx(path, speed=1.0, pitch=0.0, curves=None, volume=1.0):
    """Rewrite the WAV at `path`. Returns True if the file was modified."""
    speed = float(speed)
    pitch = float(pitch)
    volume = float(volume)
    vol_pts = (curves or {}).get("volume")
    vol_curve = bool(vol_pts) and not _is_flat(vol_pts, 1.0)
    tp_curves = bool(curves) and not (
        _is_flat(curves["speed"], 1.0) and _is_flat(curves["pitch"], 0.0))
    do_speed = abs(speed - 1.0) >= 0.01
    do_pitch = abs(pitch) >= 0.05
    do_vol = abs(volume - 1.0) >= 0.01
    if not (tp_curves or vol_curve or do_speed or do_pitch or do_vol):
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
