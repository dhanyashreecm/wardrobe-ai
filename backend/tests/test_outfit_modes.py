"""
Traditional vs Western modes, the final validator, gender and ownership.

    python -m unittest backend.tests.test_outfit_modes -v

In-memory wardrobes only - never touches a real account.
"""
import unittest

from backend import outfit_builder as ob
from backend import outfit_presentation as present
from backend import recommend_service as rs
from backend import item_recommender as ir
from backend.outfit_recommendation import recommend_outfits, CANONICAL_OCCASIONS


def wardrobe(*rows):
    return [
        {"_id": str(i), "category": c, "color": col, "image_path": f"https://res.cloudinary.com/x/{i}.jpg"}
        for i, (c, col) in enumerate(rows, start=1)
    ]


def names(outfit):
    return [item["category"] for item in outfit["items"]]


class CategoryTaxonomy(unittest.TestCase):
    """The category a photo is given always maps to the right garment kind."""

    def test_confusable_categories_stay_distinct(self):
        cases = {
            "Saree": "saree", "Lehenga": "lehenga", "Skirt": "skirt",
            "Jeans": "jeans", "Denims": "jeans", "Leggings": "leggings",
            "Leggings & Salwars": "salwar", "Salwar": "salwar",
            "Crop Top": "tshirt", "Blouse": "blouse",
            "Shirt": "shirt", "Kurta (Women)": "kurta_women", "Kurta (Men)": "kurta_men",
            "Salwar Suit": "ethnic_set", "Kurta Set": "ethnic_set", "Suit": "blazer",
            "Kurta Pajama": "kurta", "Pajama": "pajama", "Sharara": "palazzo",
            "Track Pants": "pant", "Anarkali": "anarkali",
        }
        for category, kind in cases.items():
            self.assertEqual(ob.kind_for(category), kind, category)

    def test_modes(self):
        for kind in ("saree", "lehenga", "ethnic_set", "kurta_women", "salwar", "dhoti"):
            self.assertEqual(ob.garment_mode(kind), "traditional", kind)
        for kind in ("tshirt", "jeans", "dress", "skirt", "blazer"):
            self.assertEqual(ob.garment_mode(kind), "western", kind)
        self.assertIsNone(ob.garment_mode("leggings"))


def outfit_of(items, roles, occasion):
    """A hand-made outfit, to check the validator on its own."""
    return {"occasion": occasion, "items": items,
            "roles": {item["_id"]: role for item, role in zip(items, roles)}}


def check(items, roles, occasion, gender="Female"):
    by_id = {i["_id"]: i for i in items}
    return present.validate_outfit(outfit_of(items, roles, occasion), by_id, gender, occasion)


T, B, O, F, A, S = ob.TOP, ob.BOTTOM, ob.ONE_PIECE, ob.FOOTWEAR, ob.ACCESSORY, ob.SET_PART


class ValidatorTraditional(unittest.TestCase):

    def test_saree_plus_accessories_is_valid(self):
        items = wardrobe(("Saree", "red"), ("Earrings", "gold"), ("Bangles", "gold"),
                         ("Clutch", "gold"), ("Heels", "gold"))
        ok, why = check(items, [O, A, A, A, F], "wedding")
        self.assertTrue(ok, why)

    def test_saree_plus_jeans_is_invalid(self):
        items = wardrobe(("Saree", "red"), ("Jeans", "blue"))
        self.assertFalse(check(items, [O, B], "wedding")[0])

    def test_saree_plus_crop_top_is_invalid(self):
        items = wardrobe(("Saree", "red"), ("Crop Top", "black"))
        self.assertFalse(check(items, [O, T], "traditional")[0])

    def test_saree_plus_sneakers_for_wedding_is_invalid(self):
        items = wardrobe(("Saree", "red"), ("Sneakers", "white"))
        ok, why = check(items, [O, F], "wedding")
        self.assertFalse(ok)
        self.assertIn("sneakers", why)

    def test_lehenga_plus_tshirt_is_invalid(self):
        items = wardrobe(("Lehenga", "pink"), ("T-Shirt", "white"))
        self.assertFalse(check(items, [O, T], "wedding")[0])

    def test_salwar_suit_plus_accessories_is_valid(self):
        items = wardrobe(("Salwar Suit", "green"), ("Dupatta", "gold"), ("Earrings", "gold"),
                         ("Mojaris (Women)", "gold"))
        ok, why = check(items, [O, A, A, F], "traditional")
        self.assertTrue(ok, why)

    def test_kurta_salwar_plus_accessories_is_valid(self):
        items = wardrobe(("Kurta (Women)", "yellow"), ("Salwar", "white"), ("Earrings", "gold"))
        ok, why = check(items, [T, B, A], "traditional")
        self.assertTrue(ok, why)

    def test_salwar_plus_jeans_style_mix_is_invalid(self):
        items = wardrobe(("Kurta (Women)", "yellow"), ("Jeans", "blue"))
        self.assertFalse(check(items, [T, B], "traditional")[0])

    def test_separate_blouse_is_never_shown(self):
        items = wardrobe(("Saree", "red"), ("Blouse", "gold"))
        self.assertFalse(check(items, [O, S], "wedding")[0])

    def test_belt_with_traditional_is_invalid(self):
        items = wardrobe(("Saree", "red"), ("Belt", "brown"))
        self.assertFalse(check(items, [O, A], "wedding")[0])


class ValidatorWestern(unittest.TestCase):

    def test_top_jeans_shoes_valid(self):
        items = wardrobe(("Crop Top", "white"), ("Jeans", "blue"), ("Sneakers", "white"),
                         ("Watch", "silver"))
        ok, why = check(items, [T, B, F, A], "college")
        self.assertTrue(ok, why)

    def test_shirt_trousers_formal_valid(self):
        items = wardrobe(("Shirt", "white"), ("Trousers", "black"), ("Heels", "black"))
        ok, why = check(items, [T, B, F], "interview")
        self.assertTrue(ok, why)

    def test_saree_for_college_is_invalid(self):
        items = wardrobe(("Saree", "red"),)
        self.assertFalse(check(items, [O], "college")[0])

    def test_mojaris_with_western_invalid(self):
        items = wardrobe(("T-Shirt", "white"), ("Jeans", "blue"), ("Mojaris (Women)", "gold"))
        self.assertFalse(check(items, [T, B, F], "casual")[0])

    def test_dupatta_with_western_invalid(self):
        items = wardrobe(("T-Shirt", "white"), ("Jeans", "blue"), ("Dupatta", "pink"))
        self.assertFalse(check(items, [T, B, A], "casual")[0])

    def test_two_tops_invalid(self):
        items = wardrobe(("T-Shirt", "white"), ("Shirt", "blue"), ("Jeans", "blue"))
        self.assertFalse(check(items, [T, T, B], "casual")[0])

    def test_incomplete_invalid(self):
        items = wardrobe(("T-Shirt", "white"),)
        self.assertFalse(check(items, [T], "casual")[0])


class GenderAndOwnership(unittest.TestCase):

    def test_other_gender_item_rejected(self):
        items = wardrobe(("Saree", "red"),)
        self.assertFalse(check(items, [O], "wedding", gender="Male")[0])

    def test_item_not_in_this_users_wardrobe_rejected(self):
        mine = wardrobe(("T-Shirt", "white"), ("Jeans", "blue"))
        someone_elses = {"_id": "999", "category": "Sneakers", "color": "white",
                         "image_path": "https://x/y.jpg"}
        outfit = outfit_of(mine + [someone_elses], [T, B, F], "casual")
        by_id = {i["_id"]: i for i in mine}
        self.assertFalse(present.validate_outfit(outfit, by_id, "Female", "casual")[0])

    def test_engine_only_uses_own_items_and_gender(self):
        items = wardrobe(("Sherwani", "gold"), ("Dhoti Pants", "cream"), ("Saree", "red"),
                         ("Shirt", "white"), ("Pant", "black"), ("Heels", "black"))
        own = {i["_id"] for i in items}
        for occ in CANONICAL_OCCASIONS:
            for outfit in recommend_outfits(items, occ, account_gender="Male", limit=50):
                self.assertTrue({i["_id"] for i in outfit["items"]} <= own)
                self.assertNotIn("Saree", names(outfit))
                self.assertNotIn("Heels", names(outfit))


BIG = wardrobe(
    ("Saree", "red"), ("Saree", "cream"), ("Lehenga", "pink"), ("Blouse", "gold"),
    ("Anarkali", "green"), ("Salwar Suit", "blue"), ("Kurta (Women)", "yellow"),
    ("Salwar", "white"), ("Palazzos", "cream"), ("Leggings", "black"),
    ("Crop Top", "black"), ("T-Shirt", "white"), ("Shirt", "white"),
    ("Jeans", "blue"), ("Trousers", "black"), ("Skirt", "beige"), ("Dress", "navy"),
    ("Sneakers", "white"), ("Heels", "gold"), ("Mojaris (Women)", "gold"), ("Boots", "black"),
    ("Earrings", "gold"), ("Bangles", "gold"), ("Clutch", "gold"), ("Dupatta", "pink"),
    ("Watch", "silver"), ("Belt", "brown"), ("Handbag", "black"),
)


class EngineModes(unittest.TestCase):

    def final(self, occasion):
        recs = recommend_outfits(BIG, occasion, account_gender="Female", limit=60)
        out, _ = rs.finalize(recs, BIG, "Female", occasion, limit=60)
        # the engine's own output must already pass the validator
        self.assertEqual(len(out), len(recs), occasion)
        return out

    def test_traditional_occasions_only_ethnic(self):
        for occ in ("wedding", "traditional"):
            outs = self.final(occ)
            self.assertTrue(outs, occ)
            for outfit in outs:
                self.assertEqual(outfit["style"], "ethnic", names(outfit))
                for bad in ("Jeans", "Crop Top", "T-Shirt", "Sneakers", "Boots", "Belt", "Blouse"):
                    self.assertNotIn(bad, names(outfit))

    def test_saree_recommended_as_saree_plus_accessories(self):
        outs = [o for o in self.final("wedding") if "Saree" in names(o)]
        self.assertTrue(outs)
        for outfit in outs:
            garments = [r for r in outfit["roles"].values() if r in (T, B, O)]
            self.assertEqual(garments, [O])
            self.assertLessEqual(list(outfit["roles"].values()).count(A), 3)

    def test_western_occasions_only_western(self):
        for occ in ("casual", "college", "interview", "day_outing", "date", "party"):
            for outfit in self.final(occ):
                self.assertEqual(outfit["style"], "western", (occ, names(outfit)))
                for bad in ("Saree", "Lehenga", "Anarkali", "Salwar Suit", "Kurta (Women)",
                            "Mojaris (Women)", "Dupatta"):
                    self.assertNotIn(bad, names(outfit))

    def test_western_look_is_top_bottom_or_dress_with_shoes(self):
        for outfit in self.final("college"):
            roles = list(outfit["roles"].values())
            self.assertTrue(O in roles or (T in roles and B in roles))
            self.assertIn(F, roles)

    def test_leggings_work_in_both_modes(self):
        trad = [names(o) for o in self.final("traditional")]
        self.assertTrue(any("Leggings" in n and "Kurta (Women)" in n for n in trad))

    def test_item_tabs_respect_modes(self):
        college_shoes = [r["item"]["category"] for r in
                         ir.recommend_items(BIG, "college", "Shoes", account_gender="Female")]
        self.assertNotIn("Mojaris (Women)", college_shoes)
        wedding_shoes = [r["item"]["category"] for r in
                         ir.recommend_items(BIG, "wedding", "Shoes", account_gender="Female")]
        self.assertNotIn("Sneakers", wedding_shoes)
        self.assertNotIn("Boots", wedding_shoes)
        college_ethnic = ir.recommend_items(BIG, "college", "Ethnic", account_gender="Female")
        self.assertEqual(college_ethnic, [])
        wedding_tops = ir.recommend_items(BIG, "wedding", "Tops", account_gender="Female")
        self.assertEqual(wedding_tops, [])

    def test_occasions_differ(self):
        seen = {}
        for occ in ("casual", "college", "interview", "date", "party", "wedding", "traditional"):
            recs = recommend_outfits(BIG, occ, account_gender="Female", exclusive=True)
            seen[occ] = {r["outfit_key"] for r in recs}
        occs = list(seen)
        for i, a in enumerate(occs):
            for b in occs[i + 1:]:
                if seen[a] and seen[b]:
                    self.assertFalse(seen[a] & seen[b], (a, b))


if __name__ == "__main__":
    unittest.main()
