"""Draws the jpeg_is_king icon (icon.ico + icon.png) with Pillow. Run: python make_icon.py"""
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont

N = 1024
HERE = Path(__file__).resolve().parent
FONTS = ["Poppins-Bold.ttf", "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/segoeuib.ttf",
         "DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "Arial Bold.ttf"]
GOLD, GOLD_D, GOLD_L = (255, 200, 40), (214, 140, 10), (255, 236, 150)


def font(size):
    for f in FONTS:
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default()


def gradient(size, c1, c2):
    g = Image.new("RGB", (size, size))
    px = g.load()
    assert px is not None
    for y in range(size):
        for x in range(size):
            t = (x * 0.4 + y * 0.9) / (size * 1.3)
            px[x, y] = tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))
    return g


def squircle_mask(size, radius):
    m = Image.new("L", (size * 2, size * 2), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size * 2 - 1, size * 2 - 1), radius * 2, fill=255)
    return m.resize((size, size), Image.Resampling.LANCZOS)


def crown():
    """Gold crown with jewels, drawn at 2x then reduced."""
    S = 2
    W, H = 640 * S, 430 * S
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    base_y, top_y = H - 70 * S, 40 * S
    pts = [(30 * S, base_y), (10 * S, top_y + 60 * S), (165 * S, 230 * S), (320 * S, top_y),
           (475 * S, 230 * S), (630 * S, top_y + 60 * S), (610 * S, base_y)]
    d.polygon(pts, fill=GOLD)
    d.polygon([(30 * S, base_y), (10 * S, top_y + 60 * S), (165 * S, 230 * S), (210 * S, base_y)], fill=GOLD_L)
    d.polygon([(610 * S, base_y), (630 * S, top_y + 60 * S), (475 * S, 230 * S), (430 * S, base_y)], fill=GOLD_D)
    d.rounded_rectangle((20 * S, base_y - 10 * S, 620 * S, H - 10 * S), 40 * S, fill=GOLD_D)
    d.rounded_rectangle((20 * S, base_y - 10 * S, 620 * S, H - 40 * S), 30 * S, fill=GOLD)
    for x, y, r, col in ((320, top_y, 34, (239, 68, 68)), (10, top_y + 60, 28, (59, 130, 246)),
                         (630, top_y + 60, 28, (34, 197, 94))):
        d.ellipse(((x - r) * S, (y - r) * S, (x + r) * S, (y + r) * S), fill=col, outline=GOLD_D, width=6 * S)
    for x in (150, 320, 490):
        d.ellipse(((x - 24) * S, (base_y + 4 * S) - 24 * S + 4 * S, (x + 24) * S, (base_y + 4 * S) + 24 * S + 4 * S),
                  fill=(147, 51, 234) if x == 320 else (236, 72, 153))
    return im.resize((W // S, H // S), Image.Resampling.LANCZOS)


def sparkle(d, cx, cy, r, col=(255, 255, 255, 255)):
    pts = []
    for k in range(8):
        a = math.radians(45 * k)
        rr = r if k % 2 == 0 else r * 0.22
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    d.polygon(pts, fill=col)


def build():
    bg = gradient(N, (88, 28, 135), (236, 72, 153)).convert("RGBA")
    hl = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    ImageDraw.Draw(hl).ellipse((-N * 0.3, -N * 0.5, N * 0.9, N * 0.4), fill=(255, 255, 255, 40))
    bg = Image.alpha_composite(bg, hl.filter(ImageFilter.GaussianBlur(30)))

    # "JPG" lettering with a chunky shadow
    text = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    td = ImageDraw.Draw(text)
    f = font(400)
    box = td.textbbox((0, 0), "JPG", font=f)
    tw, th = box[2] - box[0], box[3] - box[1]
    pos = ((N - tw) // 2 - box[0], 540 - box[1])
    shadow = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).text((pos[0] + 0, pos[1] + 18), "JPG", font=f, fill=(40, 8, 70, 220))
    bg.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(6)))
    td.text(pos, "JPG", font=f, fill="white", stroke_width=6, stroke_fill=(60, 12, 100, 255))
    bg.alpha_composite(text)

    # crown, tilted jauntily, resting on the letters
    c = crown().rotate(11, resample=Image.Resampling.BICUBIC, expand=True)
    c = c.resize((int(c.width * 0.8), int(c.height * 0.8)), Image.Resampling.LANCZOS)
    cs = Image.new("RGBA", c.size, (0, 0, 0, 0))
    cs.paste((30, 5, 50, 150), mask=c.split()[3])
    cs = cs.filter(ImageFilter.GaussianBlur(14))
    px, py = (N - c.width) // 2 + 10, 150
    bg.alpha_composite(cs, (px, py + 16))
    bg.alpha_composite(c, (px, py))

    sp = Image.new("RGBA", (N * 2, N * 2), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sp)
    for x, y, r in ((880, 190, 70), (140, 330, 48), (900, 880, 52)):
        sparkle(sd, x * 2, y * 2, r * 2)
    bg.alpha_composite(sp.resize((N, N), Image.Resampling.LANCZOS))

    out = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    out.paste(bg, mask=squircle_mask(N, int(N * 0.225)))
    return out


if __name__ == "__main__":
    icon = build()
    icon.save(HERE / "icon.png")
    sizes = [(s, s) for s in (16, 24, 32, 48, 64, 128, 256)]
    icon.save(HERE / "icon.ico", sizes=sizes)
    print("wrote icon.png and icon.ico", [s[0] for s in sizes])
