"""
CLOTHING PHOTO -> CLEAN WARDROBE IMAGE

Real users photograph clothes on the floor, on a bed, on a hanger, in
poor light. Before an item is classified or stored, this module turns
that photo into what the rest of the app expects: the garment alone,
on a clean white background.

    UPLOAD -> validate -> segment the garment -> white background
           -> tight crop with margin -> (classifier, colour, storage)

Segmentation engines, best first:

  1. rembg (open-source U^2-Net / IS-Net models, runs locally, free).
     Used automatically when installed:  pip install "rembg[cpu]"
     The first run downloads the model (~170 MB) once.
  2. OpenCV GrabCut, always available (opencv is already a project
     dependency). Seeded from the photo's border - in a clothing photo
     the garment is the subject and the border is backdrop - then
     cleaned up (largest object kept, holes filled, edges feathered).

If segmentation clearly fails (it keeps almost nothing, or almost the
whole frame), the photo is NOT mangled: the original is kept, framed
on white, and `background_removed` is False so this is visible.

Everything returned is honest about what happened; nothing here
invents pixels.
"""
import io
import os

import numpy as np
from PIL import Image, ImageOps

MAX_SIDE = 1024          # processed image size cap
WORK_SIDE = 640          # segmentation working size (speed)
MIN_SIDE = 120           # smaller than this is not a usable photo
MIN_FOREGROUND = 0.03    # garment must cover at least 3% ...
MAX_FOREGROUND = 0.97    # ... and not the entire frame
OUTPUT_ASPECT = 3 / 4    # wardrobe cards are 3:4
MARGIN = 0.06            # white margin around the garment


class ImageRejected(ValueError):
    """The photo cannot be used at all (message is user-facing)."""


# ------------------------------------------------------------
# 1. Validation
# ------------------------------------------------------------

def load_and_validate(source):
    """
    Opens a path/bytes/file object, fixes phone rotation (EXIF) and
    returns (RGB image, warnings). Raises ImageRejected when unusable.
    """
    try:
        if isinstance(source, (bytes, bytearray)):
            img = Image.open(io.BytesIO(source))
        else:
            img = Image.open(source)
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
    except Exception as error:
        raise ImageRejected("That file isn't an image we can read (use JPG, PNG or WEBP).") from error

    if min(img.size) < MIN_SIDE:
        raise ImageRejected(
            f"That photo is too small ({img.width}x{img.height}). Please use a photo at least {MIN_SIDE}px across."
        )

    warnings = []
    gray = np.asarray(img.convert("L"), dtype=np.float32)
    if gray.mean() < 30:
        warnings.append("The photo is very dark - colours may be less accurate.")
    if _sharpness(gray) < 12:
        warnings.append("The photo looks blurry - a sharper photo gives better results.")
    return img, warnings


def _sharpness(gray):
    import cv2
    small = cv2.resize(gray, (min(512, gray.shape[1]), min(512, gray.shape[0])))
    return float(cv2.Laplacian(small, cv2.CV_32F).var())


# ------------------------------------------------------------
# 2. Segmentation
# ------------------------------------------------------------

def _rembg_mask(img):
    """Soft mask 0..1 from rembg, or None when rembg isn't installed."""
    try:
        from rembg import remove, new_session
    except ImportError:
        return None
    global _REMBG_SESSION
    try:
        _REMBG_SESSION
    except NameError:
        _REMBG_SESSION = None
    if _REMBG_SESSION is None:
        model = os.environ.get("REMBG_MODEL", "isnet-general-use")
        _REMBG_SESSION = new_session(model)
    cut = remove(img, session=_REMBG_SESSION, only_mask=True)
    return np.asarray(cut.convert("L"), dtype=np.float32) / 255.0


def _grabcut_mask(img, suppress_backdrop=True):
    """Soft mask 0..1 using OpenCV GrabCut seeded from the border."""
    import cv2

    rgb = np.asarray(img)
    h, w = rgb.shape[:2]
    scale = WORK_SIDE / max(h, w) if max(h, w) > WORK_SIDE else 1.0
    small = cv2.resize(rgb, (int(w * scale), int(h * scale))) if scale != 1.0 else rgb
    sh, sw = small.shape[:2]
    bgr = cv2.cvtColor(small, cv2.COLOR_RGB2BGR)

    mask = np.full((sh, sw), cv2.GC_PR_FGD, np.uint8)
    border = max(3, int(min(sh, sw) * 0.03))
    mask[:border, :] = cv2.GC_BGD
    mask[-border:, :] = cv2.GC_BGD
    mask[:, :border] = cv2.GC_BGD
    mask[:, -border:] = cv2.GC_BGD

    # Pixels that look just like the border are probably backdrop too:
    # this is what lets GrabCut cope with a floor or bedsheet that fills
    # most of the frame around the garment.
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    ring = np.concatenate([lab[:border].reshape(-1, 3), lab[-border:].reshape(-1, 3),
                           lab[:, :border].reshape(-1, 3), lab[:, -border:].reshape(-1, 3)])
    if suppress_backdrop:
        backdrop = _dominant_colours(ring, k=3)
        dist = np.min(np.stack([np.linalg.norm(lab - c, axis=2) for c in backdrop]), axis=0)
        mask[(dist < 12) & (mask == cv2.GC_PR_FGD)] = cv2.GC_PR_BGD

    bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    try:
        cv2.grabCut(bgr, mask, None, bgd, fgd, 6, cv2.GC_INIT_WITH_MASK)
    except cv2.error:
        return None
    fg = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 1, 0).astype(np.uint8)
    fg = _clean_mask(fg)
    if scale != 1.0:
        fg = cv2.resize(fg, (w, h), interpolation=cv2.INTER_NEAREST)
    soft = cv2.GaussianBlur(fg.astype(np.float32), (0, 0), sigmaX=max(1.0, min(h, w) / 400))
    return np.clip(soft, 0, 1)


def _dominant_colours(pixels, k=3):
    import cv2
    pixels = pixels[np.random.default_rng(0).choice(len(pixels), min(len(pixels), 4000), replace=False)]
    k = min(k, len(pixels))
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    _, labels, centers = cv2.kmeans(pixels.astype(np.float32), k, None, criteria, 3, cv2.KMEANS_PP_CENTERS)
    counts = np.bincount(labels.flatten(), minlength=k)
    return [centers[i] for i in range(k) if counts[i] > 0.1 * len(pixels)] or [centers[int(np.argmax(counts))]]


def _clean_mask(fg):
    """Remove specks, keep the garment (largest object + big pieces), fill holes."""
    import cv2
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, kernel)
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, kernel, iterations=2)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(fg, 8)
    if count <= 1:
        return fg
    areas = stats[1:, cv2.CC_STAT_AREA]
    biggest = areas.max()
    keep = np.zeros_like(fg)
    for index, area in enumerate(areas, start=1):
        if area >= 0.15 * biggest:
            keep[labels == index] = 1
    # fill interior holes (e.g. a pattern GrabCut mistook for floor)
    contours, _ = cv2.findContours(keep, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filled = np.zeros_like(keep)
    cv2.drawContours(filled, contours, -1, 1, thickness=cv2.FILLED)
    return filled


def _is_compact_object(mask, edge=0.05):
    """
    True when the mask looks like one item lying inside the photo. A
    colour-blind GrabCut pass that "succeeds" by swallowing floor planks
    runs from edge to edge - that is rejected and the photo kept instead.
    """
    ys, xs = np.where(mask > 0.5)
    if len(xs) == 0:
        return False
    h, w = mask.shape
    touching = sum([xs.min() < w * edge, xs.max() > w * (1 - edge),
                    ys.min() < h * edge, ys.max() > h * (1 - edge)])
    return touching <= 1


def _edge_alignment(img, mask):
    """
    How much of the mask's OUTLINE sits on a real edge in the photo,
    relative to the average edge strength of the whole image.

    This is the single most useful "is this cut-out any good?" signal
    available without knowing the answer. A mask that follows a hem, a
    sleeve or a collar lies along a strong gradient and scores well
    above 1. A mask that slices through flat fabric - a neural matte
    that lost half a dress against a busy throw - or that wanders over
    an empty floor lies on nothing and scores below 1.

    Measured on the benchmark in backend/tests/segmentation_bench: every
    correct mask scored 1.5-15, and the one badly wrong mask scored 0.59.
    """
    import cv2

    rgb = np.asarray(img.convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    gradient = np.hypot(cv2.Sobel(gray, cv2.CV_32F, 1, 0, 3),
                        cv2.Sobel(gray, cv2.CV_32F, 0, 1, 3))
    gradient = cv2.GaussianBlur(gradient, (0, 0), 2.0)

    hard = (mask > 0.5).astype(np.uint8)
    outline = cv2.morphologyEx(
        hard, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8)
    ).astype(bool)

    if outline.sum() < 50:
        return 0.0

    return float(gradient[outline].mean() / (gradient.mean() + 1e-6))


MIN_EDGE_ALIGNMENT = 1.0   # below this the outline is not on any edge
MIN_BBOX_FILL = 0.35       # a garment is a solid shape, not a scatter


def _runs_off_the_frame(mask, edge=0.05):
    """
    True when the mask has no real boundary inside the photo - the sign
    of a cut-out that has swallowed the backdrop rather than found the
    garment.

    Deliberately more forgiving than _is_compact_object, which rejects
    anything touching two sides. Two sides is NORMAL: people photograph
    a garment so it fills the frame, and a pair of wide-legged palazzos
    shot from above really does run from the left edge to the right one
    while sitting well inside the top and bottom. Rejecting that threw
    away a perfectly good cut-out.

    What is not normal is a mask pressed against every side at once, or
    against three sides while covering most of the picture. That is the
    floor, not the clothes.
    """
    hard = mask > 0.5
    ys, xs = np.where(hard)

    if len(xs) == 0:
        return True

    h, w = hard.shape
    touching = sum([
        xs.min() < w * edge,
        xs.max() > w * (1 - edge),
        ys.min() < h * edge,
        ys.max() > h * (1 - edge),
    ])

    if touching >= 4:
        return True

    return touching >= 3 and float(hard.mean()) > 0.6


def _bbox_fill(mask):
    """
    How much of its own bounding box the mask actually fills.

    A real garment is a solid shape: on the benchmark, correct masks
    fill 0.69-0.82 of their box, whatever the garment. A cut-out that
    has latched onto patches of floor instead fills far less - the
    white-t-shirt-on-a-white-bed failure fills 0.16 while covering a
    share of the frame that looks superficially reasonable. This is the
    check that catches it, and the only one that does.
    """
    hard = mask > 0.5
    ys, xs = np.where(hard)

    if len(xs) == 0:
        return 0.0

    box = (ys.max() - ys.min() + 1) * (xs.max() - xs.min() + 1)

    return float(hard.sum() / box) if box else 0.0


def mask_is_plausible(img, mask, learned=False):
    """
    Whether a mask is worth using at all. Several independent checks,
    so one of them being fooled is not enough to let a ruined cut-out
    through:

      * it covers a sensible share of the frame,
      * it is a solid shape rather than a scatter of patches,
      * its outline sits on real edges,
      * and it has a real boundary inside the photo.

    A mask that fails is not used, and the photo is kept instead -
    always better than storing a garment with its sleeves sliced off.

    WHY `learned` EXISTS

    That last check is applied at two different strictnesses, because
    the two engines fail differently and deserve different trust.

    rembg is a segmentation model: it has a learned notion of "object",
    so a mask of its that runs from the left edge of the frame to the
    right one is usually a garment photographed to fill the picture -
    a pair of wide-legged palazzos shot from above, say. Judging that
    harshly threw away good cut-outs.

    GrabCut has no notion of object at all. It clusters colours. When
    the garment and the floor are close in colour it will happily
    return a mask that spans the frame because it has absorbed the
    floor - a t-shirt the colour of floorboards comes back nearly
    twice its real size. On the measurements available (coverage,
    bounding-box fill, edge alignment) that failure is INDISTINGUISHABLE
    from the palazzos, so no threshold can separate them and pretending
    otherwise would be fitting a number to two examples.

    So: a learned mask is allowed to touch the frame, a colour-clustered
    one is not. When GrabCut is refused on those grounds the photo is
    kept whole and the user is told, which is the honest outcome - and
    the practical reason to install rembg.
    """
    if mask is None:
        return False

    share = float(mask.mean())

    if not (MIN_FOREGROUND <= share <= MAX_FOREGROUND):
        return False

    if learned:
        if _runs_off_the_frame(mask):
            return False
    elif not _is_compact_object(mask):
        return False

    if _bbox_fill(mask) < MIN_BBOX_FILL:
        return False

    return _edge_alignment(img, mask) >= MIN_EDGE_ALIGNMENT


def segment(img):
    """
    Returns (soft mask 0..1, engine name) or (None, reason).

    Both engines are fallible, in DIFFERENT ways, which is why neither
    is trusted on its own. Measured over the 14-case benchmark in
    backend/tests/segmentation_bench:

        GrabCut alone   mean IoU 0.896 - but 0.003 on a white t-shirt
                        on a white bed, which it mangles rather than
                        declining
        rembg alone     mean IoU 0.920 - but 0.246 on a dress against
                        a patterned throw, where it keeps a quarter of
                        the garment
        this function   mean IoU 0.971, and no case below 0.8

    The rule is simply: take rembg's mask when it passes the checks in
    mask_is_plausible, fall back to GrabCut when it does not, and keep
    the photo untouched when neither is usable. GrabCut only runs when
    rembg's answer was rejected, so the normal upload pays for one
    engine, not two.
    """
    engine_pref = os.environ.get("BG_REMOVAL_ENGINE", "auto").lower()

    if engine_pref in ("opencv", "grabcut"):
        engine_pref = "grabcut"

    if engine_pref in ("auto", "rembg"):
        try:
            mask = _rembg_mask(img)
        except Exception as error:  # model download failed etc.
            print(f"rembg failed, using OpenCV instead: {error}")
            mask = None

        if mask is not None:
            if mask_is_plausible(img, mask, learned=True):
                return mask, "rembg"
            print("rembg produced an implausible cut-out; trying OpenCV.")

        if engine_pref == "rembg":
            return (mask, "rembg") if mask is not None else (None, "rembg unavailable")

    if engine_pref == "none":
        return None, "disabled"

    # "grabcut" forces the OpenCV path - what a machine without rembg
    # installed actually does, which is what the benchmark compares
    # against.
    mask = _grabcut_mask(img)

    if not mask_is_plausible(img, mask):
        # Garment colour close to the backdrop: try again without the
        # colour hint, letting GrabCut rely on edges and texture only.
        retry = _grabcut_mask(img, suppress_backdrop=False)
        if mask_is_plausible(img, retry):
            mask = retry

    if mask_is_plausible(img, mask):
        return mask, "opencv-grabcut"

    # Nothing trustworthy. process_clothing_photo keeps the original.
    return None, "segmentation failed"


# ------------------------------------------------------------
# 3. White background + framing
# ------------------------------------------------------------

def _frame_on_white(rgb, alpha):
    """Composite on white, crop to the garment, pad to 3:4 with margin."""
    h, w = alpha.shape
    white = np.full_like(rgb, 255, dtype=np.float32)
    out = rgb.astype(np.float32) * alpha[..., None] + white * (1 - alpha[..., None])
    ys, xs = np.where(alpha > 0.5)
    if len(xs) == 0:
        ys, xs = np.arange(h), np.arange(w)
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    crop = out[y0:y1, x0:x1]
    mask_crop = alpha[y0:y1, x0:x1]

    ch, cw = crop.shape[:2]
    pad = int(max(ch, cw) * MARGIN)
    target_h = ch + 2 * pad
    target_w = cw + 2 * pad
    if target_w / target_h > OUTPUT_ASPECT:
        target_h = int(round(target_w / OUTPUT_ASPECT))
    else:
        target_w = int(round(target_h * OUTPUT_ASPECT))
    canvas = np.full((target_h, target_w, 3), 255, np.float32)
    mask_canvas = np.zeros((target_h, target_w), np.float32)
    oy, ox = (target_h - ch) // 2, (target_w - cw) // 2
    canvas[oy:oy + ch, ox:ox + cw] = crop
    mask_canvas[oy:oy + ch, ox:ox + cw] = mask_crop
    image = Image.fromarray(np.clip(canvas, 0, 255).astype(np.uint8))
    mask_img = Image.fromarray((mask_canvas * 255).astype(np.uint8))
    if max(image.size) > MAX_SIDE:
        image.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
        mask_img = mask_img.resize(image.size, Image.BILINEAR)
    return image, mask_img


def process_clothing_photo(source):
    """
    Full pipeline. Returns a dict:
      image              processed PIL image (garment on white, 3:4)
      mask               PIL "L" mask of the garment in that image
      background_removed True when the backdrop was actually removed
      engine             which segmentation engine was used
      foreground_share   fraction of the photo that was garment
      warnings           user-facing notes (dark/blurry/kept original)
    Raises ImageRejected for unusable files.
    """
    img, warnings = load_and_validate(source)
    rgb = np.asarray(img)
    mask, engine = segment(img)

    share = float(mask.mean()) if mask is not None else 0.0
    ok = mask is not None and MIN_FOREGROUND <= share <= MAX_FOREGROUND

    if not ok:
        # Always say so. Before, this only spoke up when a mask existed
        # but looked wrong; segment() returning nothing at all went by
        # in silence, and the user was left wondering why their item
        # still had a floor behind it.
        warnings.append(
            "Couldn't separate the item from the background clearly, so the "
            "full photo was kept. Laying the item on a surface of a "
            "different colour usually fixes this."
        )
        full = np.ones(rgb.shape[:2], np.float32)
        image, mask_img = _frame_on_white(rgb, full)
        return {"image": image, "mask": mask_img, "background_removed": False,
                "engine": engine, "foreground_share": share, "warnings": warnings}

    image, mask_img = _frame_on_white(rgb, mask)
    return {"image": image, "mask": mask_img, "background_removed": True,
            "engine": engine, "foreground_share": round(share, 3), "warnings": warnings}


def garment_pixels(image, mask, limit=4000):
    """RGB pixels that belong to the garment (for colour detection)."""
    rgb = np.asarray(image.convert("RGB"))
    m = np.asarray(mask.resize(image.size)) > 128
    pixels = rgb[m]
    if len(pixels) == 0:
        pixels = rgb.reshape(-1, 3)
    if len(pixels) > limit:
        pixels = pixels[np.random.default_rng(0).choice(len(pixels), limit, replace=False)]
    return [tuple(int(v) for v in p) for p in pixels]
