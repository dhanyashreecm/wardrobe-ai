"""
Gender-separated wardrobe: one catalogue, enforced everywhere.

    python -m unittest backend.tests.test_gender_catalog -v
"""
import unittest

from backend import category_catalog as cc
from backend import inspiration
from backend import outfit_builder as ob
from backend import outfit_presentation as present
from backend import recommend_service as rs
from backend import item_recommender as ir
from backend.category_gender import item_allowed_for_account
from backend.outfit_recommendation import recommend_outfits, infer_occasions_for_category

WOMEN_ONLY = ["Saree", "Casual Saree", "Wedding Saree", "Lehenga", "Blouse", "Salwar", "Salwar Suit",
              "Dupatta", "Skirt", "Dress", "Crop Top", "Heels", "Anarkali", "Kurta (Women)", "Leggings"]
MEN_ONLY = ["Sherwani", "Kurta (Men)", "Kurta Set (Men)", "Nehru Jacket", "Dhoti Pants", "Tie",
            "Bow Tie", "Mojaris (Men)", "Formal Shirt", "Polo Shirt", "Chinos"]


def flat(gender):
    return [c["value"] for s in cc.categories_for(gender) for c in s["categories"]]


def wardrobe(*rows, gender=None):
    items = []
    for i, (cat, col) in enumerate(rows, start=1):
        item = {"_id": str(i), "category": cat, "color": col, "image_path": f"https://x/{i}.jpg"}
        if gender:
            item["gender"] = gender
        items.append(item)
    return items


def names(outfit):
    return [i["category"] for i in outfit["items"]]


class CategorySeparation(unittest.TestCase):

    def test_men_list_has_no_womens_categories(self):
        men = flat("male")
        for cat in WOMEN_ONLY:
            self.assertNotIn(cat, men)
        for cat in MEN_ONLY:
            self.assertIn(cat, men)

    def test_women_list_has_no_mens_only_categories(self):
        women = flat("female")
        for cat in MEN_ONLY:
            self.assertNotIn(cat, women)
        for cat in WOMEN_ONLY:
            self.assertIn(cat, women)

    def test_shared_categories_in_both(self):
        for cat in ["T-Shirt", "Shirt", "Jeans", "Trousers", "Shorts", "Jacket", "Blazer",
                    "Coat", "Sneakers", "Boots", "Sandals", "Sports Jersey", "Track Pants", "Watch", "Belt"]:
            self.assertTrue(cc.is_valid_for(cat, "male"), cat)
            self.assertTrue(cc.is_valid_for(cat, "female"), cat)

    def test_backend_rejects_cross_gender(self):
        self.assertFalse(cc.is_valid_for("Saree", "male"))
        self.assertFalse(cc.is_valid_for("Lehenga", "Male"))
        self.assertFalse(cc.is_valid_for("Sherwani", "female"))
        self.assertFalse(cc.is_valid_for("Made Up Thing", "male"))
        self.assertFalse(cc.is_valid_for("Shirt", None))  # no gender -> nothing

    def test_no_gender_no_categories(self):
        self.assertEqual(cc.categories_for(None), [])
        self.assertEqual(cc.categories_for("other"), [])

    def test_every_catalogue_value_is_understood_by_the_recommender(self):
        for value in cc.CATALOG:
            self.assertIsNotNone(ob.kind_for(value), value)

    def test_legacy_names_still_work(self):
        self.assertTrue(cc.is_valid_for("Denims", "male"))
        self.assertEqual(cc.canonical_for_gender("Denims", "male"), "Jeans")
        self.assertEqual(cc.canonical_for_gender("Hand Cuff", "female"), "Bangles")
        self.assertEqual(cc.canonical_for_gender("Hand Cuff", "male"), "Bracelet")
        self.assertTrue(cc.is_valid_for("Leggings & Salwars", "female"))
        self.assertFalse(cc.is_valid_for("Leggings & Salwars", "male"))

    def test_mens_categories_behave(self):
        expected = {
            "Sports Jersey": ob.TOP, "Track Pants": ob.BOTTOM, "Jeans": ob.BOTTOM,
            "Trousers": ob.BOTTOM, "Shorts": ob.BOTTOM, "Shirt": ob.TOP, "T-Shirt": ob.TOP,
            "Jacket": ob.LAYER, "Blazer": ob.LAYER, "Coat": ob.LAYER, "Kurta (Men)": ob.TOP,
            "Sherwani": ob.TOP, "Nehru Jacket": ob.LAYER, "Dhoti Pants": ob.BOTTOM,
            "Formal Shoes": ob.FOOTWEAR, "Sneakers": ob.FOOTWEAR, "Sports Shoes": ob.FOOTWEAR,
            "Belt": ob.ACCESSORY, "Watch": ob.ACCESSORY, "Denim Jacket": ob.LAYER,
        }
        for cat, role in expected.items():
            self.assertTrue(cc.is_valid_for(cat, "male"), cat)
            self.assertEqual(ob.role_for(cat), role, cat)

    def test_category_accuracy(self):
        self.assertEqual(ob.kind_for("Bootcut Jeans"), "jeans")
        self.assertEqual(ob.kind_for("Leggings"), "leggings")
        self.assertEqual(ob.kind_for("Crop Top"), "tshirt")
        self.assertEqual(ob.kind_for("Saree"), "saree")
        self.assertEqual(ob.kind_for("Lehenga"), "lehenga")
        self.assertEqual(ob.kind_for("Shorts"), "shorts")
        self.assertEqual(ob.kind_for("Track Pants"), "pant")
        self.assertEqual(ob.kind_for("Sports Jersey"), "tshirt")


class RecommendationGender(unittest.TestCase):

    MIXED = wardrobe(("Saree", "red"), ("Lehenga", "pink"), ("Dress", "black"), ("Heels", "gold"),
                     ("Sherwani", "cream"), ("Dhoti Pants", "white"), ("Kurta (Men)", "white"),
                     ("Shirt", "white"), ("Trousers", "black"), ("Formal Shoes", "black"),
                     ("T-Shirt", "white"), ("Jeans", "blue"), ("Sneakers", "white"), ("Tie", "navy"))

    def test_male_recommendations_only_male(self):
        for occ in ("casual", "college", "party", "interview", "wedding", "traditional"):
            for o in recommend_outfits(self.MIXED, occ, account_gender="Male", limit=50):
                for cat in names(o):
                    self.assertTrue(cc.is_valid_for(cat, "male"), (occ, cat))

    def test_female_recommendations_only_female(self):
        for occ in ("casual", "college", "party", "interview", "wedding", "traditional"):
            for o in recommend_outfits(self.MIXED, occ, account_gender="Female", limit=50):
                for cat in names(o):
                    self.assertTrue(cc.is_valid_for(cat, "female"), (occ, cat))
                self.assertNotIn("Tie", names(o))

    def test_explicit_item_gender_is_a_hard_filter(self):
        shirt = {"_id": "1", "category": "Shirt", "gender": "female"}
        self.assertFalse(item_allowed_for_account(shirt, "Male"))
        self.assertTrue(item_allowed_for_account(shirt, "Female"))

    def test_validator_rejects_other_gender_item(self):
        items = wardrobe(("Shirt", "white"), ("Jeans", "blue"), gender="female")
        outfit = {"occasion": "casual", "items": items,
                  "roles": {"1": ob.TOP, "2": ob.BOTTOM}}
        by_id = {i["_id"]: i for i in items}
        self.assertFalse(present.validate_outfit(outfit, by_id, "Male", "casual")[0])

    def test_item_tabs_respect_gender(self):
        tops = ir.recommend_items(self.MIXED, "wedding", "Ethnic", account_gender="Male")
        self.assertTrue(all(cc.is_valid_for(r["item"]["category"], "male") for r in tops))


MEN = wardrobe(
    ("T-Shirt", "white"), ("Sports Jersey", "blue"), ("Casual Shirt", "navy"), ("Formal Shirt", "white"),
    ("Shirt", "black"), ("Jeans", "blue"), ("Chinos", "beige"), ("Formal Trousers", "grey"),
    ("Track Pants", "black"), ("Shorts", "khaki"), ("Blazer", "navy"), ("Jacket", "black"),
    ("Kurta (Men)", "cream"), ("Sherwani", "gold"), ("Nehru Jacket", "maroon"), ("Dhoti Pants", "white"),
    ("Sneakers", "white"), ("Sports Shoes", "grey"), ("Formal Shoes", "black"), ("Mojaris (Men)", "gold"),
    ("Belt", "black"), ("Watch", "silver"), ("Tie", "navy"), ("Cap", "black"),
    gender="male",
)


class MensOccasions(unittest.TestCase):

    def looks(self, occ):
        recs = recommend_outfits(MEN, occ, account_gender="Male", limit=60)
        out, _ = rs.finalize(recs, MEN, "Male", occ, limit=60)
        self.assertEqual(len(out), len(recs), occ)  # engine output passes the validator
        return out

    def test_interview_is_formal(self):
        outs = self.looks("interview")
        self.assertTrue(outs)
        for o in outs:
            n = names(o)
            for bad in ("Sports Jersey", "Track Pants", "Shorts", "T-Shirt", "Sneakers", "Sports Shoes",
                        "Cap", "Casual Shirt", "Kurta (Men)"):
                self.assertNotIn(bad, n)

    def test_party_is_not_formal_workwear(self):
        for o in self.looks("party"):
            for bad in ("Formal Shirt", "Formal Trousers", "Track Pants", "Sports Jersey", "Sherwani"):
                self.assertNotIn(bad, names(o))

    def test_wedding_is_traditional(self):
        outs = self.looks("wedding")
        self.assertTrue(outs)
        for o in outs:
            self.assertEqual(o["style"], "ethnic")
            for bad in ("Sneakers", "Sports Shoes", "Track Pants", "Shorts", "Jeans", "Cap", "Tie"):
                self.assertNotIn(bad, names(o))

    def test_college_is_casual(self):
        for o in self.looks("college"):
            for bad in ("Formal Shirt", "Formal Trousers", "Sherwani", "Tie"):
                self.assertNotIn(bad, names(o))

    def test_occasions_change_results(self):
        seen = {occ: {o["outfit_key"] for o in recommend_outfits(MEN, occ, account_gender="Male", exclusive=True)}
                for occ in ("casual", "college", "interview", "party", "wedding", "sports")}
        non_empty = [s for s in seen.values() if s]
        self.assertGreaterEqual(len(non_empty), 4)
        for a in seen:
            for b in seen:
                if a < b and seen[a] and seen[b]:
                    self.assertFalse(seen[a] & seen[b], (a, b))

    def test_formal_and_casual_garments_have_the_right_occasions(self):
        self.assertEqual(infer_occasions_for_category("Formal Trousers"), {"office", "interview"})
        self.assertNotIn("interview", infer_occasions_for_category("Casual Shirt"))
        self.assertNotIn("interview", infer_occasions_for_category("Sports Jersey"))

    def test_colour_scoring_prefers_harmony(self):
        items = wardrobe(("Shirt", "white"), ("Shirt", "orange"), ("Trousers", "navy"), gender="male")
        ranked = recommend_outfits(items, "office", account_gender="Male")
        self.assertEqual(ranked[0]["items"][0]["color"], "white")


class Inspiration(unittest.TestCase):

    IMAGES = [
        {"id": "m1", "gender": "male", "occasion": "party", "caption": "Black Shirt", "src": "https://img/m1.jpg"},
        {"id": "f1", "gender": "female", "occasion": "party", "caption": "Red Dress", "src": "https://img/f1.jpg"},
        {"id": "m2", "gender": "male", "occasion": "wedding", "caption": "Kurta", "src": "https://img/m2.jpg"},
        {"id": "f2", "gender": "female", "occasion": "wedding", "caption": "Saree", "src": "https://img/f2.jpg"},
    ]

    def test_male_gets_only_male(self):
        out = inspiration.for_account("male", "party", images=self.IMAGES)
        self.assertEqual([i["id"] for i in out], ["m1"])

    def test_female_gets_only_female(self):
        out = inspiration.for_account("female", "wedding", images=self.IMAGES)
        self.assertEqual([i["id"] for i in out], ["f2"])

    def test_no_gender_no_pictures(self):
        self.assertEqual(inspiration.for_account(None, "party", images=self.IMAGES), [])

    def test_only_picture_and_caption_reach_the_browser(self):
        for image in inspiration.for_account("male", "party", images=self.IMAGES):
            self.assertEqual(set(image), {"id", "caption", "url"})
            self.assertNotIn("pinterest", str(image).lower())

    def test_local_file_is_gender_locked(self):
        self.assertIsNone(inspiration.local_file("f1", "male", images=self.IMAGES))

    def test_never_serves_outside_the_project(self):
        bad = [{"id": "x", "gender": "male", "occasion": "party", "src": "project:../../etc/passwd"}]
        self.assertIsNone(inspiration.local_file("x", "male", images=bad))


class InspirationLibrary(unittest.TestCase):
    """The curated-picture pipeline: folders -> checks -> list."""

    def setUp(self):
        import tempfile
        from PIL import Image
        self.root = tempfile.mkdtemp()
        def save(rel, size):
            import os
            path = os.path.join(self.root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            Image.new("RGB", size, (120, 80, 60)).save(path)
        save("male/party/look1.jpg", (800, 1000))
        save("male/formal/look2.jpg", (600, 900))        # alias -> interview
        save("female/wedding/look3.png", (900, 1200))
        save("female/party/thumb.jpg", (60, 80))          # too small
        save("female/brunchy/look4.jpg", (800, 800))      # unknown folder

    def test_collects_by_gender_and_occasion_and_refuses_thumbnails(self):
        from backend import build_inspiration as bi
        entries, skipped = bi.collect(self.root)
        got = sorted((e["gender"], e["occasion"]) for e in entries)
        self.assertEqual(got, [("female", "wedding"), ("male", "interview"), ("male", "party")])
        reasons = " ".join(r for _, r in skipped)
        self.assertIn("too small", reasons)
        self.assertIn("unknown occasion folder", reasons)

    def test_ids_are_stable_and_gender_prefixed(self):
        from backend import build_inspiration as bi
        first, _ = bi.collect(self.root)
        second, _ = bi.collect(self.root)
        self.assertEqual([e["id"] for e in first], [e["id"] for e in second])
        for e in first:
            self.assertTrue(e["id"].startswith(e["gender"] + "-"))

    def test_cloud_list_is_served_by_gender(self):
        cloud = [{"id": "male-party-1", "gender": "male", "occasion": "party",
                  "url": "https://res.cloudinary.com/demo/image/upload/c_limit,w_720/x.jpg"},
                 {"id": "female-party-1", "gender": "female", "occasion": "party",
                  "url": "https://res.cloudinary.com/demo/image/upload/c_limit,w_720/y.jpg"}]
        male = inspiration.for_account("male", "party", images=cloud)
        self.assertEqual([i["id"] for i in male], ["male-party-1"])
        self.assertTrue(male[0]["url"].startswith("https://res.cloudinary.com/"))


FEMALE_WARDROBE = wardrobe(
    ("T-Shirt", "white"), ("Crop Top", "black"), ("Shirt", "white"), ("Top", "pink"),
    ("Jeans", "blue"), ("Trousers", "black"), ("Skirt", "beige"), ("Shorts", "khaki"),
    ("Dress", "navy"), ("Blazer", "grey"), ("Track Pants", "black"), ("Sports T-Shirt", "grey"),
    ("Saree", "red"), ("Lehenga", "pink"), ("Salwar Suit", "green"), ("Kurta (Women)", "yellow"),
    ("Palazzos", "cream"), ("Sneakers", "white"), ("Heels", "gold"), ("Formal Shoes", "black"),
    ("Flats", "beige"), ("Mojaris (Women)", "gold"), ("Earrings", "gold"), ("Bangles", "gold"),
    ("Clutch", "gold"), ("Handbag", "black"), ("Watch", "silver"), ("Belt", "brown"),
    gender="female",
)
WESTERN = ("interview", "party", "college", "casual", "day_outing", "date")
TRADITIONAL = ("wedding", "traditional")


class BothGendersAllOccasions(unittest.TestCase):
    """The eight occasions, for a men's and a women's wardrobe."""

    def run_all(self, items, gender):
        results = {}
        for occ in WESTERN + TRADITIONAL:
            recs = recommend_outfits(items, occ, account_gender=gender, limit=60, exclusive=True)
            final, _ = rs.finalize(recs, items, gender, occ, limit=60)
            self.assertEqual(len(final), len(recs), (gender, occ))  # validator agrees with engine
            results[occ] = final
        return results

    def check(self, items, gender):
        results = self.run_all(items, gender)
        for occ, outs in results.items():
            for o in outs:
                for cat in names(o):
                    self.assertTrue(cc.is_valid_for(cat, gender), (occ, cat))
                expected = "ethnic" if occ in TRADITIONAL else "western"
                self.assertEqual(o["style"], expected, (occ, names(o)))
        filled = {occ: {o["outfit_key"] for o in outs} for occ, outs in results.items() if outs}
        self.assertGreaterEqual(len(filled), 6, sorted(filled))
        occs = list(filled)
        for i, a in enumerate(occs):
            for b in occs[i + 1:]:
                self.assertFalse(filled[a] & filled[b], (gender, a, b))
        return results

    def test_men(self):
        results = self.check(MEN, "male")
        for o in results["interview"]:
            self.assertTrue({"Formal Shoes"} & set(names(o)))

    def test_women(self):
        results = self.check(FEMALE_WARDROBE, "female")
        for o in results["wedding"] + results["traditional"]:
            for bad in ("Sneakers", "Jeans", "Crop Top", "Belt", "Track Pants"):
                self.assertNotIn(bad, names(o))
        for o in results["interview"]:
            for bad in ("Crop Top", "Track Pants", "Sports T-Shirt", "Sneakers", "Shorts"):
                self.assertNotIn(bad, names(o))
        for o in results["party"]:
            self.assertNotIn("Track Pants", names(o))


if __name__ == "__main__":
    unittest.main()
