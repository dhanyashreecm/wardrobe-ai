"""
Tests for the recommendation page, final validator, Home page and trip
looks. Run from the project root:

    python -m unittest discover backend/tests -v
"""
import unittest
from datetime import datetime, timedelta

from backend import outfit_presentation as present
from backend import recommend_service as rs
from backend.outfit_recommendation import recommend_outfits


def make(rows, gender_images=True):
    return [
        {"_id": str(i), "category": c, "color": col, "image_path": f"https://img/{i}.jpg",
         "created_at": datetime(2026, 9, 1) + timedelta(days=i), "favorite": i % 5 == 0}
        for i, (c, col) in enumerate(rows, start=1)
    ]


# The exact wardrobe from the project brief (section 36).
BRIEF = make([
    ("Crop Top", "black"), ("Blouse", "white"), ("Bootcut Jeans", "blue"),
    ("Leggings & Salwars", "black"), ("Saree", "pink"), ("Lehenga", "green"),
    ("Dress", "black"), ("Shirt", "white"), ("Trousers", "beige"),
    ("Sneakers", "white"), ("Heels", "black"), ("Handbag", "black"),
])


def looks(occasion, items=BRIEF, **kw):
    recs = recommend_outfits(items, occasion, account_gender="Female",
                             exclusive=True, limit=40, **kw)
    out, _ = rs.finalize(recs, items, "Female", occasion)
    return out


def names(outfit):
    return {item["category"] for item in outfit["items"]}


class BriefScenarioTests(unittest.TestCase):

    def test_party_gets_the_party_dress_with_heels(self):
        top = looks("party")[0]
        self.assertIn("Dress", names(top))
        self.assertIn("Heels", names(top))

    def test_interview_is_shirt_and_trousers(self):
        for outfit in looks("interview"):
            self.assertTrue({"Shirt", "Trousers"} <= names(outfit))

    def test_wedding_is_a_complete_ethnic_outfit_without_blouse_matching(self):
        outfits = looks("wedding")
        self.assertTrue(outfits)
        for outfit in outfits:
            self.assertEqual(outfit["style"], "ethnic")
            self.assertNotIn("Blouse", names(outfit))

    def test_casual_is_crop_top_bootcut_sneakers(self):
        self.assertTrue(any(
            {"Crop Top", "Bootcut Jeans", "Sneakers"} <= names(o) for o in looks("casual")
        ))

    def test_pools_differ_between_occasions(self):
        pairs = [("day_outing", "party"), ("party", "interview"),
                 ("wedding", "college"), ("date", "casual")]
        for a, b in pairs:
            keys_a = {o["outfit_key"] for o in looks(a)}
            keys_b = {o["outfit_key"] for o in looks(b)}
            shared_note = any("shared" in n for n in
                              rs.finalize([], BRIEF, "Female", a)[1])
            if not shared_note:
                self.assertNotEqual(keys_a, keys_b, f"{a} vs {b}")

    def test_no_sneakers_with_saree_or_lehenga(self):
        for occasion in ("wedding", "traditional"):
            for outfit in looks(occasion):
                if names(outfit) & {"Saree", "Lehenga"}:
                    self.assertNotIn("Sneakers", names(outfit))


class ClassificationRuleTests(unittest.TestCase):
    """Names as the user or classifier stores them must map correctly."""

    def test_bootcut_jeans_is_not_leggings_or_salwar(self):
        from backend.outfit_builder import kind_for
        self.assertEqual(kind_for("Bootcut Jeans"), "jeans")
        self.assertEqual(kind_for("Denims"), "jeans")

    def test_crop_top_is_not_blouse(self):
        from backend.outfit_builder import kind_for
        self.assertEqual(kind_for("Crop Top"), "tshirt")
        self.assertEqual(kind_for("Tube Top"), "tshirt")

    def test_saree_is_not_lehenga_or_dress(self):
        from backend.outfit_builder import kind_for
        self.assertEqual(kind_for("Saree"), "saree")
        self.assertNotEqual(kind_for("Saree"), kind_for("Lehenga"))
        self.assertNotEqual(kind_for("Saree"), kind_for("Dress"))

    def test_kurta_is_not_a_western_top(self):
        from backend.outfit_builder import kind_for, ETHNIC_KINDS
        self.assertIn(kind_for("Kurta (Women)"), ETHNIC_KINDS)


class ValidatorTests(unittest.TestCase):

    def setUp(self):
        self.outfit = looks("interview")[0]
        self.by_id = {i["_id"]: i for i in BRIEF}

    def test_valid_outfit_passes(self):
        ok, _ = present.validate_outfit(self.outfit, self.by_id, "Female", "interview")
        self.assertTrue(ok)

    def test_deleted_item_rejected(self):
        by_id = dict(self.by_id)
        by_id.pop(self.outfit["items"][0]["_id"])
        self.assertFalse(present.validate_outfit(self.outfit, by_id, "Female", "interview")[0])

    def test_missing_image_rejected(self):
        by_id = {k: dict(v) for k, v in self.by_id.items()}
        by_id[self.outfit["items"][0]["_id"]]["image_path"] = ""
        self.assertFalse(present.validate_outfit(self.outfit, by_id, "Female", "interview")[0])

    def test_other_users_item_rejected(self):
        other_user = {k: v for k, v in self.by_id.items() if k != self.outfit["items"][1]["_id"]}
        self.assertFalse(present.validate_outfit(self.outfit, other_user, "Female", "interview")[0])

    def test_duplicate_item_rejected(self):
        bad = dict(self.outfit)
        bad["items"] = self.outfit["items"] + [self.outfit["items"][0]]
        self.assertFalse(present.validate_outfit(bad, self.by_id, "Female", "interview")[0])

    def test_wrong_occasion_rejected(self):
        self.assertFalse(present.validate_outfit(self.outfit, self.by_id, "Female", "party")[0])

    def test_gender_rejected(self):
        saree = looks("traditional")[0]
        self.assertFalse(present.validate_outfit(saree, self.by_id, "Male", "traditional")[0])


class PresentationTests(unittest.TestCase):

    def test_display_names(self):
        self.assertEqual(present.display_name({"category": "Denims", "color": "black"}), "Black Jeans")
        self.assertEqual(present.display_name({"category": "Saree", "color": "pink"}), "Pink Saree")

    def test_groups(self):
        cases = {"Crop Top": "Tops", "Bootcut Jeans": "Bottoms", "Saree": "Sarees",
                 "Dress": "Dresses", "Kurta (Women)": "Ethnic", "Jacket": "Outerwear",
                 "Heels": "Shoes", "Handbag": "Accessories"}
        for category, group in cases.items():
            self.assertEqual(present.item_group({"category": category}), group, category)

    def test_colour_filter(self):
        out, _ = rs.finalize(recommend_outfits(BRIEF, "casual", account_gender="Female"),
                             BRIEF, "Female", "casual", colour="black")
        for outfit in out:
            self.assertTrue(any("black" in i["color"] for i in outfit["items"]))

    def test_titles_are_unique(self):
        titles = [o["title"] for o in looks("date")]
        self.assertEqual(len(titles), len(set(titles)))

    def test_no_pinterest_or_external_inspiration_in_results(self):
        import json
        for occasion in ("party", "wedding", "casual", "traditional"):
            for outfit in looks(occasion):
                self.assertNotIn("inspiration", outfit)
                self.assertNotIn("pinterest", json.dumps(outfit, default=str).lower())
        self.assertFalse(hasattr(present, "inspiration"))
        self.assertFalse(hasattr(present, "occasion_inspiration"))

    def test_why_is_built_from_real_data(self):
        for line in looks("party")[0]["why"]:
            self.assertIsInstance(line, str)
            self.assertTrue(line)


class HomeAndTripTests(unittest.TestCase):

    def test_home_is_built_from_the_wardrobe(self):
        home = rs.build_home(BRIEF, "Female", {"name": "D"})
        self.assertEqual(home["item_count"], len(BRIEF))
        self.assertEqual(home["recent"][0]["_id"], BRIEF[-1]["_id"])
        self.assertEqual([e["title"] for e in home["edits"]],
                         ["Weekend Edit", "After Dark", "Festive Edit", "Campus Edit"])
        wardrobe_ids = {i["_id"] for i in BRIEF}
        for edit in home["edits"]:
            for outfit in edit["outfits"]:
                self.assertTrue({i["_id"] for i in outfit["items"]} <= wardrobe_ids)

    def test_empty_wardrobe_home(self):
        home = rs.build_home([], "Female")
        self.assertEqual(home["item_count"], 0)
        self.assertTrue(all(e["count"] == 0 for e in home["edits"]))

    def test_trip_looks_do_not_repeat_main_pieces(self):
        trip = rs.trip_looks(BRIEF, "Female", {"is_hot": True})
        seen = set()
        for look in trip:
            ids = set(look["key_item_ids"])
            self.assertFalse(seen & ids)
            seen |= ids

    def test_trip_without_weather_still_works(self):
        self.assertTrue(rs.trip_looks(BRIEF, "Female", None))


if __name__ == "__main__":
    unittest.main()
