"""
Background removal on realistic scenes (synthetic, generated here so no
personal photos are needed): floor, bed, hanger, clutter, clean.

For each scene we know exactly which pixels are the garment, so we can
check: backdrop removed (white), garment intact (mask overlap), colour
preserved, and the output is still a normal RGB image the classifier
can take.
"""
import io
import unittest

import numpy as np

try:
    import cv2
    from PIL import Image
    from backend import image_pipeline as ip
    HAVE_CV = True
except ImportError:  # pragma: no cover
    HAVE_CV = False

W, H = 600, 800
GARMENT = (178, 34, 52)  # deep red


def tshirt_mask(w=W, h=H, scale=1.0, cx=None, cy=None):
    cx = w // 2 if cx is None else cx
    cy = h // 2 if cy is None else cy
    s = scale * min(w, h) / 600
    pts = np.array([(-110, -170), (-40, -190), (40, -190), (110, -170), (200, -90), (150, -30),
                    (100, -70), (100, 190), (-100, 190), (-100, -70), (-150, -30), (-200, -90)], np.float32)
    pts = (pts * s + (cx, cy)).astype(np.int32)
    m = np.zeros((h, w), np.uint8)
    cv2.fillPoly(m, [pts], 1)
    return m


def paint_garment(scene, mask, rng):
    g = np.array(GARMENT, np.float32)
    shade = rng.normal(0, 6, scene.shape[:2])[..., None]  # fabric texture / folds
    garment = np.clip(g + shade, 0, 255)
    scene[mask == 1] = garment[mask == 1]
    return scene


def floor_scene(rng):
    # wooden planks
    img = np.zeros((H, W, 3), np.float32)
    for i, x in enumerate(range(0, W, 75)):
        tone = np.array([150, 110, 70]) + (i % 3) * 12
        img[:, x:x + 75] = tone
        img[:, x:x + 2] = (90, 60, 40)
    img += rng.normal(0, 8, img.shape)
    return img


def bed_scene(rng):
    # light bedsheet with a blue check pattern
    img = np.full((H, W, 3), (235, 232, 225), np.float32)
    for x in range(0, W, 50):
        img[:, x:x + 6] = (120, 150, 200)
    for y in range(0, H, 50):
        img[y:y + 6, :] = (120, 150, 200)
    img += rng.normal(0, 5, img.shape)
    return img


def hanger_scene(rng):
    img = np.full((H, W, 3), (205, 200, 190), np.float32)  # wall
    img += np.linspace(-15, 15, W)[None, :, None]  # uneven light
    img += rng.normal(0, 4, img.shape)
    return img


def cluttered_scene(rng):
    img = np.full((H, W, 3), (190, 185, 175), np.float32)
    img += rng.normal(0, 6, img.shape)
    # objects touching the edges: a bag, a book, a bottle
    cv2.rectangle(img, (0, 0), (120, 160), (60, 90, 140), -1)
    cv2.rectangle(img, (480, 650), (599, 799), (40, 120, 60), -1)
    cv2.circle(img, (560, 60), 50, (220, 200, 40), -1)
    return img


def clean_scene(rng):
    img = np.full((H, W, 3), (245, 245, 245), np.float32)
    img += rng.normal(0, 2, img.shape)
    return img


def make(scene_fn, seed=0, hanger=False):
    rng = np.random.default_rng(seed)
    img = scene_fn(rng)
    mask = tshirt_mask()
    img = paint_garment(img, mask, rng)
    if hanger:
        # thin hook above the neckline: not garment, must not hurt it
        cv2.line(img, (W // 2, H // 2 - 190), (W // 2, H // 2 - 260), (80, 80, 80), 4)
    img = np.clip(img, 0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(img).save(buf, "PNG")
    return buf.getvalue(), mask


@unittest.skipUnless(HAVE_CV, "opencv/Pillow not installed")
class BackgroundRemovalScenes(unittest.TestCase):
    SCENES = {
        "floor": (floor_scene, False),
        "bed": (bed_scene, False),
        "hanger": (hanger_scene, True),
        "cluttered": (cluttered_scene, False),
        "clean": (clean_scene, False),
    }

    def run_scene(self, name):
        fn, hanger = self.SCENES[name]
        data, truth = make(fn, hanger=hanger)
        result = ip.process_clothing_photo(data)
        out = np.asarray(result["image"])
        mask = np.asarray(result["mask"]) > 128
        return result, out, mask, truth

    def check(self, name):
        result, out, mask, truth = self.run_scene(name)
        self.assertTrue(result["background_removed"], f"{name}: {result['warnings']}")
        # garment kept: its share of the photo matches the truth
        self.assertAlmostEqual(result["foreground_share"], truth.mean(), delta=0.06, msg=name)
        # white background: everything outside the garment is white
        outside = out[~mask]
        self.assertGreater((outside.min(axis=1) > 240).mean(), 0.97, name)
        # corners are pure white
        for y, x in [(2, 2), (2, -3), (-3, 2), (-3, -3)]:
            self.assertTrue((out[y, x] > 245).all(), f"{name} corner {out[y, x]}")
        # garment colour preserved
        inside = out[mask].mean(axis=0)
        self.assertLess(np.abs(inside - GARMENT).max(), 20, f"{name}: {inside}")
        # 3:4 portrait output, usable by the classifier
        h, w = out.shape[:2]
        self.assertAlmostEqual(w / h, 0.75, delta=0.01)
        self.assertEqual(out.shape[2], 3)

    def test_floor(self):
        self.check("floor")

    def test_bed(self):
        self.check("bed")

    def test_hanger(self):
        self.check("hanger")

    def test_cluttered(self):
        self.check("cluttered")

    def test_clean(self):
        self.check("clean")

    def test_garment_pixels_for_colour(self):
        result, *_ = self.run_scene("bed")
        pixels = np.array(ip.garment_pixels(result["image"], result["mask"]))
        self.assertLess(np.abs(pixels.mean(axis=0) - GARMENT).max(), 20)

    def test_classifier_input_still_works(self):
        from backend import garment_classifier as gc
        result, *_ = self.run_scene("floor")
        if hasattr(gc, "prepare_image"):
            arr = gc.prepare_image(result["image"])
            self.assertEqual(tuple(np.asarray(arr).shape[-3:]), (224, 224, 3))

    def _custom(self, backdrop, colour):
        rng = np.random.default_rng(3)
        img = backdrop(rng)
        m = tshirt_mask()
        img[m == 1] = np.array(colour) + rng.normal(0, 6, (int(m.sum()), 3))
        buf = io.BytesIO()
        Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(buf, "PNG")
        return ip.process_clothing_photo(buf.getvalue()), m

    def test_white_shirt_on_white_background(self):
        result, truth = self._custom(clean_scene, (252, 252, 252))
        # either separated correctly or honestly kept - never a wrong crop
        if result["background_removed"]:
            self.assertAlmostEqual(result["foreground_share"], truth.mean(), delta=0.06)

    def test_same_colour_as_floor_is_never_mangled(self):
        result, truth = self._custom(floor_scene, (170, 130, 90))
        if result["background_removed"]:
            self.assertAlmostEqual(result["foreground_share"], truth.mean(), delta=0.06)
        else:
            self.assertTrue(result["warnings"])

    def test_unreadable_file_rejected(self):
        with self.assertRaises(ip.ImageRejected):
            ip.process_clothing_photo(b"not an image")

    def test_tiny_image_rejected(self):
        buf = io.BytesIO()
        Image.new("RGB", (50, 50), "red").save(buf, "PNG")
        with self.assertRaises(ip.ImageRejected):
            ip.process_clothing_photo(buf.getvalue())

    def test_whole_frame_garment_keeps_photo(self):
        # a close-up where the fabric fills the frame: nothing to remove,
        # photo must not be mangled
        rng = np.random.default_rng(1)
        img = np.clip(np.array(GARMENT) + rng.normal(0, 5, (H, W, 3)), 0, 255).astype(np.uint8)
        buf = io.BytesIO()
        Image.fromarray(img).save(buf, "PNG")
        result = ip.process_clothing_photo(buf.getvalue())
        out = np.asarray(result["image"])
        self.assertGreater(out.shape[0], 100)
        self.assertLess(np.abs(out[H // 2 * out.shape[0] // H, out.shape[1] // 2] - GARMENT).max(), 30)


if __name__ == "__main__":
    unittest.main()
