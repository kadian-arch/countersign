"""Draws the site's icon and its share image, so they can be remade instead of kept as opaque files.

    python scripts/make_brand.py

Writes src/countersign/static/brand/: favicon.svg, favicon.ico, apple-touch-icon.png and og.png (1200x630, the picture
a chat or social site shows when the address is shared). Needs Pillow and a bold sans font from the system.
"""
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).resolve().parents[1] / "src" / "countersign" / "static" / "brand"
CYAN, BLUE, VIOLET = (47, 217, 255), (106, 130, 255), (200, 102, 255)
BG = (4, 5, 13)
INK, MUTED, FAINT = (240, 242, 255), (163, 172, 214), (103, 112, 160)
ALLOW, HOLD, REFUSE = (61, 245, 196), (255, 201, 77), (255, 95, 132)
FONTS = {"bold": ["segoeuib.ttf", "bahnschrift.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"],
         "text": ["segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"], "semi": ["seguisb.ttf", "segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"]}

SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#2fd9ff"/><stop offset=".5" stop-color="#6a82ff"/><stop offset="1" stop-color="#c866ff"/></linearGradient></defs>
<rect width="40" height="40" rx="9" fill="#070a1e"/>
<circle cx="20" cy="20" r="14.5" fill="none" stroke="url(#g)" stroke-width="2.6"/>
<path d="M12.6 20.9 L17.7 25.6 L27.6 14.2" fill="none" stroke="url(#g)" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
"""


def font(kind: str, size: int):
    for name in FONTS[kind]:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    sys.exit(f"no {kind} font found, install one of {FONTS[kind]}")


def gradient(size: int):
    """Cyan to blue to violet along the diagonal."""
    img = Image.new("RGB", (size, size))
    px = img.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * (size - 1))
            a, b, u = (CYAN, BLUE, t * 2) if t < .5 else (BLUE, VIOLET, (t - .5) * 2)
            px[x, y] = tuple(round(a[i] + (b[i] - a[i]) * u) for i in range(3))
    return img


def mark(size: int, scale: float = 1.0) -> Image.Image:
    """The ring with a tick, on a transparent square. scale is how much of the square the ring uses."""
    big = size * 4
    unit = big / 40 * scale
    off = big * (1 - scale) / 2
    mask = Image.new("L", (big, big), 0)
    d = ImageDraw.Draw(mask)
    p = lambda x, y: (off + x * unit, off + y * unit)
    (x0, y0), (x1, y1) = p(20 - 14.5, 20 - 14.5), p(20 + 14.5, 20 + 14.5)
    d.ellipse([x0, y0, x1, y1], outline=255, width=round(2.6 * unit))
    pts = [p(12.6, 20.9), p(17.7, 25.6), p(27.6, 14.2)]
    w = round(3.2 * unit)
    d.line(pts, fill=255, width=w, joint="curve")
    for x, y in (pts[0], pts[-1]):
        d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=255)
    out = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    out.paste(gradient(big), (0, 0), mask)
    return out.resize((size, size), Image.LANCZOS)


def tile(size: int, radius: float) -> Image.Image:
    img = Image.new("RGBA", (size * 4, size * 4), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle([0, 0, size * 4 - 1, size * 4 - 1], radius=radius * size * 4, fill=(7, 10, 30, 255))
    img = img.resize((size, size), Image.LANCZOS)
    img.alpha_composite(mark(size, .78))
    return img


def glow(canvas: Image.Image, centre, radius: int, colour, strength: int):
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.ellipse([centre[0] - radius, centre[1] - radius, centre[0] + radius, centre[1] + radius], fill=colour + (strength,))
    canvas.alpha_composite(layer.filter(ImageFilter.GaussianBlur(radius / 1.6)))


def share_image() -> Image.Image:
    w, h = 1200, 630
    img = Image.new("RGBA", (w, h), BG + (255,))
    glow(img, (140, 600), 300, BLUE, 85)
    glow(img, (1100, 40), 330, VIOLET, 70)
    glow(img, (330, 315), 230, CYAN, 55)
    d = ImageDraw.Draw(img)
    grid = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grid)
    for x in range(0, w, 60):
        gd.line([(x, 0), (x, h)], fill=(140, 158, 255, 14))
    for y in range(0, h, 60):
        gd.line([(0, y), (w, y)], fill=(140, 158, 255, 14))
    img.alpha_composite(grid)
    big = mark(380)
    img.alpha_composite(big, (110, 125))
    d = ImageDraw.Draw(img)
    d.ellipse([110 - 14, 125 - 14, 110 + 394, 125 + 394], outline=(140, 158, 255, 40), width=2)
    x = 560
    d.text((x, 150), "Countersign", font=font("bold", 104), fill=INK)
    d.text((x, 280), "Payment guardrails for AI agents", font=font("semi", 40), fill=MUTED)
    body = font("text", 29)
    for i, line in enumerate(("Every refund and payment is checked by", "plain code. It runs, waits for the owner,", "or is refused.")):
        d.text((x, 352 + i * 42), line, font=body, fill=FAINT)
    pill = font("semi", 24)
    shade = Image.new("RGBA", (w, h), (0, 0, 0, 0))   # the soft fill is drawn on its own layer so its transparency survives
    sd = ImageDraw.Draw(shade)
    cx, boxes = x, []
    for word, colour in (("ALLOW", ALLOW), ("HOLD", HOLD), ("REFUSE", REFUSE)):
        tw = d.textlength(word, font=pill)
        boxes.append((cx, tw, word, colour))
        sd.rounded_rectangle([cx, 500, cx + tw + 44, 552], radius=26, fill=colour + (30,))
        cx += tw + 44 + 16
    img.alpha_composite(shade)
    d = ImageDraw.Draw(img)
    for cx, tw, word, colour in boxes:
        d.rounded_rectangle([cx, 500, cx + tw + 44, 552], radius=26, outline=colour + (255,), width=2)
        d.text((cx + 22, 513), word, font=pill, fill=colour + (255,))
    return img.convert("RGB")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "favicon.svg").write_text(SVG, encoding="utf-8")
    tile(256, .22).save(OUT / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    apple = Image.new("RGBA", (180, 180), (7, 10, 30, 255))
    apple.alpha_composite(mark(180, .78))
    apple.convert("RGB").save(OUT / "apple-touch-icon.png")
    share_image().save(OUT / "og.png", optimize=True)
    for f in sorted(OUT.iterdir()):
        print(f"{f.name:<22}{f.stat().st_size:>8} bytes")


main()
