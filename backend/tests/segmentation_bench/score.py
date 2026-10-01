"""
Score the segmentation pipeline against the benchmark's exact masks.

IoU is the honest number here: it punishes both cutting into the
garment and swallowing floor. "kept_photo" means the pipeline refused
to cut rather than mangling the image, which is a correct behaviour,
not a success - it is reported separately.
"""
import os, sys, json, time
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")))
from backend import image_pipeline as ip


def iou(pred, truth):
    p, t = pred > 0.5, truth > 0.5
    union = (p | t).sum()
    return float((p & t).sum() / union) if union else 0.0


def recall_precision(pred, truth):
    p, t = pred > 0.5, truth > 0.5
    rec = float((p & t).sum() / t.sum()) if t.sum() else 0.0
    pre = float((p & t).sum() / p.sum()) if p.sum() else 0.0
    return rec, pre


def run(engine, bench="bench"):
    os.environ["BG_REMOVAL_ENGINE"] = engine
    rows = []
    names = sorted(n[:-4] for n in os.listdir(bench)
                   if n.endswith(".png") and not n.endswith("_truth.png")
                   and n != "contact_sheet.png")
    for name in names:
        img = Image.open(f"{bench}/{name}.png").convert("RGB")
        truth = np.asarray(Image.open(f"{bench}/{name}_truth.png")).astype(np.float32) / 255.0
        started = time.time()
        mask, used = ip.segment(img)
        elapsed = time.time() - started
        if mask is None:
            rows.append({"case": name, "engine": used, "iou": 0.0, "recall": 0.0,
                         "precision": 0.0, "kept_photo": True, "seconds": round(elapsed, 2)})
            continue
        share = float(mask.mean())
        kept = not (ip.MIN_FOREGROUND <= share <= ip.MAX_FOREGROUND)
        rec, pre = recall_precision(mask, truth)
        rows.append({"case": name, "engine": used, "iou": round(iou(mask, truth), 3),
                     "recall": round(rec, 3), "precision": round(pre, 3),
                     "kept_photo": kept, "seconds": round(elapsed, 2)})
    return rows


if __name__ == "__main__":
    engine = sys.argv[1] if len(sys.argv) > 1 else "auto"
    rows = run(engine)
    print(f"{'case':26} {'engine':16} {'IoU':>6} {'recall':>7} {'prec':>6}  {'s':>5}")
    for r in rows:
        flag = "  (kept photo)" if r["kept_photo"] else ""
        print(f"{r['case']:26} {r['engine']:16} {r['iou']:6.3f} "
              f"{r['recall']:7.3f} {r['precision']:6.3f}  {r['seconds']:5.2f}{flag}")
    good = [r for r in rows if not r["kept_photo"]]
    print()
    print(f"mean IoU over all {len(rows)} cases: "
          f"{np.mean([r['iou'] for r in rows]):.3f}")
    print(f"cases where a cut-out was produced: {len(good)}/{len(rows)}")
    if good:
        print(f"mean IoU where it did cut:          "
              f"{np.mean([r['iou'] for r in good]):.3f}")
    json.dump(rows, open(f"result_{engine}.json", "w"), indent=1)
