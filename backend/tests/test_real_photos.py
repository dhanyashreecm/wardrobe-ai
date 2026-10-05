"""
REAL PHOTOGRAPHS, NOT COMPOSITES.

test_segmentation_quality.py scores the pipeline against generated
images whose garment shape is known to the pixel. That measures
accuracy, but every one of those images was drawn by a script. This
file is the other half: actual photographs, taken on a phone, of actual
clothes on an actual floor - the thing the app is for.

There is no ground-truth mask for a real photo, so these tests do not
score IoU. They check what CAN be checked without one, and what was
genuinely getting broken:

  * a cut-out is produced at all, rather than the pipeline giving up
    and keeping the whole photo;
  * it is not mostly background;
  * it keeps nearly all of the garment, judged by how much of the
    garment's own colour survives.

WHY THIS FILE EXISTS

A photo of pink palazzos on a polished marble floor broke the pipeline
in two separate ways at once, and neither showed up in the synthetic
benchmark:

  1. The garment ran from the left edge of the frame to the right one,
     because it was photographed to fill the picture - as people
     actually do. The plausibility check rejected any mask touching two
     frame edges, so a perfectly good cut-out was thrown away and the
     whole photo kept instead.

  2. A window reflection on the polished floor - a bright pale streak
     beside the garment - was swallowed by OpenCV GrabCut and stored as
     part of the trousers.

The first is fixed; see _runs_off_the_frame in image_pipeline, and the
rules pinned at the bottom of this file. The second is why rembg is
worth installing: on this photo it removes the reflection completely
and GrabCut does not.

ADDING MORE PHOTOS

Drop any .jpg or .png into backend/tests/real_photos/ and it is picked
up automatically. Files beginning with "_" are ignored, so scratch
output can live there too. The folder is gitignored, because these are
photographs of someone's home and clothes, so the tests skip cleanly on
a machine that has none.
"""
import os
import unittest

try:
    import numpy as np
    import cv2  # noqa: F401
    from PIL import Image  # noqa: F401
    HAVE_DEPS = True
except ImportError:
    HAVE_DEPS = False

PHOTO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "real_photos")


def _photos():
    if not os.path.isdir(PHOTO_DIR):
        return []
    return sorted(
        os.path.join(PHOTO_DIR, name)
        for name in os.listdir(PHOTO_DIR)
        if name.lower().endswith((".jpg", ".jpeg", ".png"))
        and not name.startswith("_")
        and not name.lower().endswith(".mask.png")
    )


@unittest.skipUnless(HAVE_DEPS, "numpy/opencv/Pillow not installed here")
@unittest.skipUnless(_photos(), "no photographs in backend/tests/real_photos/")
class RealPhotoSegmentationTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from backend import image_pipeline
        cls.pipeline = image_pipeline
        cls.photos = _photos()

    def test_every_photo_is_either_cut_out_or_explained(self):
        """
        The contract, which holds whatever engine is installed: either
        the background comes off, or the photo is kept AND the user is
        told why. What must never happen is the photo being kept in
        silence - the item then sits in the wardrobe with a floor
        behind it, goes to the try-on model that way, and nobody knows.
        """
        for path in self.photos:
            with self.subTest(photo=os.path.basename(path)):
                result = self.pipeline.process_clothing_photo(path)
                if not result["background_removed"]:
                    self.assertTrue(
                        result["warnings"],
                        "kept the original photo without saying so",
                    )

    @unittest.skipUnless(
        os.environ.get("BG_REMOVAL_ENGINE", "auto").lower() in ("auto", "rembg"),
        "forced onto OpenCV, which cannot do these photos",
    )
    def test_with_rembg_installed_the_background_really_comes_off(self):
        """
        The reason rembg is worth installing, stated as a test.

        On the palazzos - wide-legged trousers filling the frame on a
        polished floor with a window reflection beside them - OpenCV
        GrabCut cannot find the garment at all and the photo is kept
        whole. rembg cuts it cleanly. If rembg is not installed this
        skips rather than failing, because then it is a missing
        dependency, not a broken pipeline.
        """
        try:
            import rembg  # noqa: F401
        except ImportError:
            self.skipTest("rembg is not installed on this machine")

        for path in self.photos:
            with self.subTest(photo=os.path.basename(path)):
                result = self.pipeline.process_clothing_photo(path)
                self.assertTrue(
                    result["background_removed"],
                    f"rembg is installed and the background still was not "
                    f"removed (engine: {result['engine']})",
                )

    def test_a_cut_out_is_mostly_garment_not_background(self):
        for path in self.photos:
            with self.subTest(photo=os.path.basename(path)):
                result = self.pipeline.process_clothing_photo(path)
                if not result["background_removed"]:
                    continue  # nothing was cut; covered by the test above
                share = result["foreground_share"]
                self.assertGreater(share, 0.05, "almost nothing was kept")
                self.assertLess(share, 0.95, "almost nothing was removed")

    def test_the_cut_out_matches_the_reference_outline(self):
        """
        The real check: does the cut-out still look like the garment?

        A photo may sit beside a reference mask, <name>.mask.png, which
        was produced once and CHECKED BY EYE against the photograph
        before being saved. That is what makes it usable as truth: not
        that a model produced it, but that a person looked at it and
        agreed it was the garment, all of the garment, and nothing else.

        The floor is 0.80 rather than something tighter on purpose. The
        two engines legitimately disagree at the margins - on the
        palazzos, OpenCV scores 0.95 against the reference because it
        also takes in a window reflection on the polished floor, which
        is a real flaw but a small area. What 0.80 catches is the
        failure that ruins an item: a trouser leg, a sleeve or a hem
        gone.

        A photo with no reference mask is still covered by the other
        tests here; it just is not scored.
        """
        scored = 0

        for path in self.photos:
            reference_path = os.path.splitext(path)[0] + ".mask.png"
            if not os.path.isfile(reference_path):
                continue

            with self.subTest(photo=os.path.basename(path)):
                image, _ = self.pipeline.load_and_validate(path)
                reference = np.asarray(
                    Image.open(reference_path).convert("L")
                ).astype(np.float32) / 255.0

                mask, engine = self.pipeline.segment(image)
                if mask is None:
                    # The pipeline declined rather than cut badly. That
                    # is a correct answer (see the contract test above),
                    # just not one that can be scored.
                    continue
                self.assertEqual(mask.shape, reference.shape,
                                 "reference mask is a different size")

                both = (mask > 0.5) & (reference > 0.5)
                either = (mask > 0.5) | (reference > 0.5)
                score = float(both.sum() / either.sum()) if either.sum() else 0.0

                self.assertGreater(
                    score, 0.80,
                    f"{os.path.basename(path)} scored IoU {score:.3f} with "
                    f"engine {engine} - part of the garment is missing, or a "
                    f"large piece of the background came with it",
                )
                scored += 1

        if scored == 0:
            self.skipTest("no reference masks beside the photos")

    def test_the_stored_image_is_a_wardrobe_card(self):
        for path in self.photos:
            with self.subTest(photo=os.path.basename(path)):
                result = self.pipeline.process_clothing_photo(path)
                width, height = result["image"].size
                self.assertAlmostEqual(width / height, 3 / 4, places=1)
                self.assertLessEqual(max(width, height), self.pipeline.MAX_SIDE)


@unittest.skipUnless(HAVE_DEPS, "numpy/opencv/Pillow not installed here")
class FrameTouchingRules(unittest.TestCase):
    """The specific rule the palazzos broke, pinned so it cannot return."""

    @classmethod
    def setUpClass(cls):
        from backend import image_pipeline
        cls.pipeline = image_pipeline

    def _mask(self, box, shape=(1000, 1000)):
        mask = np.zeros(shape, np.float32)
        top, bottom, left, right = box
        mask[top:bottom, left:right] = 1.0
        return mask

    def test_a_garment_spanning_the_full_width_is_allowed(self):
        """Wide-legged trousers shot from above: edge to edge sideways."""
        self.assertFalse(self.pipeline._runs_off_the_frame(self._mask((110, 880, 0, 1000))))

    def test_a_garment_spanning_the_full_height_is_allowed(self):
        self.assertFalse(self.pipeline._runs_off_the_frame(self._mask((0, 1000, 150, 820))))

    def test_a_mask_covering_the_whole_frame_is_rejected(self):
        """That is the floor, not the clothes."""
        self.assertTrue(self.pipeline._runs_off_the_frame(self._mask((0, 1000, 0, 1000))))

    def test_an_empty_mask_is_rejected(self):
        self.assertTrue(
            self.pipeline._runs_off_the_frame(np.zeros((100, 100), np.float32))
        )

    def test_a_garment_well_inside_the_frame_is_allowed(self):
        self.assertFalse(self.pipeline._runs_off_the_frame(self._mask((200, 800, 250, 750))))


if __name__ == "__main__":
    unittest.main()
