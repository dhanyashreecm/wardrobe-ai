"""
Upload endpoint tests (POST /api/wardrobe/add) through the REAL Flask
route. The database insert, Cloudinary upload and heavy AI models are
replaced with stand-ins, so these tests never touch your real wardrobe,
Atlas or Cloudinary.

Needs the project's environment (Flask etc.), so run on the Mac:
    source ai_env/bin/activate
    python -m unittest backend.tests.test_upload_api -v
Skipped automatically where Flask/pymongo aren't installed.
"""
import io
import sys
import tempfile
import types
import unittest
from datetime import timedelta
from unittest import mock


def _png_bytes():
    from PIL import Image
    from PIL import ImageDraw
    buf = io.BytesIO()
    img = Image.new("RGB", (300, 400), (225, 220, 210))      # floor/wall
    ImageDraw.Draw(img).rectangle((90, 90, 210, 320), fill=(20, 20, 20))  # garment
    img.save(buf, format="PNG")
    return buf.getvalue()


def _stub(name, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module


try:
    import flask  # noqa: F401
    import pymongo  # noqa: F401
    import flask_jwt_extended  # noqa: F401
    HAVE_DEPS = True
except ImportError:
    HAVE_DEPS = False


@unittest.skipUnless(HAVE_DEPS, "Flask/pymongo not installed here - run on the Mac with ai_env")
class UploadApiTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Keep TensorFlow models from loading: they are not what's tested.
        _stub("backend.clothing_similarity", find_similar=lambda *a, **k: [])
        _stub("backend.indofashion_similarity", find_similar_indofashion=lambda *a, **k: [])
        _stub("backend.indofashion_classifier",
              predict_category=lambda path: {"category": "blouse", "confidence": 0.3})
        from backend import app as app_module
        cls.m = app_module
        cls.client = app_module.app.test_client()
        cls.tmp = tempfile.mkdtemp()

    def setUp(self):
        m = self.m
        self.patches = [
            mock.patch.object(m, "get_user_folder", return_value=("u_folder", self.tmp)),
            mock.patch.object(m, "get_user_gender", return_value="Female"),
            mock.patch.object(m, "add_item", return_value="item123"),
            mock.patch.object(m.config, "storage_backend", return_value="cloudinary"),
            mock.patch.object(m.storage, "upload_local_file",
                              return_value="https://res.cloudinary.com/demo/image/upload/x.jpg"),
            mock.patch.object(m, "detect_colors", return_value={"primary": "black", "secondary": []}),
            mock.patch.object(m, "detect_colors_from_pixels", return_value={"primary": "black", "secondary": []}),
            mock.patch.object(m.garment_classifier, "is_available", return_value=False),
        ]
        self.mocks = [p.start() for p in self.patches]
        self.add_item = self.mocks[2]
        self.cloud = self.mocks[4]
        self.detect = self.mocks[5]
        self.detect_px = self.mocks[6]

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def _token(self, email="owner@x.com", expires=None):
        from flask_jwt_extended import create_access_token
        with self.m.app.app_context():
            return create_access_token(identity=email, expires_delta=expires)

    def _post(self, data=None, token=True, image=None, filename="shirt.png", email="owner@x.com"):
        form = {"category": "Shirt", "category_explicit": "true", "color": "white"}
        form.update(data or {})
        if image is not False:
            form["image"] = (io.BytesIO(_png_bytes() if image is None else image), filename)
        headers = {"Authorization": f"Bearer {self._token(email)}"} if token else {}
        return self.client.post("/api/wardrobe/add", data=form, headers=headers,
                                content_type="multipart/form-data")

    def test_valid_upload_saves_item_with_cloud_url(self):
        res = self._post()
        self.assertEqual(res.status_code, 200, res.get_json())
        body = res.get_json()
        self.assertTrue(body["success"])
        self.assertTrue(body["image"].startswith("https://"))
        self.assertEqual(body["category"], "Shirt")
        self.add_item.assert_called_once()
        args = self.add_item.call_args[0]
        self.assertEqual(args[0], "owner@x.com")          # owner from the JWT
        self.assertEqual(args[3], body["image"])          # the cloud URL is stored

    def test_owner_comes_from_token_not_form(self):
        res = self._post(data={"user_email": "attacker@x.com"}, email="real@x.com")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.add_item.call_args[0][0], "real@x.com")

    def test_unauthenticated_upload_rejected_with_message(self):
        res = self._post(token=False)
        self.assertEqual(res.status_code, 401)
        self.assertIn("message", res.get_json())
        self.add_item.assert_not_called()

    def test_expired_session_has_clear_message(self):
        token = self._token(expires=timedelta(seconds=-10))
        res = self.client.post("/api/wardrobe/add", data={}, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.get_json()["code"], "token_expired")

    def test_tokens_last_longer_than_15_minutes(self):
        self.assertGreaterEqual(self.m.app.config["JWT_ACCESS_TOKEN_EXPIRES"], timedelta(days=1))

    def test_invalid_image_rejected_before_storage(self):
        res = self._post(image=b"this is not an image", filename="notes.txt")
        self.assertEqual(res.status_code, 400)
        self.assertIn("image", res.get_json()["message"].lower())
        self.cloud.assert_not_called()
        self.add_item.assert_not_called()

    def test_missing_image(self):
        res = self._post(image=False)
        self.assertEqual(res.status_code, 400)
        self.assertIn("message", res.get_json())

    def test_non_latin_filename_still_uploads(self):
        res = self._post(filename="写真.png")
        self.assertEqual(res.status_code, 200, res.get_json())

    def test_cloud_failure_is_reported_and_nothing_saved(self):
        self.cloud.side_effect = self.m.storage.StorageError("network down")
        res = self._post()
        self.assertEqual(res.status_code, 502)
        self.assertIn("could not be stored", res.get_json()["message"])
        self.add_item.assert_not_called()

    def test_colour_failure_uses_message_key(self):
        self.detect.return_value = {}
        self.detect_px.return_value = {}
        res = self._post(data={"color": ""})
        self.assertEqual(res.status_code, 400)
        self.assertIn("colour", res.get_json()["message"].lower())
        self.cloud.assert_not_called()

    def test_unrecognised_auto_category_asks_user_and_stores_nothing(self):
        res = self._post(data={"category": "", "category_explicit": "false"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("choose its category", res.get_json()["message"])
        self.cloud.assert_not_called()
        self.add_item.assert_not_called()

    def test_unexpected_crash_returns_json_message(self):
        self.add_item.side_effect = RuntimeError("db down")
        res = self._post()
        self.assertEqual(res.status_code, 500)
        self.assertIn("Upload failed", res.get_json()["message"])

    def test_background_removed_before_storage_and_original_kept(self):
        res = self._post()
        body = res.get_json()
        self.assertEqual(res.status_code, 200, body)
        self.assertTrue(body["background_removed"])
        uploaded = [c.args[0] for c in self.cloud.call_args_list]
        kinds = [c.kwargs.get("kind") for c in self.cloud.call_args_list]
        self.assertTrue(uploaded[0].endswith("_clean.jpg"))       # processed = primary image
        self.assertIn("originals", kinds)                          # original retained
        attributes = self.add_item.call_args[0][7]
        self.assertTrue(attributes["image_processing"]["background_removed"])
        # colour read from the garment's own pixels, not the photo
        self.detect_px.assert_called_once()
        self.detect.assert_not_called()

    def test_tiny_image_rejected_with_message(self):
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (40, 40), "red").save(buf, format="PNG")
        res = self._post(image=buf.getvalue())
        self.assertEqual(res.status_code, 400)
        self.assertIn("too small", res.get_json()["message"])
        self.add_item.assert_not_called()

    def test_male_account_cannot_save_a_saree(self):
        with mock.patch.object(self.m, "get_user_gender", return_value="Male"):
            res = self._post(data={"category": "Saree"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("men's", res.get_json()["message"])
        self.add_item.assert_not_called()
        self.cloud.assert_not_called()

    def test_female_account_cannot_save_a_sherwani(self):
        res = self._post(data={"category": "Sherwani"})
        self.assertEqual(res.status_code, 400)
        self.add_item.assert_not_called()

    def test_item_saved_with_account_gender_and_canonical_name(self):
        res = self._post(data={"category": "Denims"})
        self.assertEqual(res.status_code, 200, res.get_json())
        self.assertEqual(self.add_item.call_args[0][1], "Jeans")
        self.assertEqual(self.add_item.call_args.kwargs.get("gender"), "female")

    def test_account_without_gender_is_asked_to_set_it(self):
        with mock.patch.object(self.m, "get_user_gender", return_value=None):
            res = self._post()
        self.assertEqual(res.status_code, 409)

    def test_categories_endpoint_is_gender_specific(self):
        with mock.patch.object(self.m, "get_user_gender", return_value="Male"):
            res = self.client.get("/api/wardrobe/categories",
                                  headers={"Authorization": f"Bearer {self._token()}"})
        values = [c["value"] for s in res.get_json()["sections"] for c in s["categories"]]
        self.assertIn("Sherwani", values)
        self.assertNotIn("Saree", values)
        self.assertNotIn("Lehenga", values)

    def _auto(self, prediction):
        with mock.patch.object(self.m.garment_classifier, "is_available", return_value=True), \
             mock.patch.object(self.m.garment_classifier, "predict", return_value=prediction):
            return self._post(data={"category": "", "category_explicit": "false"})

    def test_broad_classifier_class_asks_the_user_and_saves_nothing(self):
        res = self._auto({"category": "Pant", "confidence": 0.93, "top": [("Pant", 0.93)]})
        self.assertEqual(res.status_code, 422)
        body = res.get_json()
        values = [o["value"] for o in body["options"]]
        self.assertIn("Track Pants", values)
        self.assertNotIn("Leggings", values)
        self.add_item.assert_not_called()
        self.cloud.assert_not_called()

    def test_reliable_confident_class_is_applied(self):
        """
        Saree used to be the example here. It is now a WEAK class on
        purpose - a draped saree and a flat-laid lehenga look nearly
        identical to the model, and it was confidently labelling one as
        the other - so the example moved to a class the model really is
        reliable on. The rule under test is unchanged: when the model
        is both confident AND trustworthy about a class, the user is
        not interrupted.
        """
        res = self._auto({"category": "Shirt", "confidence": 0.93,
                          "top": [("Shirt", 0.93)]})
        self.assertEqual(res.status_code, 200, res.get_json())
        self.assertEqual(self.add_item.call_args[0][1], "Shirt")

    def test_a_confident_saree_now_asks_because_lehengas_look_the_same(self):
        res = self._auto({"category": "Saree", "confidence": 0.9,
                          "top": [("Saree", 0.9)]})
        self.assertEqual(res.status_code, 422)
        values = [option["value"] for option in res.get_json()["options"]]
        self.assertIn("Saree", values)
        self.assertIn("Lehenga", values)
        self.add_item.assert_not_called()

    def test_unsure_classifier_asks_the_user(self):
        res = self._auto({"category": "Saree", "confidence": 0.3,
                          "top": [("Saree", 0.3), ("Lehenga", 0.25)]})
        self.assertEqual(res.status_code, 422)
        values = [o["value"] for o in res.get_json()["options"]]
        self.assertEqual(values[:2], ["Saree", "Lehenga"])
        self.add_item.assert_not_called()

    def _categories(self, gender):
        with mock.patch.object(self.m, "get_user_gender", return_value=gender):
            return self.client.get("/api/wardrobe/categories",
                                   headers={"Authorization": f"Bearer {self._token()}"})

    def test_categories_female_only_womens(self):
        res = self._categories("Female")
        values = [c["value"] for s in res.get_json()["sections"] for c in s["categories"]]
        for cat in ("Saree", "Casual Saree", "Wedding Saree", "Lehenga", "Salwar Suit", "Crop Top", "Skirt", "Dress"):
            self.assertIn(cat, values)
        for cat in ("Sherwani", "Kurta (Men)", "Nehru Jacket", "Dhoti Pants", "Tie", "Bow Tie"):
            self.assertNotIn(cat, values)

    def test_categories_male_exact_bug_report(self):
        res = self._categories("Male")
        values = [c["value"] for s in res.get_json()["sections"] for c in s["categories"]]
        for cat in ("Saree", "Casual Saree", "Wedding Saree", "Lehenga", "Salwar Suit", "Kurta (Women)",
                    "Anarkali", "Dupatta", "Skirt", "Dress", "Gown", "Jumpsuit", "Romper", "Crop Top",
                    "Leggings", "Blouse"):
            self.assertNotIn(cat, values)
        for cat in ("T-Shirt", "Shirt", "Formal Shirt", "Jeans", "Chinos", "Kurta (Men)", "Sherwani",
                    "Sports Jersey", "Track Pants", "Formal Shoes", "Tie", "Watch"):
            self.assertIn(cat, values)

    def test_categories_missing_gender_returns_nothing(self):
        for gender in (None, "", "other"):
            res = self._categories(gender)
            self.assertEqual(res.status_code, 409)
            self.assertNotIn("sections", res.get_json())

    def test_capabilities_endpoint(self):
        res = self.client.get("/api/wardrobe/capabilities",
                              headers={"Authorization": f"Bearer {self._token()}"})
        self.assertEqual(res.status_code, 200)
        self.assertIn("auto_category", res.get_json())


if __name__ == "__main__":
    unittest.main()
