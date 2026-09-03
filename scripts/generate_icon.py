"""Generates app.ico -- a simple, legible-at-16px mark: "DJ" on the M3
primary-container rounded square, matching the in-app topbar brand chip."""
import os
from PIL import Image, ImageDraw, ImageFont

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "app.ico")

BG = (52, 65, 156, 255)      # --m3-primary-container
FG = (222, 225, 255, 255)    # --m3-on-primary-container


def render(size):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=round(size * 0.26), fill=BG)

    label = "DJ"
    font_size = round(size * 0.52)
    try:
        font = ImageFont.truetype("segoeuib.ttf", font_size)
    except Exception:
        font = ImageFont.load_default()
    bbox = d.textbbox((0, 0), label, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text(((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1]), label, font=font, fill=FG)
    return img


def main():
    sizes = [16, 24, 32, 48, 64, 128, 256]
    imgs = [render(s) for s in sizes]
    imgs[-1].save(OUT, format="ICO", sizes=[(s, s) for s in sizes])
    print("wrote", OUT)


if __name__ == "__main__":
    main()
