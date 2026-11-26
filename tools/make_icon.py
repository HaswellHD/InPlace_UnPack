"""Create assets/icon.ico + assets/icon.png from a square source image.

Usage: python tools/make_icon.py SOURCE_IMAGE
Needs Pillow (dev only: pip install pillow). The white background around
the artwork is made transparent by flood-filling from the image border.
"""
import os
import sys

from PIL import Image, ImageDraw

src = sys.argv[1]
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
out = os.path.join(root, "assets")
os.makedirs(out, exist_ok=True)

im = Image.open(src).convert("RGBA")
w, h = im.size
seeds = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1),
         (w // 2, 2), (2, h // 2), (w - 3, h // 2), (w // 2, h - 3)]
for xy in seeds:
    if sum(im.getpixel(xy)[:3]) > 690:  # near-white background only
        ImageDraw.floodfill(im, xy, (0, 0, 0, 0), thresh=60)
im = im.crop(im.getbbox())
side = max(im.size)
sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
sq.paste(im, ((side - im.size[0]) // 2, (side - im.size[1]) // 2))
sq.resize((512, 512), Image.LANCZOS).save(os.path.join(out, "icon.png"))
sq.save(os.path.join(out, "icon.ico"),
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("written:", os.path.join(out, "icon.ico"))
