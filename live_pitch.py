"""Real-time pitch shifter for streaming audio (numpy only).

Phase-vocoder bin shifting (STFT, 4x overlap). Feed it consecutive blocks
of mono float32 audio; it returns the same number of samples per call,
delayed by a fixed latency. The pitch ratio can change on every call, so
a GUI slider can drive it live.

    ps = PitchShifter(sample_rate)
    out = ps.process(block, ratio)      # ratio 2**(semitones/12)

Quality: clean for about +/-5 semitones, increasingly "phasey" beyond.
It moves the whole spectrum (formants too), so large shifts change the
apparent size of the speaker as well as the pitch.
"""
import numpy as np


class PitchShifter:
    def __init__(self, sample_rate, fft_size=2048, osamp=4):
        self.sr = float(sample_rate)
        self.N = int(fft_size)
        self.osamp = int(osamp)
        self.hop = self.N // self.osamp
        self.H = self.N // 2 + 1
        n = np.arange(self.N)
        self.win = (0.5 - 0.5 * np.cos(2 * np.pi * n / self.N)).astype(np.float64)
        self.k = np.arange(self.H)
        self.freq_per_bin = self.sr / self.N
        self.expct = 2 * np.pi * self.hop / self.N
        self.inbuf = np.zeros(self.N)            # sliding analysis window
        self.outacc = np.zeros(self.N)           # overlap-add accumulator
        self.last_phase = np.zeros(self.H)
        self.sum_phase = np.zeros(self.H)
        self._inq = np.zeros(0)
        self._outq = np.zeros(self.hop)          # priming: never underflow
        # loudness follower (shifting loses some energy; see _level)
        self._lat_hops = self.N // self.hop
        self._in_hist = []
        self._ema_in = 0.0
        self._ema_out = 0.0
        self._gain = 1.0
        self._ema_a = 1.0 - np.exp(-self.hop / self.sr / 0.15)

    @property
    def latency_samples(self):
        return self.N - self.hop + self.hop

    def _frame(self, ratio):
        N, H, osamp = self.N, self.H, self.osamp
        spec = np.fft.rfft(self.inbuf * self.win)
        magn = 2.0 * np.abs(spec)
        phase = np.angle(spec)
        # --- analysis: true frequency of each bin
        d = phase - self.last_phase
        self.last_phase = phase
        d -= self.k * self.expct
        q = np.trunc(d / np.pi).astype(np.int64)
        q = np.where(q >= 0, q + (q & 1), q - (q & 1))
        d -= np.pi * q
        d = osamp * d / (2 * np.pi)
        ana_freq = self.k * self.freq_per_bin + d * self.freq_per_bin
        # --- pitch shift: move bins
        idx = (self.k * ratio).astype(np.int64)
        ok = idx < H
        syn_magn = np.bincount(idx[ok], weights=magn[ok], minlength=H)[:H]
        syn_freq = np.zeros(H)
        syn_freq[idx[ok]] = ana_freq[ok] * ratio
        # --- synthesis: accumulate phase
        t = syn_freq - self.k * self.freq_per_bin
        t = t / self.freq_per_bin
        t = 2 * np.pi * t / osamp + self.k * self.expct
        self.sum_phase += t
        out_spec = syn_magn * np.exp(1j * self.sum_phase)
        frame = np.fft.irfft(out_spec, n=N)
        self.outacc += self.win * frame * (4.0 / (3.0 * osamp))
        emit = self.outacc[: self.hop].copy()
        self.outacc[: -self.hop] = self.outacc[self.hop:]
        self.outacc[-self.hop:] = 0.0
        return emit

    def _level(self, emit, hop_in, ratio):
        """Slowly restore the loudness lost by bin shifting. The input energy
        is delayed by the shifter's latency so word onsets don't overshoot."""
        e_in = float(np.dot(hop_in, hop_in)) / len(hop_in)
        e_out = float(np.dot(emit, emit)) / len(emit)
        self._in_hist.append(e_in)
        if len(self._in_hist) <= self._lat_hops:
            return emit
        e_in_aligned = self._in_hist.pop(0)
        a = self._ema_a
        self._ema_in += a * (e_in_aligned - self._ema_in)
        self._ema_out += a * (e_out - self._ema_out)
        if abs(ratio - 1.0) < 0.005 or self._ema_out < 1e-9:
            target = 1.0
        else:
            target = float(np.clip(np.sqrt((self._ema_in + 1e-12) /
                                           (self._ema_out + 1e-12)), 0.7, 2.5))
        self._gain += 0.2 * (target - self._gain)
        return emit * self._gain

    def process(self, block, ratio=1.0):
        x = np.asarray(block, dtype=np.float64)
        L = len(x)
        self._inq = np.concatenate([self._inq, x])
        outs = [self._outq]
        while len(self._inq) >= self.hop:
            hop_in = self._inq[: self.hop]
            self.inbuf[: -self.hop] = self.inbuf[self.hop:]
            self.inbuf[-self.hop:] = hop_in
            self._inq = self._inq[self.hop:]
            outs.append(self._level(self._frame(float(ratio)), hop_in, float(ratio)))
        q = np.concatenate(outs)
        if len(q) < L:                           # should not happen; stay safe
            q = np.concatenate([q, np.zeros(L - len(q))])
        self._outq = q[L:]
        return q[:L].astype(np.float32)
