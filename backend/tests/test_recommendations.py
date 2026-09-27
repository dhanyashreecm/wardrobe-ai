"""
Tests for the outfit recommendation module.

Run from the project root:
    python -m unittest backend.tests.test_recommendations -v

No database or internet needed - wardrobes are built in memory.
"""
import unittest
from datetime import datetime, timedelta

from backend import outfit_builder as ob
from backend.outfit_recommendation import (
    recommend_outfits, describe_missing_pieces, infer_occasions_for_category,
    CANONICAL_OCCASIONS,
)
from backend.outfit_assignment import ACTIVITY_RULES


def wardrobe(*rows):
    return [
        {"_id": str(index), "category": category, "color": color}
        for index, (category, color) in enumerate(rows, start=1)
    ]


def names(outfit):
    return [item["category"] for item in outfit["items"]]


def all_names(outfits):
    return [names(outfit) for outfit in outfits]


class GarmentKindTests(unittest.TestCase):

    def test_kinds_from_dropdown_and_classifier_labels(self):
        cases = {
            "T-Shirt": "tshirt", "Shirt": "shirt", "Denims": "jeans",
            "Dhoti Pants": "dhoti", "dhoti_pants": "dhoti",
            "Kurta (Men)": "kurta_men", "kurta_men": "kurta_men",
            "Kurta (Women)": "kurta_women", "women_kurta": "kurta_women",
            "Leggings & Salwars": "salwar", "leggings_and_salwars": "salwar",
            "Saree": "saree", "Lehenga": "lehenga", "Blouse": "blouse",
            "Nehru Jacket": "nehru", "nehru_jackets": "nehru",
            "Mojaris (Women)": "mojari", "Neck Chain": "necklace",
            "Finger Ring": "ring", "Petticoat": "petticoat",
        }
        for category, kind in cases.items():
            self.assertEqual(ob.kind_for(category), kind, category)

    def test_leggings_are_a_bottom_not_a_dress(self):
        self.assertEqual(ob.role_for("Leggings & Salwars"), ob.BOTTOM)

    def test_dhoti_pants_are_not_office_wear(self):
        self.assertNotIn("office", infer_occasions_for_category("Dhoti Pants"))

    def test_tshirt_is_not_office_wear(self):
        self.assertNotIn("office", infer_occasions_for_category("T-Shirt"))
        self.assertIn("office", infer_occasions_for_category("Shirt"))


class PairingRuleTests(unittest.TestCase):

    def test_sherwani_never_with_jeans(self):
        items = wardrobe(("Sherwani", "gold"), ("Denims", "blue"),
                         ("Dhoti Pants", "cream"))
        outfits = recommend_outfits(items, "wedding", account_gender="Male")
        self.assertTrue(outfits)
        for outfit in outfits:
            self.assertNotIn("Denims", names(outfit))

    def test_saree_and_lehenga_only_for_wedding_and_traditional(self):
        items = wardrobe(("Saree", "red"), ("Lehenga", "pink"), ("Blouse", "gold"))
        for occasion in CANONICAL_OCCASIONS:
            outfits = recommend_outfits(items, occasion, account_gender="Female")
            if occasion in ("wedding", "traditional"):
                self.assertTrue(outfits, occasion)
            else:
                self.assertEqual(outfits, [], occasion)

    def test_saree_comes_with_blouse(self):
        items = wardrobe(("Saree", "red"), ("Blouse", "gold"))
        outfits = recommend_outfits(items, "traditional", account_gender="Female")
        self.assertEqual(len(outfits), 1)
        self.assertEqual(outfits[0]["type"], "set")
        self.assertIn("Blouse", names(outfits[0]))

    def test_saree_without_blouse_gets_a_note(self):
        items = wardrobe(("Saree", "red"))
        outfit = recommend_outfits(items, "wedding", account_gender="Female")[0]
        self.assertTrue(any("blouse" in line.lower() for line in outfit["why"]))

    def test_blouse_is_never_paired_with_western_bottoms(self):
        items = wardrobe(("Blouse", "white"), ("Denims", "blue"), ("Skirt", "black"))
        self.assertEqual(recommend_outfits(items, "casual", account_gender="Female"), [])

    def test_petticoat_is_never_shown(self):
        items = wardrobe(("Saree", "red"), ("Blouse", "red"), ("Petticoat", "red"))
        for outfit in recommend_outfits(items, "wedding", account_gender="Female"):
            self.assertNotIn("Petticoat", names(outfit))

    def test_dupatta_only_with_suits_or_lehenga(self):
        items = wardrobe(("T-Shirt", "white"), ("Denims", "blue"),
                         ("Kurta (Women)", "yellow"), ("Palazzos", "white"),
                         ("Dupatta", "yellow"))
        for outfit in recommend_outfits(items, "casual", account_gender="Female"):
            if "Dupatta" in names(outfit):
                self.assertIn("Kurta (Women)", names(outfit))
                self.assertIn("Palazzos", names(outfit))

    def test_mojaris_only_with_ethnic_or_fusion(self):
        items = wardrobe(("T-Shirt", "white"), ("Denims", "blue"),
                         ("Mojaris (Men)", "brown"))
        outfit = recommend_outfits(items, "casual", account_gender="Male")[0]
        self.assertNotIn("Mojaris (Men)", names(outfit))

    def test_belt_only_with_western_bottoms(self):
        items = wardrobe(("Kurta (Men)", "white"), ("Dhoti Pants", "cream"),
                         ("Belt", "brown"))
        outfit = recommend_outfits(items, "traditional", account_gender="Male")[0]
        self.assertNotIn("Belt", names(outfit))

    def test_at_most_two_accessories(self):
        items = wardrobe(("Shirt", "white"), ("Pant", "black"), ("Watch", "silver"),
                         ("Bag", "black"), ("Belt", "black"), ("Neck Chain", "silver"))
        outfit = recommend_outfits(items, "office", account_gender="Male")[0]
        accessories = [r for r in outfit["roles"].values() if r == ob.ACCESSORY]
        self.assertLessEqual(len(accessories), 2)

    def test_clashing_colors_rejected(self):
        # yellow + green: non-neutral, 2 steps apart, warm vs cool
        items = wardrobe(("T-Shirt", "yellow"), ("Denims", "green"))
        self.assertEqual(recommend_outfits(items, "casual"), [])
        notes = describe_missing_pieces(items, "casual")
        self.assertTrue(notes and "clash" in notes[0])

    def test_whole_wardrobe_is_used_not_first_8(self):
        tops = [("T-Shirt", "white")] * 12
        items = wardrobe(*tops, ("Denims", "blue"))
        outfits = recommend_outfits(items, "casual", limit=12)
        used_tops = {outfit["items"][0]["_id"] for outfit in outfits}
        self.assertEqual(len(used_tops), 12)


class LayerAndWeatherTests(unittest.TestCase):

    def test_coat_added_only_when_cold(self):
        items = wardrobe(("T-Shirt", "white"), ("Denims", "blue"), ("Coat", "camel"))
        warm_day = recommend_outfits(items, "casual")[0]
        cold_day = recommend_outfits(items, "casual", weather={"is_cold": True})[0]
        self.assertNotIn("Coat", names(warm_day))
        self.assertIn("Coat", names(cold_day))

    def test_no_coat_when_hot(self):
        items = wardrobe(("Shirt", "white"), ("Pant", "black"), ("Blazer", "navy"))
        outfit = recommend_outfits(items, "office", weather={"is_hot": True})[0]
        self.assertNotIn("Blazer", names(outfit))

    def test_nehru_jacket_over_kurta_for_wedding(self):
        items = wardrobe(("Kurta (Men)", "cream"), ("Dhoti Pants", "white"),
                         ("Nehru Jacket", "maroon"))
        outfit = recommend_outfits(items, "wedding", account_gender="Male")[0]
        self.assertIn("Nehru Jacket", names(outfit))

    def test_shorts_rank_lower_when_cold(self):
        items = wardrobe(("T-Shirt", "white"), ("Shorts", "khaki"), ("Denims", "blue"))
        outfits = recommend_outfits(items, "casual", weather={"is_cold": True})
        self.assertIn("Denims", names(max(outfits, key=lambda o: o["score"])))


class GenderTests(unittest.TestCase):

    def test_men_never_get_womens_wear(self):
        items = wardrobe(("Saree", "red"), ("Blouse", "red"), ("Shirt", "white"),
                         ("Pant", "black"))
        for outfit in recommend_outfits(items, "office", account_gender="Male"):
            self.assertNotIn("Saree", names(outfit))


class HistoryAndFeedbackTests(unittest.TestCase):

    def setUp(self):
        self.items = wardrobe(("Shirt", "white"), ("Shirt", "light blue"),
                              ("Pant", "black"))
        self.now = datetime(2026, 9, 27, 12, 0)

    def _outfit_with(self, outfits, shirt_id):
        return next(o for o in outfits if shirt_id in o["key_item_ids"])

    def test_recently_worn_ranks_lower(self):
        base = recommend_outfits(self.items, "office", now=self.now)
        worn_key = self._outfit_with(base, "1")["outfit_key"]
        history = [{"item_ids": ["1", "3"], "outfit_key": worn_key,
                    "worn_at": self.now - timedelta(days=1)}]
        after = recommend_outfits(self.items, "office", wear_history=history, now=self.now)
        self.assertLess(self._outfit_with(after, "1")["score"],
                        self._outfit_with(base, "1")["score"])
        self.assertTrue(any("recently" in line for line in
                            self._outfit_with(after, "1")["why"]))

    def test_old_wear_has_no_penalty(self):
        base = recommend_outfits(self.items, "office", now=self.now)
        history = [{"item_ids": ["1"], "outfit_key": "x",
                    "worn_at": self.now - timedelta(days=20)}]
        after = recommend_outfits(self.items, "office", wear_history=history, now=self.now)
        self.assertEqual(self._outfit_with(after, "1")["score"],
                         self._outfit_with(base, "1")["score"])

    def test_disliked_outfit_never_returned(self):
        base = recommend_outfits(self.items, "office")
        key = self._outfit_with(base, "1")["outfit_key"]
        after = recommend_outfits(self.items, "office", feedback={key: "dislike"})
        self.assertNotIn(key, [o["outfit_key"] for o in after])

    def test_liked_outfit_gets_boost(self):
        base = recommend_outfits(self.items, "office")
        outfit = self._outfit_with(base, "2")
        after = recommend_outfits(self.items, "office",
                                  feedback={outfit["outfit_key"]: "like"})
        liked = self._outfit_with(after, "2")
        self.assertTrue(liked["liked"])
        self.assertGreater(liked["score"], outfit["score"])

    def test_outfit_key_ignores_accessories(self):
        items = self.items + [{"_id": "9", "category": "Watch", "color": "silver"}]
        outfit = recommend_outfits(items, "office")[0]
        self.assertNotIn("9", outfit["outfit_key"].split("|"))


MIXED_WARDROBE = wardrobe(
    ("Kurta (Women)", "yellow"), ("Kurta (Women)", "white"),
    ("Leggings & Salwars", "white"), ("Palazzos", "green"), ("Saree", "red"),
    ("Blouse", "gold"), ("Lehenga", "pink"), ("Dress", "navy"), ("Dress", "red"),
    ("Skirt", "black"), ("T-Shirt", "white"), ("T-Shirt", "black"),
    ("Shirt", "light blue"), ("Shirt", "white"), ("Denims", "blue"),
    ("Pant", "black"), ("Pant", "beige"), ("Shorts", "khaki"), ("Gown", "wine"),
)


class NoRepetitionTests(unittest.TestCase):

    def _keys(self, occasion, activity=None):
        return [
            outfit["outfit_key"] for outfit in recommend_outfits(
                MIXED_WARDROBE, occasion, account_gender="Female",
                activity=activity, exclusive=True, limit=50,
            )
        ]

    def test_no_outfit_repeats_across_occasions(self):
        seen = {}
        for occasion in CANONICAL_OCCASIONS:
            for key in self._keys(occasion):
                self.assertNotIn(key, seen, f"{occasion} repeats {seen.get(key)}")
                seen[key] = occasion

    def test_every_occasion_with_clothes_gets_outfits(self):
        for occasion in CANONICAL_OCCASIONS:
            self.assertTrue(self._keys(occasion), occasion)

    def test_no_outfit_repeats_across_activities(self):
        seen = {}
        for activity in ACTIVITY_RULES:
            keys = self._keys("casual", activity)
            if not keys:
                continue
            notes = []
            recommend_outfits(MIXED_WARDROBE, "casual", account_gender="Female",
                              activity=activity, exclusive=True, notes_out=notes)
            if any("shared" in note for note in notes):
                continue  # honest fallback, flagged to the user
            for key in keys:
                self.assertNotIn(key, seen, f"{activity} repeats {seen.get(key)}")
                seen[key] = activity

    def test_sports_only_uses_sportswear(self):
        for outfit in recommend_outfits(MIXED_WARDROBE, "casual",
                                        account_gender="Female", activity="sports"):
            for item in outfit["items"]:
                self.assertNotIn(item["category"], ("Shirt", "Denims", "Kurta (Women)"))

    def test_formal_event_has_no_tshirts_or_shorts(self):
        for outfit in recommend_outfits(MIXED_WARDROBE, "party",
                                        account_gender="Female", activity="formal_event"):
            for item in outfit["items"]:
                self.assertNotIn(item["category"], ("T-Shirt", "Shorts", "Denims"))

    def test_same_request_gives_same_answer(self):
        self.assertEqual(self._keys("college"), self._keys("college"))


class EthnicWesternSeparationTests(unittest.TestCase):

    ITEMS = wardrobe(
        ("Crop Top", "charcoal"), ("Blouse", "gold"), ("Lehenga", "red"),
        ("Kurta (Women)", "yellow"), ("Denims", "blue"), ("Palazzos", "white"),
        ("Saree", "green"), ("Gown", "wine"), ("Dress", "navy"), ("Skirt", "black"),
    )

    def test_traditional_is_ethnic_only(self):
        for exclusive in (True, False):
            for outfit in recommend_outfits(self.ITEMS, "traditional",
                                            account_gender="Female",
                                            exclusive=exclusive, limit=50):
                self.assertEqual(outfit["style"], "ethnic", names(outfit))

    def test_crop_top_is_never_used_as_a_blouse(self):
        for occasion in CANONICAL_OCCASIONS:
            for outfit in recommend_outfits(self.ITEMS, occasion,
                                            account_gender="Female", limit=50):
                if "Crop Top" in names(outfit):
                    self.assertEqual(outfit["style"], "western", names(outfit))
                    self.assertNotIn("Lehenga", names(outfit))
                    self.assertNotIn("Saree", names(outfit))

    def test_sets_use_a_real_blouse(self):
        for outfit in recommend_outfits(self.ITEMS, "wedding", account_gender="Female"):
            if "Lehenga" in names(outfit) or "Saree" in names(outfit):
                self.assertIn("Blouse", names(outfit))


if __name__ == "__main__":
    unittest.main()
