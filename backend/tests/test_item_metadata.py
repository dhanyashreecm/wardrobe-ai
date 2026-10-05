"""
WHAT AN ITEM CLAIMS ABOUT ITSELF.

A user photographed plain pink cotton palazzos and the wardrobe
labelled them "Ethnic - Smart - rose", suitable for "Traditional,
Wedding". Nothing about that came from the photograph. The image
pipeline did its job; two lookup tables did the rest:

  * occasion_model aliased the word "palazzo" onto the Myntra article
    "Patiala", whose measured usage is 100% ethnic. A Patiala salwar
    IS festive. A palazzo is not, and inherited the numbers anyway.

  * outfit_recommendation listed "palazzo" as {wedding, traditional},
    so the only occasions it was ever eligible for were a wedding and
    a festival.

The result was that every palazzo in the world - cotton, printed,
worn to college - came out as wedding wear, and the user could not
tell the app otherwise except by editing each item by hand.

These tests pin the corrected behaviour, and just as importantly pin
the garments that SHOULD still read as festive, so the fix cannot be
over-applied: a sharara, a salwar and a lehenga are genuinely
traditional and must stay that way.
"""
import os
import unittest

os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017/test")
os.environ.setdefault("JWT_SECRET_KEY", "tests-only")

from backend import item_attributes
from backend import outfit_recommendation
from backend.color_detection import display_name


def occasions(category):
    return outfit_recommendation.infer_occasions_for_category(category)


class PalazzosAreEverydayWear(unittest.TestCase):

    def test_palazzos_are_not_wedding_wear(self):
        self.assertNotIn("wedding", occasions("Palazzos"))

    def test_palazzos_are_suitable_for_ordinary_days(self):
        for everyday in ("casual", "college", "day_outing"):
            self.assertIn(everyday, occasions("Palazzos"))

    def test_palazzos_still_work_for_traditional_occasions(self):
        """
        The point is not to strip the ethnic reading out - plenty of
        people wear a kurta with palazzos to a festival. It is to stop
        that being the ONLY reading.
        """
        self.assertIn("traditional", occasions("Palazzos"))

    def test_palazzos_are_not_described_as_ethnic_in_style(self):
        self.assertNotEqual(item_attributes.style_label("Palazzos"), "ethnic")

    def test_a_palazzo_reads_as_casual(self):
        self.assertEqual(item_attributes.style_label("Palazzos"), "casual")

    def test_the_wardrobe_card_says_casual_not_smart(self):
        """
        There are two style paths - item_attributes.style_label and
        style_compatibility.resolve_style - and the wardrobe card uses
        the second. Fixing only the first left the card still reading
        "Smart", so both are pinned here.
        """
        from backend import outfit_presentation

        card = outfit_presentation.present_item(
            {"category": "Palazzos", "color": "rose", "user_email": "a@b.c"}
        )
        self.assertEqual(card["style_label"], "Casual")
        self.assertEqual(card["color_display"], "Pink")


class GenuinelyFestiveGarmentsAreUnchanged(unittest.TestCase):
    """The guard against fixing this too enthusiastically."""

    def test_a_sharara_is_still_festive(self):
        """
        Shararas share the palazzo garment KIND - same shape - so a
        careless fix takes them with it. They are wedding wear.
        """
        self.assertEqual(occasions("Sharara"), {"wedding", "traditional"})
        self.assertEqual(item_attributes.style_label("Sharara"), "ethnic")

        from backend import style_compatibility
        self.assertNotEqual(
            style_compatibility.infer_style("Sharara"),
            style_compatibility.infer_style("Palazzos"),
            "a sharara was swept along with the palazzo fix",
        )

    def test_a_salwar_is_still_festive(self):
        self.assertIn("traditional", occasions("Salwar"))
        self.assertEqual(item_attributes.style_label("Salwar"), "ethnic")

    def test_a_lehenga_is_still_festive(self):
        self.assertIn("wedding", occasions("Lehenga"))
        self.assertEqual(item_attributes.style_label("Lehenga"), "ethnic")

    def test_a_saree_is_still_festive(self):
        self.assertIn("traditional", occasions("Saree"))

    def test_jeans_did_not_become_traditional(self):
        self.assertNotIn("traditional", occasions("Jeans"))
        self.assertNotIn("wedding", occasions("Jeans"))


class ColoursAreNamedTheWayPeopleTalk(unittest.TestCase):
    """
    The detector picks from 95 shades, which is right for matching and
    wrong for reading. "rose" is a correct measurement of the pixels
    and a strange thing to tell someone about their trousers.
    """

    def test_the_shade_that_started_this_reads_as_pink(self):
        self.assertEqual(display_name("rose"), "Pink")

    def test_shades_collapse_onto_everyday_words(self):
        for shade, expected in (
            ("blush", "Pink"), ("magenta", "Pink"),
            ("burgundy", "Maroon"), ("wine", "Maroon"),
            ("charcoal", "Grey"), ("slate", "Grey"),
            ("mustard", "Yellow"), ("olive", "Green"),
            ("teal", "Green"), ("indigo", "Navy"),
            ("ivory", "Cream"), ("taupe", "Beige"),
        ):
            self.assertEqual(display_name(shade), expected, shade)

    def test_a_qualified_shade_still_resolves(self):
        self.assertEqual(display_name("dark navy"), "Navy")
        self.assertEqual(display_name("light pink"), "Pink")

    def test_an_unknown_colour_is_shown_not_invented(self):
        """Better the user's own word than a guess."""
        self.assertEqual(display_name("chartreuse"), "Chartreuse")

    def test_nothing_in_means_nothing_out(self):
        self.assertEqual(display_name(""), "")
        self.assertEqual(display_name(None), "")

    def test_the_measured_shade_is_never_destroyed(self):
        """
        present_item ADDS the readable name; it must not overwrite the
        stored one, or every wardrobe already full of "rose" and "teal"
        items loses information the colour matcher uses.
        """
        from backend import outfit_presentation

        stored = {"category": "Palazzos", "color": "rose", "user_email": "a@b.c"}
        shown = outfit_presentation.present_item(stored)

        self.assertEqual(shown["color"], "rose")
        self.assertEqual(shown["color_display"], "Pink")
        self.assertEqual(stored["color"], "rose", "the stored item was mutated")


if __name__ == "__main__":
    unittest.main()
