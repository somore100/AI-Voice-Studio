"""Speed, pitch & volume curve editor (tkinter) with a zoomable timeline.

Top: a timeline showing the generated speech as a waveform, split into
sentences, with a time ruler. Below it: three curve canvases (speed, pitch,
volume) that share the timeline's zoom/scroll window, so a point sits exactly
under the word it affects.

  mouse wheel  zoom (around the pointer)      Shift+wheel / drag timeline  move
  double-click a sentence  zoom to it         middle-drag on a curve       move
  click  add a point   drag  move it   right-click / double-click  remove it
  Snap: points jump to sentence edges and quiet gaps between words, so an
  edit never cuts a word.

Curve x is always the position in the ORIGINAL speech, 0..1 (audio_fx.py), so
zooming only changes the view, never the stored curves:
    {"smooth": bool, "speed": [(x, mult)], "pitch": [(x, semitones)],
     "volume": [(x, gain)]}

open_editor(..., hooks=...) - `hooks` connects the editor to the app:
    get_ref()          -> (ref | None, status_text)
                          ref = {"path", "sentences": [(t0, t1, text)],
                                 "pauses": [seconds]}
    generate(done_cb)  start building the timeline; call done_cb() when done
    play()             play the unprocessed speech
    preview()          preview with the curves applied
"""
import bisect
import math
import tkinter as tk
from tkinter import ttk

import numpy as np

import audio_fx

W = 760
L, R = 54, 14
PLOT_W = W - L - R
TL_H = 104              # timeline canvas height
RULER_H, STRIP_H = 18, 14
H = 100                 # curve canvas height
T, B = 18, 6
PLOT_H = H - T - B
MINDX = 0.0003          # closest two points may get (fraction of the speech)
_NICE = [0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600]


class _Ctx:
    """The shared view window + timeline data."""

    def __init__(self):
        self.v0, self.v1 = 0.0, 1.0
        self.min_span = 0.02
        self.ref = None
        self.y = None
        self.sr = 1
        self.dur = 0.0
        self.snaps = []
        self.snap_on = None
        self.views = []
        self.sb = None
        self._wav_key = None

    # -- view
    def span(self):
        return self.v1 - self.v0

    def x2px(self, x):
        return L + (x - self.v0) / self.span() * PLOT_W

    def px2x(self, px):
        return min(max(self.v0 + (px - L) / PLOT_W * self.span(), 0.0), 1.0)

    def set_view(self, v0, v1, force=False):
        span = min(max(v1 - v0, self.min_span), 1.0)
        v0 = min(max(v0, 0.0), 1.0 - span)
        v1 = v0 + span
        if not force and abs(v0 - self.v0) < 1e-9 and abs(v1 - self.v1) < 1e-9:
            return
        self.v0, self.v1 = v0, v1
        if self.sb is not None:
            self.sb.set(v0, v1)
        for f in self.views:
            f()

    def zoom(self, factor, anchor_px):
        ax = self.px2x(anchor_px)
        span = self.span()
        new = min(max(span * factor, self.min_span), 1.0)
        v0 = ax - (ax - self.v0) * new / span
        self.set_view(v0, v0 + new)

    def pan(self, dx):
        self.set_view(self.v0 + dx, self.v1 + dx)

    def fit(self):
        self.set_view(0.0, 1.0)

    # -- timeline data
    def set_ref(self, ref):
        self.ref = ref
        if not ref:
            self.y, self.dur, self.snaps = None, 0.0, []
            self._wav_key = None
            self.min_span = 0.02
            return
        key = ref["path"]
        if key != self._wav_key:
            self.y, self.sr = audio_fx.load_wav_mono(ref["path"])
            self._wav_key = key
        self.dur = self.y.size / float(self.sr)
        pts = set()
        for t0, t1, _txt in ref["sentences"]:
            pts.add(round(t0 / self.dur, 6))
            pts.add(round(t1 / self.dur, 6))
        for p in ref.get("pauses", []):
            pts.add(round(p / self.dur, 6))
        self.snaps = sorted(p for p in pts if 0.0 < p < 1.0)
        self.min_span = max(0.5 / self.dur, 0.0005)

    def snap(self, x):
        if not (self.snaps and self.snap_on is not None and self.snap_on.get()):
            return x
        r = 7.0 / PLOT_W * self.span()
        i = bisect.bisect_left(self.snaps, x)
        best, bd = x, r
        for j in (i - 1, i):
            if 0 <= j < len(self.snaps) and abs(self.snaps[j] - x) <= bd:
                best, bd = self.snaps[j], abs(self.snaps[j] - x)
        return best

    # -- labels
    def fmt_x(self, x):
        if self.dur <= 0:
            return f"{x * 100:.0f}%"
        return self._fmt_t(x * self.dur)

    @staticmethod
    def _fmt_t(t):
        if t >= 60:
            m = int(t // 60)
            return f"{m}:{t - 60 * m:04.1f}"
        return f"{t:.2f}s" if t < 10 else f"{t:.1f}s"

    def ticks(self):
        """[(x, label)] visible ruler ticks."""
        out = []
        if self.dur > 0:
            span_s = self.span() * self.dur
            step = next((s for s in _NICE if s / span_s * PLOT_W >= 80), _NICE[-1])
            t = math.ceil(self.v0 * self.dur / step - 1e-9) * step
            while t <= self.v1 * self.dur + 1e-9:
                out.append((t / self.dur, self._fmt_t(t)))
                t += step
        else:
            span_p = self.span() * 100
            step = next((s for s in (1, 2, 5, 10, 20, 25, 50)
                         if s / span_p * PLOT_W >= 60), 50)
            p = math.ceil(self.v0 * 100 / step - 1e-9) * step
            while p <= self.v1 * 100 + 1e-9:
                out.append((p / 100.0, f"{p:g}%"))
                p += step
        return out


def _bind_nav(cv, ctx, left_pan=False):
    """Wheel = zoom, Shift+wheel = move, middle-drag (and optionally
    left-drag) = move."""
    def wheel(direction, e):
        if e.state & 0x1:
            ctx.pan(-direction * 0.15 * ctx.span())
        else:
            ctx.zoom(0.8 if direction > 0 else 1.25, e.x)
    cv.bind("<MouseWheel>", lambda e: wheel(1 if e.delta > 0 else -1, e))
    cv.bind("<Button-4>", lambda e: wheel(1, e))
    cv.bind("<Button-5>", lambda e: wheel(-1, e))
    st = {"x": None, "v0": 0.0}

    def down(e):
        st["x"], st["v0"] = e.x, ctx.v0

    def move(e):
        if st["x"] is None:
            return
        span = ctx.span()
        v0 = st["v0"] - (e.x - st["x"]) / PLOT_W * span
        ctx.set_view(v0, v0 + span)

    def up(_e):
        st["x"] = None
    cv.bind("<ButtonPress-2>", down)
    cv.bind("<B2-Motion>", move)
    cv.bind("<ButtonRelease-2>", up)
    if left_pan:
        cv.bind("<ButtonPress-1>", down)
        cv.bind("<B1-Motion>", move)
        cv.bind("<ButtonRelease-1>", up)


class _Timeline:
    def __init__(self, parent, ctx, colors):
        self.ctx, self.c = ctx, colors
        self.cv = tk.Canvas(parent, width=W, height=TL_H, bg=colors["bg"],
                            highlightthickness=1, highlightbackground=colors["border"])
        self.cv.pack()
        _bind_nav(self.cv, ctx, left_pan=True)
        self.cv.bind("<Double-Button-1>", self._dbl)
        self.cv.bind("<Motion>", self._hover)
        self.draw()

    def _dbl(self, e):
        ctx = self.ctx
        if not ctx.ref:
            return ctx.fit()
        x = ctx.px2x(e.x)
        for t0, t1, _t in ctx.ref["sentences"]:
            if t0 / ctx.dur <= x <= t1 / ctx.dur:
                pad = (t1 - t0) / ctx.dur * 0.05
                ctx.set_view(t0 / ctx.dur - pad, t1 / ctx.dur + pad)
                return
        ctx.fit()

    def _hover(self, e):
        self.cv.configure(cursor="fleur")

    def draw(self):
        cv, c, ctx = self.cv, self.c, self.ctx
        cv.delete("all")
        top = RULER_H + STRIP_H + 2
        bot = TL_H - 4
        mid = (top + bot) / 2.0
        if ctx.ref:
            for k, (t0, t1, txt) in enumerate(ctx.ref["sentences"]):
                a, b = ctx.x2px(t0 / ctx.dur), ctx.x2px(t1 / ctx.dur)
                if b < L or a > L + PLOT_W:
                    continue
                a2, b2 = max(a, L), min(b, L + PLOT_W)
                cv.create_rectangle(a2, RULER_H, b2, bot,
                                    fill=c["surface"] if k % 2 else c["card"], outline="")
                chars = int((b2 - a2 - 8) / 6.2)
                if chars >= 4:
                    label = txt if len(txt) <= chars else txt[:chars - 1] + "\u2026"
                    cv.create_text(a2 + 4, RULER_H + 2, text=label, anchor="nw",
                                   fill=c["fg"], font=("Segoe UI", 8))
                if a >= L:
                    cv.create_line(a, RULER_H, a, bot, fill=c["dim"])
            ncols = PLOT_W
            n = ctx.y.size
            mn, mx = audio_fx.wave_peaks(ctx.y, ctx.v0 * n, ctx.v1 * n, ncols)
            scale = (bot - top) / 2.0 * 0.95
            peak = max(float(np.abs(ctx.y).max()), 1e-6)
            up = [(L + i, mid - float(mx[i]) / peak * scale) for i in range(len(mx))]
            dn = [(L + i, mid - float(mn[i]) / peak * scale) for i in range(len(mn) - 1, -1, -1)]
            pts = [v for p in up + dn for v in p]
            if len(pts) >= 6:
                cv.create_polygon(*pts, fill=c["accent"], outline="")
            for p in ctx.ref.get("pauses", []):
                px = ctx.x2px(p / ctx.dur)
                if L <= px <= L + PLOT_W:
                    cv.create_line(px, bot - 7, px, bot, fill=c["fg"])
        else:
            cv.create_text(L + PLOT_W / 2, (RULER_H + TL_H) / 2,
                           text="No timeline yet - press \"Generate timeline from text\"",
                           fill=c["dim"], font=("Segoe UI", 9))
        cv.create_rectangle(0, 0, W, RULER_H, fill=c["card"], outline="")
        for x, lab in ctx.ticks():
            px = ctx.x2px(x)
            if px < L - 1 or px > L + PLOT_W + 1:
                continue
            cv.create_line(px, 0, px, RULER_H - 4, fill=c["dim"])
            cv.create_text(px + 3, 1, text=lab, anchor="nw", fill=c["dim"],
                           font=("Segoe UI", 8))
        cv.create_text(L - 6, mid, text="speech", anchor="e", fill=c["dim"],
                       font=("Segoe UI", 8))


class _Panel:
    def __init__(self, parent, title, state, key, colors, ctx, on_change):
        self.state, self.key, self.c, self.on_change = state, key, colors, on_change
        self.kind, self.title, self.ctx = key, title, ctx
        self.sel = None
        self.cv = tk.Canvas(parent, width=W, height=H, bg=colors["bg"],
                            highlightthickness=1, highlightbackground=colors["border"])
        self.cv.pack(pady=(4, 0))
        self.cv.bind("<ButtonPress-1>", self._press)
        self.cv.bind("<B1-Motion>", self._drag)
        self.cv.bind("<ButtonRelease-1>", self._release)
        self.cv.bind("<Button-3>", self._remove)
        self.cv.bind("<Double-Button-1>", self._remove)
        self.cv.bind("<Motion>", self._hover)
        _bind_nav(self.cv, ctx)
        self.draw()

    # ---- value <-> pixel
    def x2px(self, x):
        return self.ctx.x2px(x)

    def px2x(self, px):
        return self.ctx.px2x(px)

    def v2py(self, v):
        if self.kind == "speed":
            yn = 0.5 - 0.5 * math.log2(min(max(v, 0.5), 2.0))
        elif self.kind == "volume":
            yn = 1.0 - min(max(v, 0.0), 2.0) / 2.0
        else:
            yn = 0.5 - min(max(v, -12.0), 12.0) / 24.0
        return T + yn * PLOT_H

    def py2v(self, py):
        yn = min(max((py - T) / PLOT_H, 0.0), 1.0)
        if abs(yn - 0.5) * PLOT_H < 6:             # snap to the centre line
            yn = 0.5
        if self.kind == "speed":
            return 2.0 ** (1.0 - 2.0 * yn)
        if self.kind == "volume":
            return 2.0 - 2.0 * yn
        return 12.0 - 24.0 * yn

    def fmt(self, v):
        if self.kind == "speed":
            return f"{v:.2f}x"
        return f"{v * 100:.0f}%" if self.kind == "volume" else f"{v:+.1f} st"

    # ---- drawing
    def draw(self):
        cv, c, ctx = self.cv, self.c, self.ctx
        cv.delete("all")
        labels = {"speed": ["2.0x", "1.4x", "1.0x", "0.7x", "0.5x"],
                  "volume": ["200%", "150%", "100%", "50%", "0%"],
                  }.get(self.kind, ["+12", "+6", "0", "-6", "-12"])
        for i, lab in enumerate(labels):
            y = T + i * PLOT_H / 4
            cv.create_line(L, y, L + PLOT_W, y, fill=c["border"] if i != 2 else c["dim"],
                           dash=(2, 3) if i != 2 else ())
            cv.create_text(L - 6, y, text=lab, anchor="e", fill=c["dim"], font=("Segoe UI", 8))
        for x, _lab in ctx.ticks():
            px = self.x2px(x)
            if L <= px <= L + PLOT_W:
                cv.create_line(px, T, px, T + PLOT_H, fill=c["border"], dash=(2, 3))
        if ctx.ref:
            for t0, _t1, _txt in ctx.ref["sentences"][1:]:
                px = self.x2px(t0 / ctx.dur)
                if L <= px <= L + PLOT_W:
                    cv.create_line(px, T, px, T + PLOT_H, fill=c["dim"])
        cv.create_text(L + 4, 3, text=self.title, anchor="nw", fill=c["accent"],
                       font=("Segoe UI", 9, "bold"))
        pts = self.state[self.key]
        lo, hi = {"speed": (0.5, 2.0), "volume": (0.0, 2.0)}.get(self.kind, (-12.0, 12.0))
        f = audio_fx.curve_func(pts, self.state.get("smooth", True), lo, hi)
        n = 240
        xs = [ctx.v0 + ctx.span() * i / n for i in range(n + 1)]
        xs += [x for x, _v in pts if ctx.v0 < x < ctx.v1]
        xs.sort()
        line = []
        for x in xs:
            line += [self.x2px(x), self.v2py(float(f(x)))]
        cv.create_line(*line, fill=c["accent"], width=2, smooth=False)
        for i, (x, v) in enumerate(pts):
            px, py = self.x2px(x), self.v2py(v)
            if px < L - 8 or px > L + PLOT_W + 8:
                continue
            r = 7 if i == self.sel else 5
            cv.create_oval(px - r, py - r, px + r, py + r, fill=c["accent"],
                           outline=c["fg"], width=2 if i == self.sel else 1)

    # ---- mouse
    def _nearest(self, ex, ey, radius=11):
        best, bd = None, radius
        for i, (x, v) in enumerate(self.state[self.key]):
            d = math.hypot(self.x2px(x) - ex, self.v2py(v) - ey)
            if d <= bd:
                best, bd = i, d
        return best

    def _press(self, e):
        pts = self.state[self.key]
        i = self._nearest(e.x, e.y)
        if i is None:
            if not (L - 4 <= e.x <= L + PLOT_W + 4 and T - 4 <= e.y <= T + PLOT_H + 4):
                return
            x = min(max(self.ctx.snap(self.px2x(e.x)), MINDX), 1.0 - MINDX)
            near = [k for k, p in enumerate(pts) if abs(p[0] - x) < MINDX]
            if near:
                i = near[0]
            else:
                pts.append((x, self.py2v(e.y)))
                pts.sort(key=lambda p: p[0])
                i = min(range(len(pts)), key=lambda k: abs(pts[k][0] - x))
        self.sel = i
        self._drag(e)

    def _drag(self, e):
        if self.sel is None:
            return
        pts = self.state[self.key]
        i = self.sel
        x, _v = pts[i]
        if 0 < i < len(pts) - 1:
            x = min(max(self.ctx.snap(self.px2x(e.x)), pts[i - 1][0] + MINDX),
                    pts[i + 1][0] - MINDX)
        pts[i] = (x, self.py2v(e.y))
        self.draw()
        self.cv.create_text(L + PLOT_W - 4, 3, anchor="ne", fill=self.c["fg"],
                            font=("Segoe UI", 9, "bold"),
                            text=f"{self.ctx.fmt_x(x)}   {self.fmt(pts[i][1])}")
        self.on_change()

    def _release(self, _e):
        self.sel = None
        self.draw()
        self.on_change()

    def _remove(self, e):
        pts = self.state[self.key]
        i = self._nearest(e.x, e.y)
        if i is not None and 0 < i < len(pts) - 1:
            del pts[i]
            self.sel = None
            self.draw()
            self.on_change()

    def _hover(self, e):
        if self.sel is not None:
            return
        i = self._nearest(e.x, e.y)
        self.cv.configure(cursor="hand2" if i is not None else "crosshair")

    def reset(self):
        d = 0.0 if self.kind == "pitch" else 1.0
        self.state[self.key][:] = [(0.0, d), (1.0, d)]
        self.sel = None
        self.draw()
        self.on_change()


def open_editor(root, state, use_var, colors, hooks=None):
    """Open (or raise) the editor window. `use_var` is a tk.BooleanVar."""
    hooks = hooks or {}
    win = getattr(root, "_curve_win", None)
    if win is not None and win.winfo_exists():
        win.deiconify()
        win.lift()
        if hasattr(win, "_refresh"):
            win._refresh()
        return win
    win = tk.Toplevel(root)
    root._curve_win = win
    win.title("Speed, Pitch & Volume Curves")
    win.configure(bg=colors["card"])
    win.resizable(False, False)
    body = tk.Frame(win, bg=colors["card"], padx=12, pady=8)
    body.pack()
    tk.Label(body, bg=colors["card"], fg=colors["dim"], font=("Segoe UI", 9), justify="left",
             text="Wheel = zoom  -  Shift+wheel or drag the timeline = move  -  double-click a "
                  "sentence = zoom to it\nClick = add a point  -  drag = move  -  right-click or "
                  "double-click a point = remove.  Curves REPLACE the sliders."
             ).pack(anchor="w", pady=(0, 4))

    ctx = _Ctx()
    ctx.snap_on = tk.BooleanVar(value=True)
    info = tk.Label(body, bg=colors["card"], fg=colors["fg"], font=("Segoe UI", 9, "bold"))
    _ready = [False]

    def changed():
        if _ready[0] and not use_var.get():
            use_var.set(True)  # editing a curve = you want it applied
        k = audio_fx.length_factor(state)
        word = "shorter" if k < 0.995 else "longer" if k > 1.005 else "same length"
        info.config(text=f"Overall length: x{k:.2f} ({word})")

    tl = _Timeline(body, ctx, colors)
    sp = _Panel(body, "Speed   (up = faster)", state, "speed", colors, ctx, changed)
    pp = _Panel(body, "Pitch   (up = higher)", state, "pitch", colors, ctx, changed)
    vp = _Panel(body, "Volume   (up = louder)", state, "volume", colors, ctx, changed)
    ctx.views = [tl.draw, sp.draw, pp.draw, vp.draw]

    def sb_cmd(*a):
        if a[0] == "moveto":
            v0 = float(a[1])
            ctx.set_view(v0, v0 + ctx.span())
        elif a[0] == "scroll":
            ctx.pan(int(a[1]) * ctx.span() * (0.9 if a[2] == "pages" else 0.1))
    ctx.sb = tk.Scrollbar(body, orient="horizontal", command=sb_cmd, width=12)
    ctx.sb.pack(fill="x", pady=(4, 0))
    ctx.sb.set(0.0, 1.0)

    def btn(parent, text, cmd, **kw):
        b = tk.Button(parent, text=text, command=cmd, bg=colors["surface"], fg=colors["fg"],
                      relief="flat", bd=0, padx=kw.pop("padx", 10), pady=3, cursor="hand2",
                      font=("Segoe UI", 9))
        b.pack(side="left", padx=kw.pop("gap", 3))
        return b

    # timeline row
    trow = tk.Frame(body, bg=colors["card"])
    trow.pack(fill="x", pady=(6, 0))
    status = tk.Label(trow, bg=colors["card"], fg=colors["dim"], font=("Segoe UI", 9))

    def refresh():
        ref, text = hooks["get_ref"]() if "get_ref" in hooks else (None, "")
        ctx.set_ref(ref)
        status.config(text=text)
        ctx.set_view(ctx.v0, ctx.v1, force=True)

    def generate():
        if "generate" not in hooks:
            return
        status.config(text="Generating timeline...", fg=colors["accent"])
        hooks["generate"](lambda: (win.winfo_exists() and (refresh(), ctx.fit())))

    btn(trow, "Generate timeline from text", generate, padx=12)
    btn(trow, "-", lambda: ctx.zoom(1.25, L + PLOT_W / 2), padx=9, gap=(10, 2))
    btn(trow, "+", lambda: ctx.zoom(0.8, L + PLOT_W / 2), padx=9)
    btn(trow, "Fit", ctx.fit, padx=9)
    ttk.Checkbutton(trow, text="Snap to pauses", variable=ctx.snap_on).pack(side="left", padx=10)
    status.pack(side="left", padx=4)

    row = tk.Frame(body, bg=colors["card"])
    row.pack(fill="x", pady=(8, 0))
    smooth = tk.BooleanVar(value=state.get("smooth", True))

    def set_smooth(*_):
        state["smooth"] = bool(smooth.get())
        sp.draw()
        pp.draw()
        vp.draw()
        changed()
    smooth.trace_add("write", set_smooth)
    ttk.Checkbutton(row, text="Smooth curves", variable=smooth).pack(side="left", padx=(0, 14))
    ttk.Radiobutton(row, text="Use sliders", variable=use_var,
                    value=False).pack(side="left", padx=(0, 8))
    ttk.Radiobutton(row, text="Use curves", variable=use_var,
                    value=True).pack(side="left")
    info.pack(anchor="w", pady=(6, 0))

    btns = tk.Frame(body, bg=colors["card"])
    btns.pack(fill="x", pady=(8, 0))
    if "play" in hooks:
        btn(btns, "Play original", hooks["play"])

    def preview():
        use_var.set(True)
        hooks["preview"]()
    if "preview" in hooks:
        btn(btns, "Preview with curves", preview)
    for text, cmd in (("Close", win.destroy), ("Reset volume", vp.reset),
                      ("Reset pitch", pp.reset), ("Reset speed", sp.reset)):
        b = tk.Button(btns, text=text, command=cmd, bg=colors["surface"], fg=colors["fg"],
                      relief="flat", bd=0, padx=10, pady=3, cursor="hand2",
                      font=("Segoe UI", 9))
        b.pack(side="right", padx=3)

    win._refresh = refresh
    win.bind("<FocusIn>", lambda e: refresh() if e.widget is win else None)
    refresh()
    changed()
    _ready[0] = True
    return win
