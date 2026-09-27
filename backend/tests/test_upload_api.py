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
    buf = io.BytesIO()
    Image.new("RGB", (40, 60), (20, 20, 20)).save(buf, format="PNG")
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
            mock.patch.object(m.garment_classifier, "is_available", return_value=False),
        ]
        self.mocks = [p.start() for p in self.patches]
        self.add_item = self.mocks[2]
        self.cloud = self.mocks[4]
        self.detect = self.mocks[5]

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

    def test_capabilities_endpoint(self):
        res = self.client.get("/api/wardrobe/capabilities",
                              headers={"Authorization": f"Bearer {self._token()}"})
        self.assertEqual(res.status_code, 200)
        self.assertIn("auto_category", res.get_json())


if __name__ == "__main__":
    unittest.main()
