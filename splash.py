"""Start-up animation: the JPEG crown slices every other format in half, then blows the room up.

`Scene` draws everything from a single time value (milliseconds), so it can be tested without a
window. `run_splash` shows it in a borderless window and hands over to the main window when done.
"""
from __future__ import annotations

import math
import random
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 760, 420
DURATION = 2900  # ms, including the final fade
FADE_START = 2600
T_SLASH, T_SPLIT = 560, 700

BG = (15, 17, 21)
GOLD = (255, 200, 40)
GOLD_L = (255, 236, 150)
MUTED = (154, 163, 181)
CHIPS = (("RAW", (239, 68, 68)), ("HEIC", (249, 115, 22)), ("PNG", (34, 197, 94)),
         ("TIFF", (6, 182, 212)), ("DNG", (139, 92, 246)), ("MOV", (236, 72, 153)))
CHIP_W, CHIP_H = 138, 58
ANGLE = math.radians(28)
FONT_FILES = ["Poppins-Bold.ttf", "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/segoeuib.ttf",
              "DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]


def hexc(c) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(v))) for v in c)


def lerp(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def ease_out(t: float) -> float:
    t = clamp01(t)
    return 1 - (1 - t) ** 3


def ease_in(t: float) -> float:
    t = clamp01(t)
    return t * t


def _font(size: int):
    for f in FONT_FILES:
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default()


def make_chip(label: str, color, k: float) -> Image.Image:
    """Rounded 'format badge' rendered at 3x then reduced, for smooth edges."""
    w, h, ss = int(CHIP_W * k), int(CHIP_H * k), 3
    im = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, w * ss - 1, h * ss - 1), 14 * k * ss, fill=color + (255,))
    d.rounded_rectangle((0, 0, w * ss - 1, h * ss * 0.5), 14 * k * ss, fill=tuple(min(255, c + 40) for c in color) + (255,))
    d.rectangle((0, h * ss * 0.3, w * ss, h * ss * 0.5), fill=tuple(min(255, c + 40) for c in color) + (255,))
    d.rounded_rectangle((0, h * ss * 0.5, w * ss - 1, h * ss - 1), 14 * k * ss, fill=color + (255,))
    d.rectangle((0, h * ss * 0.5, w * ss, h * ss * 0.7), fill=color + (255,))
    f = _font(int(26 * k * ss))
    box = d.textbbox((0, 0), label, font=f)
    d.text(((w * ss - (box[2] - box[0])) / 2 - box[0], (h * ss - (box[3] - box[1])) / 2 - box[1]),
           label, font=f, fill="white")
    return im.resize((w, h), Image.Resampling.LANCZOS)


def split_halves(chip: Image.Image, dx: float, dy: float, nx: float, ny: float):
    """Cut a chip along the line through its centre with direction (dx,dy); returns (side +n, side -n)."""
    w, h = chip.size
    cx, cy, L = w / 2, h / 2, max(w, h) * 2
    out = []
    for sgn in (1, -1):
        m = Image.new("L", chip.size, 0)
        ImageDraw.Draw(m).polygon([(cx - dx * L, cy - dy * L), (cx + dx * L, cy + dy * L),
                                   (cx + dx * L + sgn * nx * L, cy + dy * L + sgn * ny * L),
                                   (cx - dx * L + sgn * nx * L, cy - dy * L + sgn * ny * L)], fill=255)
        half = chip.copy()
        a = half.split()[3]
        from PIL import ImageChops
        half.putalpha(ImageChops.multiply(a, m))
        out.append(half)
    return out


class Scene:
    def __init__(self, canvas, photo, k: float | None, icon_path: Path | None, family: str = "Segoe UI",
                 bg=BG, seed: int = 7, size: tuple[float, float] | None = None):
        """canvas: tk.Canvas-like; photo: ImageTk.PhotoImage-like factory; size: the canvas size in pixels
        (the scene is scaled up to fill it); k: pixel scale, derived from size when None."""
        cw, ch = size if size else (W * (k or 1.0), H * (k or 1.0))
        if k is None:
            k = min(cw / W, ch / H)
        self.cw, self.ch = cw, ch
        self.fill = max(1.0, math.hypot(cw, ch) / math.hypot(W * k, H * k))  # effects reach the corners
        self.c, self.k, self.fam, self.bg = canvas, k, family, bg
        self.C = (cw / 2, ch * 200 / 420)
        self.d = (math.cos(ANGLE), -math.sin(ANGLE))
        self.n = (math.sin(ANGLE), math.cos(ANGLE))
        rnd = random.Random(seed)
        c = canvas
        self.flash = c.create_rectangle(0, 0, cw, ch, fill=hexc(bg), outline="")
        self.rays = [c.create_line(0, 0, 0, 0, fill=hexc(bg), width=3 * k, state="hidden", capstyle="round")
                     for _ in range(18)]
        self.rings = [c.create_oval(0, 0, 0, 0, outline=hexc(bg), width=2, state="hidden") for _ in range(3)]
        self.parts = []
        for _ in range(46):
            ang, sp = rnd.uniform(0, math.tau), rnd.uniform(140, 560)
            self.parts.append((c.create_oval(0, 0, 0, 0, fill=hexc(bg), outline="", state="hidden"),
                               ang, sp, rnd.uniform(3, 7), rnd.choice((GOLD, GOLD_L, (255, 255, 255), (255, 140, 40)))))
        # chips: full version + two halves each
        self.chips = []
        ts = (-300, -180, -60, 60, 180, 300)
        starts = ((-520, -80), (520, 120), (-420, 260), (480, -240), (-150, -330), (200, 380))
        for i, ((label, col), t0) in enumerate(zip(CHIPS, ts)):
            full = make_chip(label, col, k)
            a, b = split_halves(full, self.d[0], self.d[1], self.n[0], self.n[1])
            ph = [photo(x) for x in (full, a, b)]
            cx, cy = self.C[0] + self.d[0] * t0 * k, self.C[1] + self.d[1] * t0 * k
            ids = [c.create_image(cx, cy, image=ph[0], anchor="center"),
                   c.create_image(cx, cy, image=ph[1], anchor="center", state="hidden"),
                   c.create_image(cx, cy, image=ph[2], anchor="center", state="hidden")]
            self.chips.append(dict(pos=(cx, cy), ids=ids, ph=ph, start=starts[i], delay=70 * i, spin=rnd.uniform(.8, 1.3)))
        # slash glow
        self.slash = [c.create_line(0, 0, 0, 0, fill=hexc(bg), width=w * k, capstyle="round", state="hidden")
                      for w in (26, 11, 4)]
        # logo
        self.logo_steps = [round(0.2 + 0.08 * i, 2) for i in range(14)]
        self.logo_ph = []
        icon = Image.open(icon_path).convert("RGBA") if icon_path and Path(icon_path).exists() else None
        for s in self.logo_steps:
            side = max(8, int(220 * k * s))
            im = icon.resize((side, side), Image.Resampling.LANCZOS) if icon else Image.new("RGBA", (side, side), GOLD + (255,))
            self.logo_ph.append(photo(im))
        self.logo = c.create_image(self.C[0], self.C[1] - 20 * k, image=self.logo_ph[0], state="hidden")
        self.title = c.create_text(cw / 2, self.C[1] + 138 * k, text="JPEG IS KING", fill=hexc(bg), font=(family, int(30 * k), "bold"))
        self.sub = c.create_text(cw / 2, self.C[1] + 176 * k, text="no other formats were spared", fill=hexc(bg),
                                 font=(family, int(11 * k)))

    # -------------------------------------------------------------
    def update(self, t: float) -> None:
        c, k, bg = self.c, self.k, self.bg
        kf = k * self.fill  # distances that should reach the window edges
        cx0, cy0 = self.C
        dx, dy = self.d
        nx, ny = self.n
        # chips fly in, then split
        for ch in self.chips:
            fx, fy = ch["pos"]
            p = ease_out((t - ch["delay"]) / 480)
            ox, oy = ch["start"]
            x, y = fx + ox * kf * (1 - p), fy + oy * kf * (1 - p)
            if t < T_SPLIT:
                bob = math.sin(t / 140 + ch["delay"]) * 2 * k * ease_in((t - 480) / 100) if t > 480 else 0
                c.coords(ch["ids"][0], x, y + bob)
            else:
                tau = (t - T_SPLIT) / 1000
                s = (6 + 340 * ease_out(tau * 1.1)) * kf
                fall = 520 * tau * tau * kf
                for j, sg in ((1, 1), (2, -1)):
                    c.coords(ch["ids"][j], fx + nx * s * sg, fy + ny * s * sg + fall * (1.3 if sg > 0 else 0.8))
            hidden_full = "hidden" if t >= T_SPLIT else "normal"
            shown_half = "normal" if t >= T_SPLIT else "hidden"
            c.itemconfigure(ch["ids"][0], state=hidden_full)
            c.itemconfigure(ch["ids"][1], state=shown_half)
            c.itemconfigure(ch["ids"][2], state=shown_half)

        # the slash itself
        L = 560 * kf
        if t >= T_SLASH:
            p = ease_in((t - T_SLASH) / 140)
            x0, y0 = cx0 - dx * L, cy0 - dy * L
            x1, y1 = x0 + dx * 2 * L * p, y0 + dy * 2 * L * p
            fade = clamp01((t - T_SPLIT - 40) / 200)
            cols = (lerp(GOLD, bg, fade), lerp(GOLD_L, bg, fade), lerp((255, 255, 255), bg, fade))
            for item, col in zip(self.slash, cols):
                c.coords(item, x0, y0, x1, y1)
                c.itemconfigure(item, fill=hexc(col), state="hidden" if fade >= 1 else "normal")
        else:
            for item in self.slash:
                c.itemconfigure(item, state="hidden")

        # flash, rays, rings, sparks (all start at the split)
        tb = t - T_SPLIT
        c.itemconfigure(self.flash, fill=hexc(lerp((255, 232, 160), bg, tb / 260)) if tb >= 0 else hexc(bg))
        for i, r in enumerate(self.rays):
            if tb < 0:
                c.itemconfigure(r, state="hidden")
                continue
            tau = clamp01(tb / 700)
            ang = math.radians(i * 20 + 7)
            r_in = (120 + 280 * ease_out(tau)) * kf
            r_out = r_in + ((190 if i % 2 == 0 else 90) * (1 - tau) + 20) * kf
            c.coords(r, cx0 + math.cos(ang) * r_in, cy0 - 20 * k + math.sin(ang) * r_in,
                     cx0 + math.cos(ang) * r_out, cy0 - 20 * k + math.sin(ang) * r_out)
            c.itemconfigure(r, fill=hexc(lerp(GOLD_L, bg, tau)), width=max(1, (5 - 4 * tau) * k),
                            state="hidden" if tau >= 1 else "normal")
        for i, ring in enumerate(self.rings):
            tau = (tb - 110 * i) / 750
            if tau < 0 or tau >= 1:
                c.itemconfigure(ring, state="hidden")
                continue
            rad = (30 + 470 * ease_out(tau)) * kf
            c.coords(ring, cx0 - rad, cy0 - 20 * k - rad, cx0 + rad, cy0 - 20 * k + rad)
            c.itemconfigure(ring, outline=hexc(lerp(GOLD, bg, tau)), width=max(1, (10 * (1 - tau) + 1) * k),
                            state="normal")
        for item, ang, sp, size, col in self.parts:
            s = tb / 1000
            if s < 0 or s > 1.05:
                c.itemconfigure(item, state="hidden")
                continue
            x = cx0 + math.cos(ang) * sp * s * kf
            y = cy0 - 20 * k + math.sin(ang) * sp * s * kf + 260 * s * s * kf
            r = size * k * (1 - 0.6 * s)
            c.coords(item, x - r, y - r, x + r, y + r)
            c.itemconfigure(item, fill=hexc(lerp(col, bg, s * 0.95)), state="normal")

        # logo pops in with overshoot
        if t >= T_SPLIT + 60:
            u = (t - T_SPLIT - 60) / 420
            sc = 1.0 + 0.2 * math.sin(clamp01(u) * math.pi) if u < 1 else 1.0
            sc *= ease_out(u * 1.25) if u < 0.8 else 1.0
            sc = max(0.2, min(1.2, sc))
            idx = min(range(len(self.logo_steps)), key=lambda j: abs(self.logo_steps[j] - sc))
            c.itemconfigure(self.logo, image=self.logo_ph[idx], state="normal")
        else:
            c.itemconfigure(self.logo, state="hidden")
        c.itemconfigure(self.title, fill=hexc(lerp(bg, GOLD, (t - 1100) / 300)), state="normal" if t >= 1100 else "hidden")
        c.itemconfigure(self.sub, fill=hexc(lerp(bg, MUTED, (t - 1300) / 300)), state="normal" if t >= 1300 else "hidden")


def run_splash(root, scale: float, icon_path, family: str, bg_hex: str, line_hex: str, on_done) -> None:
    """Play the animation INSIDE the main window: a full-window cover that is lifted away at the end.
    No second window is ever created. Always calls on_done exactly once."""
    import tkinter as tk

    state = {"done": False, "cover": None}

    def finish(*_):
        if state["done"]:
            return
        state["done"] = True
        cover = state["cover"]
        if cover is not None:
            try:
                cover.destroy()
            except Exception:  # noqa: BLE001
                pass
        on_done()

    try:
        from PIL import ImageTk

        cover = tk.Frame(root, background=bg_hex, borderwidth=0, highlightthickness=0)
        state["cover"] = cover
        cover.place(x=0, y=0, relwidth=1, relheight=1)
        cover.lift()
        cv = tk.Canvas(cover, background=bg_hex, highlightthickness=0, borderwidth=0)
        cv.place(x=0, y=0, relwidth=1, relheight=1)  # the animation fills the whole window
        bg = tuple(int(bg_hex[i:i + 2], 16) for i in (1, 3, 5))
        for widget in (cover, cv):
            widget.bind("<Button-1>", finish)
        root.bind("<Key>", finish, add="+")
        cover.focus_set()

        def begin(event=None):
            """Build the scene once the window has its real size, then start the clock."""
            if state.get("scene") is not None or state["done"]:
                return
            cw, ch = cover.winfo_width(), cover.winfo_height()
            if cw < 200 or ch < 150:
                return
            state["scene"] = Scene(cv, ImageTk.PhotoImage, None, icon_path, family, bg, size=(cw, ch))
            state["t0"] = time.perf_counter()
            tick()

        def tick():
            if state["done"]:
                return
            t = (time.perf_counter() - state["t0"]) * 1000
            if t >= DURATION:
                finish()
                return
            try:
                state["scene"].update(t)
                if t > FADE_START:  # curtain: the cover slides up and reveals the app underneath
                    p = ease_in((t - FADE_START) / (DURATION - FADE_START))
                    cover.place_configure(relheight=max(0.001, 1 - p))
            except Exception:  # noqa: BLE001
                finish()
                return
            root.after(15, tick)

        cover.bind("<Configure>", begin)
        root.after(2500, lambda: finish() if state.get("scene") is None else None)  # never stay stuck
    except Exception:  # noqa: BLE001
        finish()
