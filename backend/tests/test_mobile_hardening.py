"""
Phone-app hardening: login lockout, token-in-URL only for images,
CORS limited to the app's own origins, and a hard upload size cap.
Database and email are replaced with stand-ins.

    python -m unittest backend.tests.test_mobile_hardening -v
"""
import sys
import types
import unittest
from unittest import mock

try:
    import flask  # noqa: F401
    import flask_jwt_extended  # noqa: F401
    HAVE_DEPS = True
except ImportError:
    HAVE_DEPS = False


def _stub(name, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules.setdefault(name, module)


@unittest.skipUnless(HAVE_DEPS, "Flask not installed here - run on the Mac with ai_env312")
class MobileHardeningTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        _stub("backend.clothing_similarity", find_similar=lambda *a, **k: [])
        _stub("backend.indofashion_similarity", find_similar_indofashion=lambda *a, **k: [])
        _stub("backend.indofashion_classifier", predict_category=lambda path: {"category": "blouse", "confidence": 0.3})
        from backend import app as app_module
        cls.m = app_module
        cls.client = app_module.app.test_client()

    def setUp(self):
        self.m._login_failures.clear()

    def _login(self, password, ip="1.2.3.4"):
        return self.client.post("/api/login", json={"email": "a@example.com", "password": password},
                                environ_base={"REMOTE_ADDR": ip})

    def test_wrong_passwords_lock_that_email_and_address_for_a_while(self):
        bad = {"success": False, "message": "Invalid email or password"}
        with mock.patch.object(self.m, "verify_login", return_value=bad) as verify:
            for _ in range(self.m.LOGIN_FAIL_LIMIT):
                self.assertEqual(self._login("nope").status_code, 401)
            locked = self._login("nope")
            self.assertEqual(locked.status_code, 429)
            self.assertIn("Too many wrong passwords", locked.get_json()["message"])
            # the password isn't even checked while locked
            self.assertEqual(verify.call_count, self.m.LOGIN_FAIL_LIMIT)
            # a different address is not affected
            self.assertEqual(self._login("nope", ip="5.6.7.8").status_code, 401)

    def test_a_correct_login_clears_earlier_failures(self):
        bad = {"success": False, "message": "Invalid"}
        good = {"success": True, "email": "a@example.com", "name": "A"}
        with mock.patch.object(self.m, "verify_login", return_value=bad):
            for _ in range(self.m.LOGIN_FAIL_LIMIT - 1):
                self._login("nope")
        with mock.patch.object(self.m, "verify_login", return_value=good), \
                mock.patch.object(self.m.config, "SEND_LOGIN_EMAIL", False):
            ok = self._login("right")
            self.assertEqual(ok.status_code, 200)
            self.assertTrue(ok.get_json()["token"])
        self.assertEqual(self.m._login_failures, {})

    def _token(self):
        from flask_jwt_extended import create_access_token
        with self.m.app.app_context():
            return create_access_token(identity="a@example.com")

    def test_token_in_the_url_is_refused_outside_the_image_route(self):
        res = self.client.get(f"/api/user/profile?token={self._token()}")
        self.assertEqual(res.status_code, 401)

    def test_token_in_the_url_still_works_for_images(self):
        # Wrong folder for this account -> 403 from the ownership check,
        # which proves the ?token= was accepted (otherwise 401).
        res = self.client.get(f"/api/uploads/someone_else/x.jpg?token={self._token()}")
        self.assertNotEqual(res.status_code, 401)

    def test_cors_allows_the_phone_app_and_refuses_strangers(self):
        for origin in ("https://localhost", "capacitor://localhost", "http://localhost:3000", "http://192.168.1.20:3000"):
            res = self.client.get("/api/health", headers={"Origin": origin})
            self.assertEqual(res.headers.get("Access-Control-Allow-Origin"), origin, origin)
        res = self.client.get("/api/health", headers={"Origin": "https://evil.example"})
        self.assertIsNone(res.headers.get("Access-Control-Allow-Origin"))

    def test_huge_requests_get_a_friendly_413(self):
        big = b"x" * (21 * 1024 * 1024)
        res = self.client.post("/api/wardrobe/add", data=big, content_type="application/octet-stream",
                               headers={"Authorization": f"Bearer {self._token()}"})
        self.assertEqual(res.status_code, 413)
        self.assertIn("too large", res.get_json()["message"])


if __name__ == "__main__":
    unittest.main()
