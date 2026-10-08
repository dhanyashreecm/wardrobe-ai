"""
Style & Trends (Outfit Studio) + Outfit Calendar.

Engine tests need no database. API tests run the real Flask routes with
in-memory collections (no network, no real accounts).
"""
import sys
import types
import unittest
from datetime import datetime
from unittest import mock

from bson.objectid import ObjectId

from backend.outfit_presentation import present_item
from backend.style_studio import engine, gaps, recipes, trends

try:
    import flask  # noqa: F401
    import flask_jwt_extended  # noqa: F401
    HAVE_DEPS = True
except ImportError:
    HAVE_DEPS = False


class _Cursor(list):
    def sort(self, key, direction=1):
        return _Cursor(sorted(self, key=lambda d: d.get(key) or datetime.min, reverse=direction == -1))


class _Result:
    def __init__(self, inserted_id=None, deleted_count=0):
        self.inserted_id, self.deleted_count = inserted_id, deleted_count


class Fake:
    """Just enough of a Mongo collection for these modules."""

    def __init__(self, docs=None):
        self.docs = list(docs or [])

    @staticmethod
    def _ok(doc, query):
        for key, want in query.items():
            have = doc.get(key)
            if isinstance(want, dict):
                for op, val in want.items():
                    if op == "$in" and have not in val:
                        return False
                    if op == "$gte" and not (have is not None and have >= val):
                        return False
                    if op == "$lte" and not (have is not None and have <= val):
                        return False
                    if op == "$lt" and not (have is not None and have < val):
                        return False
            elif have != want:
                return False
        return True

    def find(self, query=None, projection=None):
        return _Cursor(dict(d) for d in self.docs if self._ok(d, query or {}))

    def find_one(self, query):
        hits = self.find(query)
        return hits[0] if hits else None

    def insert_one(self, doc):
        doc.setdefault("_id", ObjectId())
        self.docs.append(doc)
        return _Result(inserted_id=doc["_id"])

    def delete_one(self, query):
        for d in self.docs:
            if self._ok(d, query):
                self.docs.remove(d)
                return _Result(deleted_count=1)
        return _Result()

    def delete_many(self, query):
        self.docs = [d for d in self.docs if not self._ok(d, query)]

    def count_documents(self, query):
        return len(self.find(query))


def wardrobe(email, gender, *rows):
    return [{"_id": ObjectId(), "user_email": email, "gender": gender, "category": c, "color": col,
             "image_path": f"https://res.cloudinary.com/demo/{email[0]}{n}.jpg"}
            for n, (c, col) in enumerate(rows)]


ALICE, BOB = "alice@example.com", "bob@example.com"
ALICE_W = wardrobe(ALICE, "female", ("Top", "white"), ("Shirt", "beige"), ("Trousers", "black"),
                   ("Jeans", "blue"), ("Skirt", "grey"), ("Blazer", "black"), ("Dress", "black"),
                   ("Heels", "black"), ("Sneakers", "white"), ("Handbag", "tan"), ("Saree", "emerald"),
                   ("Kurta (Women)", "white"), ("Palazzos", "white"), ("Mojaris (Women)", "gold"),
                   ("Earrings", "gold"), ("Cardigan", "cream"))
BOB_W = wardrobe(BOB, "male", ("Shirt", "white"), ("T-Shirt", "black"), ("Jeans", "blue"),
                 ("Chinos", "beige"), ("Blazer", "navy"), ("Sneakers", "white"), ("Loafers", "brown"),
                 ("Kurta (Men)", "ivory"), ("Pajama", "white"), ("Mojaris (Men)", "gold"), ("Watch", "silver"))
GENDERS = {ALICE: "Female", BOB: "Male"}


def ctx_for(items, gender, **kw):
    return engine.Context("x", [present_item(i) for i in items], gender, **kw)


class TrendCatalogueTests(unittest.TestCase):
    def test_every_trend_has_real_dated_sources_and_no_invented_fields(self):
        data = trends.catalogue()
        for t in data["trends"]:
            self.assertTrue(t["sources"], t["id"])
            for key in t["sources"]:
                src = data["sources"][key]
                self.assertTrue(src["url"].startswith("https://"))
                self.assertTrue(src["name"])
            for banned in ("followers", "likes", "engagement", "influencer"):
                self.assertNotIn(banned, t)

    def test_gender_isolation_of_trends(self):
        female, _ = trends.trends_for("Female")
        male, _ = trends.trends_for("Male")
        f_ids, m_ids = {t["id"] for t in female}, {t["id"] for t in male}
        self.assertIn("pastel-festive", f_ids)
        self.assertNotIn("pastel-festive", m_ids)
        self.assertIn("kurta-nehru-jacket", m_ids)
        self.assertNotIn("kurta-nehru-jacket", f_ids)

    def test_without_live_keys_trends_are_curated_not_live(self):
        with mock.patch.dict("os.environ", {"PINTEREST_ACCESS_TOKEN": "", "SERPAPI_API_KEY": ""}):
            items, status = trends.trends_for("Female")
        self.assertTrue(all(t["freshness"] == "curated" for t in items))
        self.assertFalse(status["instagram"]["configured"])

    def test_live_failure_falls_back_quietly(self):
        from backend.style_studio import live
        live._cache.clear()
        with mock.patch.dict("os.environ", {"PINTEREST_ACCESS_TOKEN": "x"}), \
                mock.patch.object(live, "_get_json", side_effect=OSError("down")):
            items, status = trends.trends_for("Male")
        live._cache.clear()
        self.assertTrue(items)
        self.assertFalse(status["pinterest"]["ok"])


class EngineTests(unittest.TestCase):
    def test_three_named_alternatives_with_real_images_and_reasons(self):
        ctx = ctx_for(ALICE_W, "Female")
        result = engine.create_outfits(ctx, occasion="casual")
        outfits = result["outfits"]
        self.assertEqual(len(outfits), 3)
        names = [o["name"] for o in outfits]
        self.assertEqual(len(set(names)), 3)
        self.assertFalse(any(n.lower().startswith("outfit") for n in names))
        own = {str(i["_id"]) for i in ALICE_W}
        for o in outfits:
            self.assertEqual(o["occasion"], "casual")
            self.assertTrue(o["why"])
            self.assertTrue(o["styling_tip"])
            for p in o["pieces"]:
                self.assertIn(p["_id"], own)
                self.assertTrue(p["image_path"].startswith("https://res.cloudinary.com/"))

    def test_male_account_never_gets_womens_pieces(self):
        mixed = BOB_W + wardrobe(BOB, "female", ("Saree", "red"), ("Dress", "black"))
        ctx = ctx_for(mixed, "Male")
        for occasion in ("casual", "traditional", "party"):
            for o in engine.create_outfits(ctx, occasion=occasion)["outfits"]:
                cats = {p["category"] for p in o["pieces"]}
                self.assertFalse(cats & {"Saree", "Dress"})

    def test_traditional_outfits_never_use_sneakers_or_western_pieces(self):
        ctx = ctx_for(ALICE_W, "Female")
        for occasion in ("traditional", "wedding"):
            for o in engine.create_outfits(ctx, occasion=occasion)["outfits"]:
                cats = {p["category"] for p in o["pieces"]}
                self.assertNotIn("Sneakers", cats)
                self.assertFalse(cats & {"Jeans", "Top", "Shirt", "Skirt"})
                self.assertEqual(o["mode"], "ethnic")

    def test_trend_version_matches_recipe(self):
        ctx = ctx_for(ALICE_W, "Female")
        result = engine.create_outfits(ctx, trend_id="ladylike-suiting")
        self.assertTrue(result["outfits"])
        for o in result["outfits"]:
            self.assertIn("Blazer", {p["category"] for p in o["pieces"]})
            self.assertEqual(o["trends"][0]["id"], "ladylike-suiting")

    def test_recently_worn_outfit_is_not_repeated(self):
        ctx = ctx_for(ALICE_W, "Female")
        first = engine.create_outfits(ctx, occasion="date")["outfits"][0]
        history = [{"item_ids": first["key_item_ids"], "outfit_key": first["id"], "worn_at": datetime.utcnow()}]
        ctx2 = ctx_for(ALICE_W, "Female", wear_history=history)
        again = engine.create_outfits(ctx2, occasion="date")
        self.assertNotIn(first["id"], [o["id"] for o in again["outfits"]])

    def test_trend_status_yes_no_and_inspiration(self):
        ctx = ctx_for(ALICE_W, "Female")
        by_id = {t["id"]: t for t in ctx.trends}
        self.assertEqual(engine.trend_status(ctx, by_id["ladylike-suiting"])["status"], "yes")
        self.assertEqual(engine.trend_status(ctx, by_id["folk-tales"])["status"], "partly")
        self.assertIn("boots", " ".join(engine.trend_status(ctx, by_id["folk-tales"])["missing"]))
        self.assertEqual(engine.trend_status(ctx, by_id["indo-western-fusion"])["status"], "inspiration")

    def test_shopping_gap_uses_virtual_items_only_and_counts_unlocks(self):
        ctx = ctx_for(BOB_W, "Male")
        before = len(ctx.items)
        result = gaps.analyse(ctx)
        self.assertEqual(len(ctx.items), before)                 # nothing added to the wardrobe
        if not result["no_purchase_needed"]:
            top = result["top"]
            self.assertGreaterEqual(top["unlocks_total"], 1)
            self.assertTrue(top["shop"]["links"])
            self.assertFalse(any(str(p["_id"]).startswith("virtual:") for p in top["works_with"]))

    def test_no_purchase_needed_when_nothing_unlocks(self):
        ctx = ctx_for(ALICE_W, "Female")
        with mock.patch.object(gaps, "STAPLES", {"female": []}), \
                mock.patch.object(recipes, "missing_slots", return_value=[]):
            result = gaps.analyse(ctx)
        self.assertTrue(result["no_purchase_needed"])
        self.assertIn("No purchase needed", result["message"])


@unittest.skipUnless(HAVE_DEPS, "Flask not installed here")
class StyleApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for name, attrs in {"backend.clothing_similarity": {"find_similar": lambda *a, **k: []},
                            "backend.indofashion_similarity": {"find_similar_indofashion": lambda *a, **k: []},
                            "backend.indofashion_classifier": {"predict_category": lambda p: {}}}.items():
            if name not in sys.modules:
                module = types.ModuleType(name)
                for k, v in attrs.items():
                    setattr(module, k, v)
                sys.modules[name] = module
        from backend import app as app_module, style_routes
        from backend.style_studio import calendar, saved
        from backend import outfit_feedback
        cls.app, cls.routes, cls.calendar, cls.saved, cls.fb = app_module.app, style_routes, calendar, saved, outfit_feedback
        cls.client = app_module.app.test_client()

    def setUp(self):
        self.wardrobe = Fake(ALICE_W + BOB_W)
        self.wear = Fake()
        self.saved_docs = Fake()
        by_user = lambda email: [dict(d) for d in self.wardrobe.docs if d["user_email"] == email]  # noqa: E731
        self.patches = [
            mock.patch.object(self.routes, "get_user_wardrobe", side_effect=by_user),
            mock.patch.object(self.routes, "get_user_gender", side_effect=lambda e: GENDERS.get(e)),
            mock.patch.object(self.fb, "wardrobe_collection", self.wardrobe),
            mock.patch.object(self.fb, "wear_log_collection", self.wear),
            mock.patch.object(self.fb, "feedback_collection", Fake()),
            mock.patch.object(self.calendar, "wear_log_collection", self.wear),
            mock.patch.object(self.saved, "saved_collection", self.saved_docs),
            mock.patch.object(self.saved, "wardrobe_collection", self.wardrobe),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def h(self, email):
        from flask_jwt_extended import create_access_token
        with self.app.app_context():
            return {"Authorization": f"Bearer {create_access_token(identity=email)}"}

    def test_every_route_requires_login(self):
        for method, path in [("get", "/api/style/overview"), ("post", "/api/style/outfits"),
                             ("get", "/api/style/ideas"), ("get", "/api/style/shopping"),
                             ("get", "/api/style/saved"), ("post", "/api/style/saved"),
                             ("get", "/api/calendar"), ("post", "/api/calendar"),
                             ("get", "/api/wardrobe/last-worn")]:
            self.assertEqual(getattr(self.client, method)(path).status_code, 401, path)

    def test_overview_is_gendered_and_inspiration_never_touches_wardrobe(self):
        before = len(self.wardrobe.docs)
        women = self.client.get("/api/style/overview", headers=self.h(ALICE)).get_json()
        men = self.client.get("/api/style/overview", headers=self.h(BOB)).get_json()
        self.assertEqual(women["gender"], "female")
        self.assertEqual(men["gender"], "male")
        self.assertNotIn("dark-romance", [t["id"] for t in men["trends"]])
        self.assertEqual(len(self.wardrobe.docs), before)

    def test_outfits_use_only_the_callers_wardrobe(self):
        body = self.client.post("/api/style/outfits", json={"occasion": "casual"}, headers=self.h(BOB)).get_json()
        bob_ids = {str(i["_id"]) for i in BOB_W}
        self.assertEqual(len(body["outfits"]), 3)
        for o in body["outfits"]:
            self.assertTrue(set(o["item_ids"]) <= bob_ids)

    def test_saved_outfits_are_private_and_ignore_foreign_items(self):
        alice_ids = [str(ALICE_W[0]["_id"]), str(ALICE_W[2]["_id"])]
        bob_item = str(BOB_W[0]["_id"])
        res = self.client.post("/api/style/saved", json={"name": "City Rose", "item_ids": alice_ids + [bob_item],
                                                         "occasion": "Casual"}, headers=self.h(ALICE))
        self.assertEqual(res.status_code, 201)
        doc = self.saved_docs.docs[0]
        self.assertEqual(doc["item_ids"], alice_ids)                 # Bob's piece dropped
        self.assertTrue(all(u.startswith("https://res.cloudinary.com/") for u in doc["image_urls"]))
        self.assertEqual(self.client.get("/api/style/saved", headers=self.h(BOB)).get_json()["saved"], [])
        saved_id = res.get_json()["id"]
        self.assertEqual(self.client.delete(f"/api/style/saved/{saved_id}", headers=self.h(BOB)).status_code, 404)
        self.assertEqual(self.client.delete(f"/api/style/saved/{saved_id}", headers=self.h(ALICE)).status_code, 200)
        bad = self.client.post("/api/style/saved", json={"item_ids": [bob_item]}, headers=self.h(ALICE))
        self.assertEqual(bad.status_code, 400)

    def test_calendar_log_backdate_future_repeat_and_last_worn(self):
        ids = [str(ALICE_W[1]["_id"]), str(ALICE_W[2]["_id"])]
        today = self.calendar.local_today()
        ok = self.client.post("/api/calendar", json={"item_ids": ids}, headers=self.h(ALICE))
        self.assertEqual(ok.status_code, 201)
        self.assertEqual(ok.get_json()["date"], today.isoformat())
        again = self.client.post("/api/calendar", json={"item_ids": ids, "date": today.isoformat()}, headers=self.h(ALICE))
        self.assertIn("already", again.get_json()["warning"])
        future = self.client.post("/api/calendar", json={"item_ids": ids, "date": "2999-01-01"}, headers=self.h(ALICE))
        self.assertEqual(future.status_code, 400)
        foreign = self.client.post("/api/calendar", json={"item_ids": [str(BOB_W[0]["_id"])]}, headers=self.h(ALICE))
        self.assertEqual(foreign.status_code, 400)
        month = self.client.get(f"/api/calendar?month={today:%Y-%m}", headers=self.h(ALICE)).get_json()
        self.assertEqual(len(month["entries"]), 2)
        self.assertEqual(self.client.get(f"/api/calendar?month={today:%Y-%m}", headers=self.h(BOB)).get_json()["entries"], [])
        worn = self.client.get("/api/wardrobe/last-worn", headers=self.h(ALICE)).get_json()["last_worn"]
        self.assertEqual(worn[ids[0]]["days_ago"], 0)
        entry_id = month["entries"][0]["id"]
        self.assertEqual(self.client.delete(f"/api/calendar/{entry_id}", headers=self.h(BOB)).status_code, 404)
        self.assertEqual(self.client.delete(f"/api/calendar/{entry_id}", headers=self.h(ALICE)).status_code, 200)

    def test_style_pages_never_touch_the_try_on_counter(self):
        from backend import tryon_usage
        with mock.patch.object(tryon_usage, "reserve") as reserve, mock.patch.object(tryon_usage, "settle") as settle:
            for path in ("/api/style/overview", "/api/style/ideas", "/api/style/shopping"):
                self.client.get(path, headers=self.h(ALICE))
            self.client.post("/api/style/outfits", json={"occasion": "party"}, headers=self.h(ALICE))
        reserve.assert_not_called()
        settle.assert_not_called()


if __name__ == "__main__":
    unittest.main()
