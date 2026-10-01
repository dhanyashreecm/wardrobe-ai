"""
The Find Similar route (/api/ai/similar) after the "Shop this look"
upgrade: every field it returned before is still there, plus match
levels, a wardrobe summary and the photo's attributes.

The image models are replaced by stand-ins, so this runs in seconds
without loading TensorFlow or the datasets:

    python -m unittest backend.tests.test_similar_route -v
"""
import importlib
import io
import os
import sys
import unittest
from unittest import mock

try:
    import flask_jwt_extended  # noqa: F401
    from PIL import Image
    HAVE_DEPS = True
except ImportError:
    HAVE_DEPS = False


def _stub_modules():
    stubs = {
        "backend.clothing_similarity": mock.MagicMock(),
        "backend.indofashion_similarity": mock.MagicMock(),
        "backend.indofashion_classifier": mock.MagicMock(),
    }
    for heavy in ("tensorflow", "tensorflow.keras", "cv2"):
        try:
            importlib.import_module(heavy)
        except ImportError:
            stubs[heavy] = mock.MagicMock()
    return stubs


@unittest.skipUnless(HAVE_DEPS, "flask/Pillow not installed")
class SimilarRouteTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.modules = mock.patch.dict(sys.modules, _stub_modules())
        cls.modules.start()
        sys.modules.pop("backend.app", None)
        cls.app_module = importlib.import_module("backend.app")

    @classmethod
    def tearDownClass(cls):
        sys.modules.pop("backend.app", None)
        cls.modules.stop()

    def setUp(self):
        from flask_jwt_extended import create_access_token
        app = self.app_module
        self.saved_paths = []

        def wardrobe_search(path, items, top_k=5):
            self.saved_paths.append(path)
            self.assertTrue(os.path.exists(path))
            return [{"item_id": "a1", "image": "https://img/a.jpg", "category": "Kurta",
                     "color": "pink", "occasion": "festive", "similarity": 0.91},
                    {"item_id": "b2", "image": "https://img/b.jpg", "category": "Top",
                     "color": "blue", "occasion": "casual", "similarity": 0.55}]

        sys.modules["backend.clothing_similarity"].find_similar_in_wardrobe = wardrobe_search
        patches = [
            mock.patch.object(app, "get_user_gender", return_value="Female"),
            mock.patch.object(app, "get_user_wardrobe", return_value=[{"_id": "a1"}]),
            mock.patch.object(app, "find_similar", return_value=[{"image": "d/1.jpg", "similarity": 0.8}]),
            mock.patch.object(app, "predict_category", return_value={"category": "women_kurta", "confidence": 0.9}),
            mock.patch.object(app, "find_similar_indofashion", return_value=[]),
            mock.patch.object(app, "analyse_photo", return_value={"category": "kurta", "colour": "pink"}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        self.client = app.app.test_client()
        with app.app.app_context():
            self.auth = {"Authorization": "Bearer " + create_access_token(identity="a@gmail.com")}

    def post(self, name="IMG_0001.jpg"):
        out = io.BytesIO()
        Image.new("RGB", (40, 40), (200, 100, 150)).save(out, "JPEG")
        out.seek(0)
        return self.client.post("/api/ai/similar", headers=self.auth,
                                data={"image": (out, name)}, content_type="multipart/form-data")

    def test_existing_fields_kept_and_new_fields_added(self):
        r = self.post()
        self.assertEqual(r.status_code, 200, r.get_json())
        body = r.get_json()
        for key in ("wardrobe_results", "dataset_results", "indofashion_results", "category_results"):
            self.assertIn(key, body)
        self.assertEqual([i["match_level"] for i in body["wardrobe_results"]], ["very_close", "loose"])
        self.assertEqual(body["wardrobe_status"], "very_close")
        self.assertEqual(body["analysis"], {"category": "kurta", "colour": "pink"})

    def test_query_photo_gets_random_name_and_is_deleted(self):
        self.post("../../evil.jpg")
        self.post("IMG_0001.jpg")
        first, second = self.saved_paths
        self.assertNotEqual(first, second)
        self.assertNotIn("evil", first)
        self.assertFalse(os.path.exists(first))
        self.assertFalse(os.path.exists(second))

    def test_analysis_failure_does_not_break_search(self):
        with mock.patch.object(self.app_module, "analyse_photo", side_effect=RuntimeError("boom")):
            r = self.post()
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.get_json()["analysis"])


if __name__ == "__main__":
    unittest.main()
