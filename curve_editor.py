"""Speed & pitch curve editor (tkinter), CapCut-style.

Two canvases over the speech timeline (left = start, right = end of the
original speech). Click empty space to add a point, drag to move, right-click
or double-click a point to remove it. End points only move up/down. Points
snap to the centre line (1x / 0 st) when you get close.
The curves are stored in `state` (a plain dict shared with the app):
    {"smooth": bool, "speed": [(x, mult)], "pitch": [(x, semitones)]}
"""
import math
import tkinter as tk
from tkinter import ttk

import audio_fx

W, H = 640, 190
L, R, T, B = 54, 14, 12, 24
PLOT_W, PLOT_H = W - L - R, H - T - B


class _Panel:
    def __init__(self, parent, title, state, key, colors, on_change):
        self.state, self.key, self.c, self.on_change = state, key, colors, on_change
        self.kind = key
        self.sel = None
        tk.Label(parent, text=title, bg=colors["card"], fg=colors["accent"],
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(8, 2))
        self.cv = tk.Canvas(parent, width=W, height=H, bg=colors["bg"],
                            highlightthickness=1, highlightbackground=colors["border"])
        self.cv.pack()
        self.cv.bind("<ButtonPress-1>", self._press)
        self.cv.bind("<B1-Motion>", self._drag)
        self.cv.bind("<ButtonRelease-1>", self._release)
        self.cv.bind("<Button-3>", self._remove)
        self.cv.bind("<Double-Button-1>", self._remove)
        self.cv.bind("<Motion>", self._hover)
        self.draw()

    # ---- value <-> pixel
    def x2px(self, x):
        return L + x * PLOT_W

    def px2x(self, px):
        return min(max((px - L) / PLOT_W, 0.0), 1.0)

    def v2py(self, v):
        if self.kind == "speed":
            yn = 0.5 - 0.5 * math.log2(min(max(v, 0.5), 2.0))
        else:
            yn = 0.5 - min(max(v, -12.0), 12.0) / 24.0
        return T + yn * PLOT_H

    def py2v(self, py):
        yn = min(max((py - T) / PLOT_H, 0.0), 1.0)
        if abs(yn - 0.5) * PLOT_H < 7:             # snap to the centre line
            yn = 0.5
        return 2.0 ** (1.0 - 2.0 * yn) if self.kind == "speed" else 12.0 - 24.0 * yn

    def fmt(self, v):
        return f"{v:.2f}x" if self.kind == "speed" else f"{v:+.1f} st"

    # ---- drawing
    def draw(self):
        cv, c = self.cv, self.c
        cv.delete("all")
        labels = (["2.0x", "1.4x", "1.0x", "0.7x", "0.5x"] if self.kind == "speed"
                  else ["+12", "+6", "0", "-6", "-12"])
        for i, lab in enumerate(labels):
            y = T + i * PLOT_H / 4
            cv.create_line(L, y, L + PLOT_W, y, fill=c["border"] if i != 2 else c["dim"],
                           dash=(2, 3) if i != 2 else ())
            cv.create_text(L - 6, y, text=lab, anchor="e", fill=c["dim"], font=("Segoe UI", 8))
        for i, lab in enumerate(["start", "25%", "50%", "75%", "end"]):
            x = L + i * PLOT_W / 4
            cv.create_line(x, T, x, T + PLOT_H, fill=c["border"], dash=(2, 3))
            cv.create_text(x, T + PLOT_H + 11, text=lab, fill=c["dim"], font=("Segoe UI", 8))
        pts = self.state[self.key]
        lo, hi = (0.5, 2.0) if self.kind == "speed" else (-12.0, 12.0)
        f = audio_fx.curve_func(pts, self.state.get("smooth", True), lo, hi)
        xs = [i / 240.0 for i in range(241)]
        line = []
        for x in xs:
            line += [self.x2px(x), self.v2py(float(f(x)))]
        cv.create_line(*line, fill=c["accent"], width=2, smooth=False)
        for i, (x, v) in enumerate(pts):
            px, py = self.x2px(x), self.v2py(v)
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
        i = self._nearest(e.x, e.y)
        pts = self.state[self.key]
        if i is None:
            if not (L - 4 <= e.x <= L + PLOT_W + 4 and T - 4 <= e.y <= T + PLOT_H + 4):
                return
            x = min(max(self.px2x(e.x), 0.01), 0.99)
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
            x = min(max(self.px2x(e.x), pts[i - 1][0] + 0.01), pts[i + 1][0] - 0.01)
        pts[i] = (x, self.py2v(e.y))
        self.draw()
        self.cv.create_text(L + PLOT_W - 4, T + 10, anchor="e", fill=self.c["fg"],
                            font=("Segoe UI", 9, "bold"),
                            text=f"{x * 100:.0f}%  {self.fmt(pts[i][1])}")
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
        self.state[self.key][:] = [(0.0, 1.0 if self.kind == "speed" else 0.0),
                                   (1.0, 1.0 if self.kind == "speed" else 0.0)]
        self.sel = None
        self.draw()
        self.on_change()


def open_editor(root, state, use_var, colors):
    """Open (or raise) the editor window. `use_var` is a tk.BooleanVar."""
    win = getattr(root, "_curve_win", None)
    if win is not None and win.winfo_exists():
        win.deiconify()
        win.lift()
        return win
    win = tk.Toplevel(root)
    root._curve_win = win
    win.title("Speed & Pitch Curves")
    win.configure(bg=colors["card"])
    win.resizable(False, False)
    body = tk.Frame(win, bg=colors["card"], padx=12, pady=10)
    body.pack()
    tk.Label(body, bg=colors["card"], fg=colors["dim"], font=("Segoe UI", 9), justify="left",
             text="Click to add a point  -  drag to move  -  right-click or double-click a "
                  "point to remove it.\nThe curves follow your speech from start to end. "
                  "Slider values combine with the curves.").pack(anchor="w")
    info = tk.Label(body, bg=colors["card"], fg=colors["fg"], font=("Segoe UI", 9, "bold"))

    def changed():
        k = audio_fx.length_factor(state)
        word = "shorter" if k < 0.995 else "longer" if k > 1.005 else "same length"
        info.config(text=f"Overall length: x{k:.2f} ({word})")

    sp = _Panel(body, "Speed   (up = faster)", state, "speed", colors, changed)
    pp = _Panel(body, "Pitch   (up = higher)", state, "pitch", colors, changed)
    row = tk.Frame(body, bg=colors["card"])
    row.pack(fill="x", pady=(10, 0))
    smooth = tk.BooleanVar(value=state.get("smooth", True))

    def set_smooth(*_):
        state["smooth"] = bool(smooth.get())
        sp.draw()
        pp.draw()
        changed()
    smooth.trace_add("write", set_smooth)
    ttk.Checkbutton(row, text="Smooth curves", variable=smooth).pack(side="left", padx=(0, 14))
    ttk.Checkbutton(row, text="Use curves on Preview / Save audio",
                    variable=use_var).pack(side="left")
    info.pack(anchor="w", pady=(6, 0))
    btns = tk.Frame(body, bg=colors["card"])
    btns.pack(anchor="e", pady=(8, 0))
    for text, cmd in (("Reset speed", sp.reset), ("Reset pitch", pp.reset),
                      ("Close", win.destroy)):
        tk.Button(btns, text=text, command=cmd, bg=colors["surface"], fg=colors["fg"],
                  relief="flat", bd=0, padx=12, pady=4, cursor="hand2",
                  font=("Segoe UI", 9)).pack(side="left", padx=4)
    changed()
    return win
