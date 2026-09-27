"""
Category tabs, Sports/Workout, Full Looks, hard compatibility rules,
ownership/gender and honest empty states.

    python -m unittest discover backend/tests -v
"""
import unittest
from datetime import datetime, timedelta

from backend import item_recommender as ir
from backend import outfit_presentation as present
from backend import recommend_service as rs
from backend.outfit_recommendation import recommend_outfits


def make(rows, owner="a@x.com", start=1):
    return [
        {"_id": f"{owner[0]}{i}", "category": c, "color": col, "image_path": f"https://res.cloudinary.com/x/{i}.jpg",
         "user_email": owner}
        for i, (c, col) in enumerate(rows, start=start)
    ]


WOMEN = make([
    ("Crop Top", "black"), ("T-Shirt", "white"), ("Shirt", "white"), ("Blouse", "gold"),
    ("Bootcut Jeans", "blue"), ("Trousers", "beige"), ("Skirt", "black"), ("Shorts", "khaki"),
    ("Leggings", "black"), ("Track Pants", "grey"),
    ("Dress", "black"), ("Gown", "wine"),
    ("Saree", "pink"), ("Lehenga", "green"), ("Kurta (Women)", "yellow"), ("Palazzos", "white"),
    ("Dupatta", "yellow"), ("Petticoat", "pink"),
    ("Jacket", "blue"), ("Coat", "camel"), ("Blazer", "navy"),
    ("Sneakers", "white"), ("Heels", "black"), ("Flats", "gold"), ("Boots", "brown"),
    ("Mojaris (Women)", "gold"),
    ("Handbag", "black"), ("Watch", "silver"), ("Earrings", "gold"), ("Belt", "brown"),
])

MEN = make([("Sherwani", "cream"), ("Kurta (Men)", "white"), ("Dhoti Pants", "cream"),
            ("Shirt", "blue"), ("Trousers", "black"), ("Sneakers", "white"), ("Mojaris (Men)", "brown")],
           owner="m@x.com")


def items(group, occasion, gender="Female", wardrobe=WOMEN, **kw):
    return ir.recommend_items(wardrobe, occasion, group, account_gender=gender, **kw)


def cats(results):
    return {r["item"]["category"] for r in results}


class CategoryTabTests(unittest.TestCase):

    def test_each_tab_returns_only_its_category(self):
        for group in ir.GROUPS:
            for occasion in ("casual", "college", "party", "wedding", "traditional", "interview", "sports"):
                for r in items(group, occasion):
                    self.assertEqual(present.item_group(r["item"]), group, (group, occasion, r["title"]))

    def test_tops(self):
        self.assertTrue(cats(items("Tops", "college")) <= {"Crop Top", "T-Shirt", "Shirt"})
        self.assertNotIn("Blouse", cats(items("Tops", "college")))

    def test_bottoms_never_blouse_or_dress(self):
        c = cats(items("Bottoms", "casual"))
        self.assertTrue(c and c <= {"Bootcut Jeans", "Trousers", "Skirt", "Shorts", "Track Pants", "Leggings"}, c)

    def test_plain_leggings_are_bottoms_but_salwar_is_ethnic(self):
        self.assertEqual(present.item_group({"category": "Leggings"}), "Bottoms")
        self.assertEqual(present.item_group({"category": "Leggings & Salwars"}), "Ethnic")
        self.assertEqual(present.item_group({"category": "Bootcut Jeans"}), "Bottoms")

    def test_tshirt_pairs_with_leggings_never_with_salwar(self):
        w = make([("T-Shirt", "white"), ("Leggings", "black"), ("Leggings & Salwars", "white")])
        outfits = recommend_outfits(w, "sports", account_gender="Female", limit=20)
        pairs = [{i["category"] for i in o["items"]} for o in outfits]
        self.assertIn({"T-Shirt", "Leggings"}, pairs)
        self.assertFalse(any("Leggings & Salwars" in p for p in pairs))

    def test_dresses(self):
        self.assertTrue(cats(items("Dresses", "party")) <= {"Dress", "Gown"})
        self.assertTrue(items("Dresses", "party"))

    def test_sarees_only_sarees(self):
        self.assertEqual(cats(items("Sarees", "wedding")), {"Saree"})

    def test_ethnic(self):
        c = cats(items("Ethnic", "traditional"))
        self.assertTrue(c)
        self.assertNotIn("Petticoat", c)
        self.assertFalse(c & {"Crop Top", "Bootcut Jeans", "Dress"})

    def test_outerwear(self):
        self.assertTrue(cats(items("Outerwear", "office")) <= {"Jacket", "Coat", "Blazer"})

    def test_shoes_only_footwear(self):
        self.assertTrue(cats(items("Shoes", "party")) <= {"Heels", "Flats", "Boots", "Mojaris (Women)", "Sneakers"})

    def test_accessories_only_accessories(self):
        self.assertTrue(cats(items("Accessories", "casual")) <= {"Handbag", "Watch", "Earrings", "Belt", "Dupatta"}
                        - {"Dupatta"} | {"Handbag", "Watch", "Earrings", "Belt"})

    def test_empty_state_is_honest(self):
        notes = []
        self.assertEqual(items("Sarees", "college", notes=notes), [])
        self.assertTrue(any("No suitable sarees" in n for n in notes), notes)
        notes = []
        self.assertEqual(ir.recommend_items(MEN, "casual", "Sarees", account_gender="Male", notes=notes), [])
        self.assertTrue(notes)


class OccasionTests(unittest.TestCase):

    def test_college_and_party_differ(self):
        self.assertNotEqual([r["title"] for r in items("Tops", "college")],
                            [r["title"] for r in items("Tops", "party")])

    def test_wedding_and_traditional_exclude_casual(self):
        for occasion in ("wedding", "traditional"):
            for group in ir.GROUPS:
                c = cats(items(group, occasion))
                self.assertFalse(c & {"T-Shirt", "Crop Top", "Shorts", "Bootcut Jeans", "Sneakers", "Track Pants"}, (occasion, c))

    def test_interview_is_formal(self):
        all_items = set()
        for group in ir.GROUPS:
            all_items |= cats(items(group, "interview"))
        self.assertFalse(all_items & {"T-Shirt", "Crop Top", "Shorts", "Bootcut Jeans", "Sneakers", "Skirt", "Track Pants", "Mojaris (Women)"}, all_items)
        self.assertIn("Shirt", all_items)

    def test_sports_excludes_formal_and_traditional(self):
        all_items = set()
        for group in ir.GROUPS:
            all_items |= cats(items(group, "sports"))
        self.assertFalse(all_items & {"Saree", "Lehenga", "Blazer", "Heels", "Shirt", "Trousers", "Dress", "Earrings", "Mojaris (Women)"}, all_items)
        self.assertTrue({"T-Shirt", "Sneakers"} <= all_items, all_items)
        self.assertIn("Track Pants", all_items)

    def test_sports_outfits(self):
        outfits = recommend_outfits(WOMEN, "sports", account_gender="Female", limit=40)
        self.assertTrue(outfits)
        for o in outfits:
            self.assertFalse({i["category"] for i in o["items"]} & {"Heels", "Shirt", "Trousers", "Earrings"})


class WeatherColourStyleTests(unittest.TestCase):

    def test_hot_weather_no_coat_or_boots(self):
        c = cats(items("Outerwear", "casual", weather={"is_hot": True})) | cats(items("Shoes", "casual", weather={"is_hot": True}))
        self.assertFalse(c & {"Coat", "Boots"}, c)

    def test_cold_weather_no_shorts(self):
        self.assertNotIn("Shorts", cats(items("Bottoms", "casual", weather={"is_cold": True})))

    def test_colour_filter(self):
        for r in items("Tops", "casual", colour="black"):
            self.assertTrue(any("colour" in w.lower() or "goes well" in w.lower() for w in r["why"]))

    def test_style_filter(self):
        for r in items("Bottoms", "casual", style="Casual"):
            self.assertIn("Casual", r["style_tags"])

    def test_reasons_come_from_scores(self):
        r = items("Tops", "college", weather={"is_hot": True}, colour="white", debug=True)[0]
        self.assertIn("breakdown", r)
        if any(w.startswith("Weather") for w in r["why"]):
            self.assertGreater(r["breakdown"]["weather"], 0.6)

    def test_recent_wear_lowers_rank(self):
        now = datetime(2026, 9, 27)
        base = items("Tops", "casual", now=now)
        top = base[0]["item"]["_id"]
        later = items("Tops", "casual", now=now,
                      wear_history=[{"item_ids": [top], "worn_at": now - timedelta(days=1)}])
        self.assertLess(next(r["score"] for r in later if r["item"]["_id"] == top), base[0]["score"])


class CompatibilityTests(unittest.TestCase):

    def _outfits(self, occasion, wardrobe=WOMEN, gender="Female"):
        return recommend_outfits(wardrobe, occasion, account_gender=gender, limit=60)

    def test_saree_lehenga_never_with_sneakers(self):
        for occasion in ("wedding", "traditional"):
            for o in self._outfits(occasion):
                c = {i["category"] for i in o["items"]}
                if c & {"Saree", "Lehenga"}:
                    self.assertNotIn("Sneakers", c)

    def test_sherwani_never_with_sneakers(self):
        for occasion in ("wedding", "traditional"):
            for o in self._outfits(occasion, MEN, "Male"):
                c = {i["category"] for i in o["items"]}
                if "Sherwani" in c:
                    self.assertNotIn("Sneakers", c)

    def test_no_duplicates_and_valid_shapes(self):
        by_id = {i["_id"]: i for i in WOMEN}
        for occasion in ("casual", "party", "college", "wedding", "interview", "sports"):
            for o in self._outfits(occasion):
                ok, why = present.validate_outfit(o, by_id, "Female", occasion)
                self.assertTrue(ok, (occasion, why))

    def test_full_looks_have_shoes_and_no_fabricated_items(self):
        ids = {i["_id"] for i in WOMEN}
        recs = recommend_outfits(WOMEN, "party", account_gender="Female", limit=40)
        full, _ = rs.finalize(recs, WOMEN, "Female", "party", require_full=True)
        self.assertTrue(full)
        for o in full:
            self.assertIn("footwear", o["roles"].values())
            self.assertTrue({i["_id"] for i in o["items"]} <= ids)

    def test_full_looks_empty_is_honest(self):
        no_shoes = [i for i in WOMEN if present.item_group(i) != "Shoes"]
        recs = recommend_outfits(no_shoes, "party", account_gender="Female", limit=40)
        full, notes = rs.finalize(recs, no_shoes, "Female", "party", require_full=True)
        self.assertEqual(full, [])
        self.assertTrue(any("No complete looks" in n for n in notes))


class OwnershipGenderTests(unittest.TestCase):

    def test_user_a_never_gets_user_b_items(self):
        a = WOMEN
        b = make([("Dress", "red"), ("Heels", "red")], owner="b@x.com", start=100)
        a_ids = {i["_id"] for i in a}
        # The route only ever passes the logged-in user's wardrobe; the
        # validator rejects anything else that slips through.
        for group in ir.GROUPS:
            for r in items(group, "party", wardrobe=a):
                self.assertIn(r["item"]["_id"], a_ids)
        foreign = recommend_outfits(b, "party", account_gender="Female")
        for o in foreign:
            ok, _ = present.validate_outfit(o, {i["_id"]: i for i in a}, "Female", "party")
            self.assertFalse(ok)

    def test_female_never_gets_male_items(self):
        mixed = WOMEN + MEN
        for group in ir.GROUPS:
            c = cats(items(group, "wedding", wardrobe=mixed))
            self.assertFalse(c & {"Sherwani", "Kurta (Men)", "Dhoti Pants", "Mojaris (Men)"}, c)

    def test_male_never_gets_female_items(self):
        mixed = WOMEN + MEN
        for group in ir.GROUPS:
            c = cats(ir.recommend_items(mixed, "wedding", group, account_gender="Male"))
            self.assertFalse(c & {"Saree", "Lehenga", "Blouse", "Dress", "Heels", "Mojaris (Women)", "Kurta (Women)"}, c)


if __name__ == "__main__":
    unittest.main()
