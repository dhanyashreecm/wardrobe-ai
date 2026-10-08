"""
Calibrates the "same item = 100%" check on THIS machine's real wardrobe
photos (backend/uploads/_remote_cache). Writes a report and a picture
of any doubtful pairs to backups/_claude_tmp/. Read-only otherwise.

    ./ai_env312/bin/python -m scripts.calibrate_same_item
"""
import glob
import hashlib
import io
import os
import tempfile
import time

import numpy as np
from PIL import Image, ImageDraw

from backend import clothing_similarity as cs
from backend import image_pipeline

OUT = os.path.join("backups", "_claude_tmp")
os.makedirs(OUT, exist_ok=True)
report = open(os.path.join(OUT, "calibration.txt"), "w")


def log(*a):
    line = " ".join(str(x) for x in a)
    print(line)
    report.write(line + "\n")
    report.flush()


files = sorted({
    hashlib.md5(open(f, "rb").read()).hexdigest(): f
    for f in glob.glob("backend/uploads/_remote_cache/*.jpg")
}.values())
log(len(files), "unique wardrobe photos")
t0 = time.time()

feats = [cs.extract_feature(f) for f in files]
prints = [cs.image_fingerprint(f) for f in files]
log("features ready in %.0fs" % (time.time() - t0))

tmp = tempfile.mkdtemp()

# ---- 1. every photo, re-uploaded, must come back as itself ----
missed = []
for idx, f in enumerate(files):
    im = Image.open(f).convert("RGB")
    up = im.copy()
    up.thumbnail((1400, 1400))
    q1 = os.path.join(tmp, "q1.jpg")
    up.save(q1, "JPEG", quality=82)
    variants = [q1]
    try:
        cleaned = image_pipeline.process_clothing_photo(q1)
        q2 = os.path.join(tmp, "q2.jpg")
        cleaned["image"].save(q2, "JPEG", quality=90)
        variants.append(q2)
    except Exception as e:  # noqa: BLE001
        log("  cleaning failed for", f, e)
    best = max(float(np.dot(cs.extract_feature(v), feats[idx])) for v in variants)
    ok = any(cs.is_same_item(cs.image_fingerprint(v), prints[idx], best) for v in variants)
    if not ok:
        missed.append((f, best))
log("re-upload recognised: %d / %d" % (len(files) - len(missed), len(files)))
for f, b in missed:
    log("  MISSED", f, "cos=%.3f" % b)

# ---- 2. different photos wrongly called the same ----
flagged = []
for i in range(len(files)):
    for j in range(i + 1, len(files)):
        sim = float(np.dot(feats[i], feats[j]))
        if sim < cs.EXACT_KEYPOINT_MIN_FEATURE_SIMILARITY:
            continue
        if cs.is_same_item(prints[i], prints[j], sim):
            flagged.append((sim, cs.keypoint_inliers(prints[i], prints[j]),
                            cs.fingerprint_distance(prints[i], prints[j]), i, j))
flagged.sort(reverse=True)
log("pairs of DIFFERENT files called the same item:", len(flagged))
for sim, inl, dist, i, j in flagged:
    log("  cos=%.3f inliers=%d pix=%.4f  %s  %s" % (sim, inl, dist, files[i][-16:], files[j][-16:]))

W = 140
rows = flagged[:40] + [(0, 0, 0, files.index(f), files.index(f)) for f, _ in missed[:20]]
if rows:
    sheet = Image.new("RGB", (W * 2 + 160, W * len(rows)), "white")
    draw = ImageDraw.Draw(sheet)
    for r, (sim, inl, dist, i, j) in enumerate(rows):
        for c, k in enumerate((i, j)):
            thumb = Image.open(files[k]).convert("RGB")
            thumb.thumbnail((W, W))
            sheet.paste(thumb, (c * W, r * W))
        label = "MISSED" if i == j else "cos %.2f\ninl %d" % (sim, inl)
        draw.text((2 * W + 6, r * W + 55), label, fill="black")
    sheet.save(os.path.join(OUT, "calibration.jpg"))
log("done in %.0fs" % (time.time() - t0))
report.close()
