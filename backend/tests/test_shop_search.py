"""
"Shop this look" + wishlist tests. No network, no Atlas, no TensorFlow:
SerpApi calls are mocked, MongoDB is an in-memory stand-in.

    python -m unittest backend.tests.test_shop_search -v
"""
import io
import json
import unittest
from unittest import mock

try:
    import flask  # noqa: F401
    import flask_jwt_extended  # noqa: F401
    from bson import ObjectId
    from PIL import Image
    HAVE_DEPS = True
except ImportError:
    HAVE_DEPS = False


def jpeg_bytes(size=(64, 64), colour=(220, 120, 160)):
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, "JPEG")
    return out.getvalue()


ANALYSIS = {"category": "kurta", "colour": "pink", "pattern": "embroidered",
            "neckline": "mandarin collar", "audience": "women"}


def product(title, url, position=0, price=None, exact=False, image="https://img.example/x.jpg"):
    return {"title": title, "url": url, "source": "", "image": image, "price": price,
            "price_text": None if price is None else f"₹{price:,.0f}", "currency": "INR",
            "in_stock": None, "exact_evidence": exact, "position": position,
            "provider": "google_lens"}


# ------------------------------------------------------------------
# ATTRIBUTES / QUERY
# ------------------------------------------------------------------

class AttributeTests(unittest.TestCase):

    def test_reads_details_from_shop_titles(self):
        from backend.shopping.attributes import extract_from_text
        found = extract_from_text("Libas Women Pink Embroidered Straight Kurta with Mandarin Collar & 3/4 Sleeves")
        self.assertEqual(found["category"], "kurta")
        self.assertEqual(found["colours"], ["pink"])
        self.assertEqual(found["pattern"], ["embroidered"])
        self.assertEqual(found["neckline"], ["mandarin collar"])
        self.assertEqual(found["sleeve"], ["3/4 sleeves"])

    def test_specific_garment_words_win(self):
        from backend.shopping.attributes import extract_from_text
        self.assertEqual(extract_from_text("Rust Printed T-shirt")["category"], "t-shirt")
        self.assertEqual(extract_from_text("Sky Blue Nehru Jacket")["category"], "nehru jacket")
        self.assertEqual(extract_from_text("Kurta with Trousers & Dupatta")["category"], "kurta set")
        # No false hits inside other words.
        self.assertEqual(extract_from_text("steel cabinet")["fabric"], [])

    def test_consensus_needs_several_titles(self):
        from backend.shopping.attributes import consensus_from_titles
        agreed = consensus_from_titles([
            "Pink Embroidered Kurta Mandarin Collar", "Pink chikankari kurta 3/4 sleeve",
            "Women Pink Straight Kurta Mandarin Collar", "Blue sleeveless dress"])
        self.assertEqual(agreed["neckline"][0][0], "mandarin collar")
        self.assertEqual(agreed["pattern"][0][0], "embroidered")   # chikankari counts
        self.assertNotIn("sleeve", agreed)                         # only one title each

    def test_query_and_user_keywords(self):
        from backend.shopping.analysis import build_query, refine_with_titles
        self.assertEqual(build_query(ANALYSIS), "pink embroidered kurta women")
        self.assertEqual(build_query(dict(ANALYSIS, keywords="yellow anarkali")), "yellow anarkali")
        refined = refine_with_titles({"category": "kurta", "colour": "pink", "sources": {}},
                                     ["Pink A-Line Kurta", "pink a-line kurta cotton", "Kurta A-line"])
        self.assertEqual(refined["silhouette"], "a-line")
        self.assertEqual(refined["sources"]["silhouette"], "matched products")

    def test_photo_analysis_uses_existing_models(self):
        import sys
        from backend.shopping.analysis import analyse_photo
        classifier = mock.MagicMock()
        classifier.is_available.return_value = True
        classifier.predict.return_value = {"category": "Kurta (Women)", "confidence": 0.88}
        colours = mock.MagicMock()
        colours.detect_colors.return_value = {"primary": "pink", "secondary": ["gold"],
                                              "is_patterned": True, "confidence": "high"}
        with mock.patch.dict(sys.modules, {"backend.garment_classifier": classifier,
                                           "backend.color_detection": colours}):
            import backend
            with mock.patch.object(backend, "garment_classifier", classifier, create=True):
                out = analyse_photo("photo.jpg", "Female")
        self.assertEqual((out["category"], out["audience"], out["colour"]), ("kurta", "women", "pink"))
        self.assertEqual(out["secondary_colours"], ["gold"])
        self.assertFalse(out["uncertain"])

        classifier.predict.return_value = {"category": "Shirt", "confidence": 0.3}
        with mock.patch.dict(sys.modules, {"backend.garment_classifier": classifier,
                                           "backend.color_detection": colours}):
            import backend
            with mock.patch.object(backend, "garment_classifier", classifier, create=True):
                out = analyse_photo("photo.jpg", "Male")
        self.assertTrue(out["uncertain"])           # low confidence -> ask the user
        self.assertEqual(out["audience"], "men")    # from the account when the type doesn't say

    def test_client_analysis_is_sanitised(self):
        from backend.shopping.analysis import clean_client_analysis
        clean = clean_client_analysis({"category": "x" * 500, "colour": 5, "evil": "$where",
                                       "secondary_colours": ["red", {"a": 1}]})
        self.assertEqual(len(clean["category"]), 60)
        self.assertEqual(clean["colour"], "")
        self.assertNotIn("evil", clean)
        self.assertEqual(clean["secondary_colours"], ["red"])
        self.assertEqual(clean_client_analysis("nonsense")["category"], "")


# ------------------------------------------------------------------
# RANKING / LABELS
# ------------------------------------------------------------------

class RankingTests(unittest.TestCase):

    def rank(self, visual, exact=()):
        from backend.shopping.ranking import rank
        return rank(list(visual), list(exact), ANALYSIS)

    def test_exact_label_needs_exact_evidence(self):
        same = "Women Pink Embroidered Kurta Mandarin Collar"
        out = self.rank(
            [product(same, "https://www.myntra.com/kurtas/libas/1", 0, 1299)],
            [product(same, "https://www.ajio.com/p/2", 0, 1499, exact=True)])
        labels = {p["platform"]: p["match"] for p in out}
        self.assertEqual(labels, {"AJIO": "exact", "Myntra": "very_similar"})
        self.assertEqual(out[0]["platform"], "AJIO")
        for p in out:
            self.assertNotIn("similarity", p)   # no invented percentages

    def test_labels_follow_the_evidence(self):
        out = {p["title"]: p["match"] for p in self.rank([
            product("Pink Embroidered Kurta", "https://www.myntra.com/a", 1, 999),
            product("Pink Printed Kurta", "https://www.myntra.com/b", 2, 999),
            product("Blue Embroidered Kurta", "https://www.myntra.com/c", 3, 999),
            product("Women Ethnic Wear", "https://www.myntra.com/d", 4, 999),
        ])}
        self.assertEqual(out["Pink Embroidered Kurta"], "very_similar")
        self.assertEqual(out["Pink Printed Kurta"], "similar_style")      # detail differs
        self.assertEqual(out["Blue Embroidered Kurta"], "same_category")  # colour differs
        self.assertEqual(out["Women Ethnic Wear"], "similar_style")       # nothing contradicts

    def test_different_garment_dropped_unless_exact(self):
        out = self.rank([product("Pink Embroidered Saree", "https://www.myntra.com/s", 0, 2000)])
        self.assertEqual(out, [])
        out = self.rank([], [product("Pink Embroidered Saree", "https://www.ajio.com/s", 0, 2000, exact=True)])
        self.assertEqual(out[0]["match"], "exact")

    def test_only_safe_shop_links_survive(self):
        out = self.rank([
            product("Pink Kurta", "https://in.pinterest.com/pin/1", 0),
            product("Pink Kurta", "https://www.instagram.com/p/1", 1, 999),
            product("Pink Kurta blog", "https://someblog.example/post", 2),
            product("Pink Kurta", "javascript:alert(1)", 3, 999),
            product("Pink Kurta boutique", "https://boutique.example/kurta", 4, 1500),
            product("Pink Kurta", "https://www.flipkart.com/k", 5, image="javascript:x"),
        ])
        self.assertEqual([p["url"] for p in out],
                         ["https://boutique.example/kurta", "https://www.flipkart.com/k"])
        self.assertEqual(out[1]["image"], "")

    def test_duplicates_removed(self):
        out = self.rank([
            product("Pink Kurta", "https://www.myntra.com/k?utm_source=google", 0, 999),
            product("Pink Kurta", "https://myntra.com/k/", 1, 999),
            product("PINK  kurta", "https://www.myntra.com/other-url", 2, 999),
        ])
        self.assertEqual(len(out), 1)

    def test_wardrobe_levels(self):
        from backend.shopping.ranking import wardrobe_match_level, wardrobe_summary
        self.assertEqual(wardrobe_match_level(0.93), "very_close")
        self.assertEqual(wardrobe_match_level(0.75), "similar")
        self.assertEqual(wardrobe_match_level(0.5), "loose")
        self.assertEqual(wardrobe_summary([]), "none")
        self.assertEqual(wardrobe_summary([{"similarity": 0.6}]), "none")
        self.assertEqual(wardrobe_summary([{"similarity": 0.6}, {"similarity": 0.9}]), "very_close")


# ------------------------------------------------------------------
# SERPAPI CLIENT
# ------------------------------------------------------------------

@unittest.skipUnless(HAVE_DEPS, "Pillow not installed")
class LensClientTests(unittest.TestCase):

    def test_price_shapes(self):
        from backend.shopping.lens import normalise
        a = normalise({"title": "t", "link": "https://x.in", "price": {
            "value": "₹1,299*", "extracted_value": 1299, "currency": "₹"}, "in_stock": True}, False, 0)
        self.assertEqual((a["price"], a["price_text"], a["currency"], a["in_stock"]),
                         (1299.0, "₹1,299", "INR", True))
        b = normalise({"title": "t", "link": "https://x.in", "price": "₹899",
                       "extracted_price": 899, "out_of_stock": True}, True, 0)
        self.assertEqual((b["price"], b["currency"], b["in_stock"], b["exact_evidence"]),
                         (899.0, "INR", False, True))
        c = normalise({"title": "t", "link": "https://x.in"}, False, 0)
        self.assertIsNone(c["price"])

    def test_big_photo_shrunk_under_limit(self):
        import os
        from backend.shopping.lens import MAX_UPLOAD_BYTES, prepare_image
        noisy = Image.frombytes("RGB", (3000, 3000), os.urandom(3000 * 3000 * 3))
        out = io.BytesIO()
        noisy.save(out, "PNG")
        self.assertLessEqual(len(prepare_image(out.getvalue())), MAX_UPLOAD_BYTES)

    def test_errors_never_contain_the_key(self):
        from backend import config
        from backend.shopping import lens

        class Response:
            def __init__(self, body):
                self.body = json.dumps(body).encode()

            def read(self):
                return self.body

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        requests = []

        def fake_urlopen(request, timeout=None):
            requests.append(request)
            if request.full_url.startswith(lens.UPLOAD_URL):
                return Response({"image_id": "img123"})
            return Response({"error": "Your account has run out of searches. key=SECRET-KEY-123"})

        with mock.patch.object(config, "SERPAPI_API_KEY", "SECRET-KEY-123"), \
             mock.patch("urllib.request.urlopen", fake_urlopen):
            with self.assertRaises(lens.LensError) as caught:
                lens.search(jpeg_bytes(), None, include_exact=False)
        self.assertEqual(caught.exception.kind, "quota")
        self.assertNotIn("SECRET-KEY-123", caught.exception.message)
        search_url = requests[-1].full_url
        self.assertIn("engine=google_lens", search_url)
        self.assertIn("image_id=img123", search_url)
        self.assertIn("country=in", search_url)


# ------------------------------------------------------------------
# SERVICE (fallback cases + cache)
# ------------------------------------------------------------------

@unittest.skipUnless(HAVE_DEPS, "Pillow not installed")
class ServiceTests(unittest.TestCase):

    def setUp(self):
        from backend import config
        from backend.shopping import service
        self.service = service
        service.clear_cache()
        self.addCleanup(service.clear_cache)
        for p in (mock.patch.object(config, "SHOP_CACHE_HOURS", 12.0),
                  mock.patch.object(config, "SHOP_LENS_EXACT_MATCHES", True)):
            p.start()
            self.addCleanup(p.stop)

    def configured(self, value=True):
        from backend import config
        return mock.patch.object(config, "SERPAPI_API_KEY", "k" if value else "")

    def test_not_configured_gives_links_not_products(self):
        with self.configured(False):
            out = self.service.search(jpeg_bytes(), dict(ANALYSIS))
        self.assertEqual(out["status"], "links_only")
        self.assertEqual(out["products"], [])
        platforms = [link["platform"] for link in out["links"]]
        for shop in ("Myntra", "AJIO", "Nykaa Fashion", "Amazon", "Flipkart"):
            self.assertIn(shop, platforms)
        self.assertTrue(all(link["url"].startswith("https://") for link in out["links"]))
        self.assertIn("pink+embroidered+kurta+women", out["links"][1]["url"])

    def test_provider_down_still_gives_links(self):
        from backend.shopping import lens
        with self.configured(), mock.patch.object(
                lens, "search", side_effect=lens.LensError("quota", "Used up.")):
            out = self.service.search(jpeg_bytes(), dict(ANALYSIS))
        self.assertEqual(out["status"], "provider_error")
        self.assertEqual(out["products"], [])
        self.assertTrue(out["links"])

    def test_no_results_case(self):
        from backend.shopping import lens
        with self.configured(), mock.patch.object(lens, "search", return_value={"visual": [], "exact": []}):
            out = self.service.search(jpeg_bytes(), dict(ANALYSIS))
        self.assertEqual(out["status"], "no_results")
        self.assertTrue(out["links"])

    def test_results_cached_failures_not(self):
        from backend.shopping import lens
        photo = jpeg_bytes()
        found = {"visual": [product("Pink Embroidered Kurta", "https://www.myntra.com/a", 0, 999)],
                 "exact": []}
        with self.configured(), mock.patch.object(
                lens, "search", side_effect=lens.LensError("unavailable", "down")) as call:
            self.service.search(photo, dict(ANALYSIS))
            self.service.search(photo, dict(ANALYSIS))
        self.assertEqual(call.call_count, 2)
        with self.configured(), mock.patch.object(lens, "search", return_value=found) as call:
            first = self.service.search(photo, dict(ANALYSIS))
            second = self.service.search(photo, dict(ANALYSIS))
            self.service.search(photo, dict(ANALYSIS, keywords="pink kurta mirror work"))
        self.assertEqual(call.call_count, 2)       # new keywords = new search
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(first["status"], "similar_only")
        self.assertEqual(second["products"][0]["match"], "very_similar")


# ------------------------------------------------------------------
# ROUTES + WISHLIST PRIVACY
# ------------------------------------------------------------------

class FakeWishlist:
    def __init__(self):
        self.docs = []

    @staticmethod
    def _match(doc, flt):
        return all(doc.get(k) == v for k, v in flt.items())

    def find(self, flt):
        return [dict(d) for d in self.docs if self._match(d, flt)]

    def find_one(self, flt):
        found = self.find(flt)
        return found[0] if found else None

    def count_documents(self, flt):
        return len(self.find(flt))

    def insert_one(self, doc):
        doc = dict(doc, _id=ObjectId())
        self.docs.append(doc)
        return mock.Mock(inserted_id=doc["_id"])

    def delete_one(self, flt):
        for d in self.docs:
            if self._match(d, flt):
                self.docs.remove(d)
                return mock.Mock(deleted_count=1)
        return mock.Mock(deleted_count=0)

    def delete_many(self, flt):
        self.docs = [d for d in self.docs if not self._match(d, flt)]


@unittest.skipUnless(HAVE_DEPS, "flask not installed")
class RouteTests(unittest.TestCase):

    def setUp(self):
        from flask import Flask
        from flask_jwt_extended import JWTManager, create_access_token
        from backend import config, shopping_routes, wishlist
        from backend.shopping import service

        self.store = FakeWishlist()
        for p in (mock.patch.object(wishlist, "wishlist_collection", self.store),
                  mock.patch.object(config, "SERPAPI_API_KEY", "")):
            p.start()
            self.addCleanup(p.stop)
        service.clear_cache()
        shopping_routes.reset_limits()

        app = Flask(__name__)
        app.config["JWT_SECRET_KEY"] = "test-secret-" + "x" * 40
        JWTManager(app)
        app.register_blueprint(shopping_routes.shopping_blueprint)
        self.client = app.test_client()
        with app.app_context():
            self.alice = {"Authorization": "Bearer " + create_access_token(identity="alice@gmail.com")}
            self.bob = {"Authorization": "Bearer " + create_access_token(identity="Bob@Gmail.com")}

    def search(self, headers, image=None, analysis=None):
        data = {"analysis": json.dumps(analysis or ANALYSIS)}
        if image is not None:
            data["image"] = (io.BytesIO(image), "photo.jpg")
        return self.client.post("/api/shop/search", data=data, headers=headers,
                                content_type="multipart/form-data")

    def test_login_required(self):
        self.assertEqual(self.client.get("/api/wishlist").status_code, 401)
        self.assertEqual(self.client.post("/api/shop/search").status_code, 401)

    def test_search_without_api_key_returns_links(self):
        r = self.search(self.alice, jpeg_bytes())
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["status"], "links_only")
        self.assertEqual(body["products"], [])
        self.assertNotIn("api_key", r.get_data(as_text=True))

    def test_bad_inputs(self):
        self.assertEqual(self.search(self.alice).status_code, 400)
        self.assertEqual(self.search(self.alice, b"not an image").status_code, 400)
        r = self.client.post("/api/shop/search", headers=self.alice, content_type="multipart/form-data",
                             data={"image": (io.BytesIO(jpeg_bytes()), "p.jpg"), "analysis": "{broken"})
        self.assertEqual(r.status_code, 200)

    def test_search_rate_limit(self):
        from backend import shopping_routes
        with mock.patch.object(shopping_routes, "SEARCHES_PER_HOUR", 2):
            codes = [self.search(self.alice, jpeg_bytes()).status_code for _ in range(3)]
        self.assertEqual(codes, [200, 200, 429])

    def test_wishlist_is_private(self):
        item = {"title": "Pink Kurta", "url": "https://www.myntra.com/k/1", "price": 999,
                "image": "https://img.example/k.jpg"}
        r = self.client.post("/api/wishlist", json=item, headers=self.alice)
        self.assertEqual(r.status_code, 200)
        item_id = r.get_json()["item"]["id"]
        self.assertEqual(r.get_json()["item"]["platform"], "Myntra")

        # Saving twice doesn't duplicate.
        self.client.post("/api/wishlist", json=item, headers=self.alice)
        self.assertEqual(len(self.client.get("/api/wishlist", headers=self.alice).get_json()["items"]), 1)

        # Bob sees nothing of Alice's and cannot delete it.
        self.assertEqual(self.client.get("/api/wishlist", headers=self.bob).get_json()["items"], [])
        self.assertEqual(self.client.delete(f"/api/wishlist/{item_id}", headers=self.bob).status_code, 404)
        self.assertEqual(len(self.store.docs), 1)

        self.assertEqual(self.client.delete(f"/api/wishlist/{item_id}", headers=self.alice).status_code, 200)
        self.assertEqual(self.store.docs, [])
        self.assertEqual(self.client.delete("/api/wishlist/not-an-id", headers=self.alice).status_code, 404)

    def test_wishlist_rejects_unsafe_links(self):
        for bad in ({"title": "x", "url": "javascript:alert(1)"}, {"title": "", "url": "https://a.in"}, "junk"):
            r = self.client.post("/api/wishlist", json=bad, headers=self.alice)
            self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/wishlist", headers=self.alice,
                             json={"title": "ok", "url": "https://a.in/p", "image": "javascript:x"})
        self.assertEqual(r.get_json()["item"]["image"], "")


if __name__ == "__main__":
    unittest.main()
