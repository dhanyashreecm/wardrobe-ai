"""A picture of the difference, for the report."""
import os, sys
import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")))
from backend import image_pipeline as ip

CASES = ["white_tshirt_white_bed", "dress_patterned_throw", "tshirt_tiled_floor"]
CELL = (260, 347)


def cut(img, mask):
    rgb = np.asarray(img).astype(np.float32)
    white = np.full_like(rgb, 255)
    if mask is None:
        out = rgb
    else:
        a = mask[..., None]
        out = rgb * a + white * (1 - a)
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


cols = ["photo", "BEFORE (GrabCut only)", "AFTER (no rembg)", "AFTER (with rembg)"]
sheet = Image.new("RGB", (len(cols) * CELL[0], len(CASES) * CELL[1] + 30), "white")
d = ImageDraw.Draw(sheet)
for i, c in enumerate(cols):
    d.text((i * CELL[0] + 8, 8), c, fill="black")

for row, case in enumerate(CASES):
    img = Image.open(f"bench/{case}.png").convert("RGB")
    y = 30 + row * CELL[1]
    sheet.paste(img.resize(CELL), (0, y))

    # BEFORE: the old code path - grabcut, accepted on share alone
    old = ip._grabcut_mask(img)
    if old is not None and not (ip.MIN_FOREGROUND <= float(old.mean()) <= ip.MAX_FOREGROUND):
        old = None
    sheet.paste(cut(img, old).resize(CELL), (CELL[0], y))

    for col, engine in ((2, "grabcut"), (3, "auto")):
        os.environ["BG_REMOVAL_ENGINE"] = engine
        mask, _ = ip.segment(img)
        sheet.paste(cut(img, mask).resize(CELL), (col * CELL[0], y))

sheet.save("before_after.png")
print("written", sheet.size)
