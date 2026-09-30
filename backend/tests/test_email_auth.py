"""
Email verification, login notification and login-security tests.

They run the REAL auth.py / auth_routes.py / email_service.py code
against an in-memory stand-in for MongoDB and a fake mail sender, so
they never touch Atlas or send a real email:

    python -m unittest backend.tests.test_email_auth -v
"""
import re
import smtplib
import unittest
from datetime import datetime, timezone
from unittest import mock

try:
    import bcrypt  # noqa: F401
    import flask  # noqa: F401
    import flask_jwt_extended  # noqa: F401
    import pymongo  # noqa: F401
    HAVE_DEPS = True
except ImportError:
    HAVE_DEPS = False

from backend.tests.test_cloud_accounts import FakeCollection as _BaseFake, _match


class FakeUsers(_BaseFake):
    """Adds $unset/$inc to the shared fake, as auth.py now uses them."""

    def update_one(self, flt, update):
        for d in self.docs:
            if _match(d, flt):
                d.update(update.get("$set", {}))
                for key in update.get("$unset", {}):
                    d.pop(key, None)
                for key, amount in update.get("$inc", {}).items():
                    d[key] = d.get(key, 0) + amount
                return


WINDOWS_CHROME = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
MAC_SAFARI = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
              "(KHTML, like Gecko) Version/17.5 Safari/605.1.15")
ANDROID_CHROME = ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0.0.0 Mobile Safari/537.36")
IPHONE_SAFARI = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
                 "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1")
IPAD_DESKTOP_MODE = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
                     "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1")
EDGE = WINDOWS_CHROME + " Edg/128.0.0.0"


@unittest.skipUnless(HAVE_DEPS, "flask/bcrypt/pymongo not installed here - run with ai_env")
class EmailAuthFlowTests(unittest.TestCase):

    def setUp(self):
        from flask import Flask
        from flask_jwt_extended import JWTManager
        from backend import auth, auth_routes, config, email_service

        self.auth = auth
        self.users = FakeUsers(unique_ci="email")
        self.sent = []

        def fake_send_async(to, subject, text, html_body=None):
            self.sent.append({"to": to, "subject": subject, "text": text, "html": html_body})

        patches = [
            mock.patch.object(auth, "users_collection", self.users),
            mock.patch.object(email_service, "send_async", fake_send_async),
            mock.patch.object(config, "REQUIRE_EMAIL_VERIFICATION", True),
            mock.patch.object(config, "SEND_LOGIN_EMAIL", True),
            mock.patch.object(config, "SEND_WELCOME_EMAIL", True),
            mock.patch.object(config, "ALLOWED_EMAIL_DOMAINS", ()),
            mock.patch.object(config, "TRUST_PROXY_HEADERS", False),
            mock.patch.object(config, "email_configured", lambda: True),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        auth_routes.reset_rate_limits()
        self.addCleanup(auth_routes.reset_rate_limits)

        app = Flask(__name__)
        app.config["JWT_SECRET_KEY"] = "test-secret-" + "x" * 40
        JWTManager(app)
        app.register_blueprint(auth_routes.auth_blueprint)
        self.client = app.test_client()

    # ---------------- helpers ----------------

    def register(self, email="ganga@gmail.com", password="secret123", name="Ganga"):
        return self.client.post("/api/register", json={
            "name": name, "email": email, "password": password, "gender": "Female"})

    def login(self, email="ganga@gmail.com", password="secret123", ua=WINDOWS_CHROME, client=None):
        body = {"email": email, "password": password}
        if client is not None:
            body["client"] = client
        return self.client.post("/api/login", json=body, headers={"User-Agent": ua})

    def last_code(self):
        for mail in reversed(self.sent):
            match = re.search(r"\b(\d{6})\b", mail["text"])
            if match and "Verify" in mail["subject"]:
                return match.group(1)
        self.fail("no verification email was sent")

    def add_legacy_user(self, email="old@gmail.com", password="oldpass1"):
        import bcrypt
        self.users.docs.append({
            "_id": "legacy", "name": "Old User", "email": email, "gender": "Female",
            "password_hash": bcrypt.hashpw(password.encode(), bcrypt.gensalt()),
        })

    # ---------------- existing accounts ----------------

    def test_existing_account_without_flag_logs_in_unchanged(self):
        self.add_legacy_user()
        r = self.login("Old@Gmail.com", "oldpass1")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["token"])
        self.assertNotIn("email_verified", self.users.docs[0])

    # ---------------- registration + verification ----------------

    def test_registration_sends_code_and_blocks_login_until_verified(self):
        r = self.register()
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertTrue(body["verification_required"])
        self.assertNotIn("code", body)
        self.assertNotIn(self.last_code(), r.get_data(as_text=True))
        self.assertIs(self.users.docs[0]["email_verified"], False)
        self.assertNotIn("secret123", str(self.sent))
        # The raw code is never stored - only its hash.
        self.assertNotIn(self.last_code(), str(self.users.docs[0]))

        r = self.login()
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.get_json()["code"], "email_not_verified")
        self.assertNotIn("token", r.get_json())
        self.assertFalse(any("New Login" in m["subject"] for m in self.sent))

    def test_wrong_password_does_not_reveal_verification_state(self):
        self.register()
        r = self.login(password="wrongpass")
        self.assertEqual(r.status_code, 401)
        self.assertNotEqual(r.get_json().get("code"), "email_not_verified")

    def test_verify_with_correct_code_then_login(self):
        self.register()
        code = self.last_code()
        bad = "000000" if code != "000000" else "111111"
        r = self.client.post("/api/verify-email", json={"email": "ganga@gmail.com", "code": bad})
        self.assertEqual(r.status_code, 400)

        r = self.client.post("/api/verify-email", json={"email": "GANGA@gmail.com", "code": code})
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertIs(self.users.docs[0]["email_verified"], True)
        self.assertNotIn("verify_code_hash", self.users.docs[0])
        self.assertTrue(any(m["subject"].startswith("Welcome") for m in self.sent))

        r = self.login()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["token"])

    def test_code_attempts_are_capped(self):
        self.register()
        code = self.last_code()
        bad = "000000" if code != "000000" else "111111"
        for _ in range(5):
            self.client.post("/api/verify-email", json={"email": "ganga@gmail.com", "code": bad})
        r = self.client.post("/api/verify-email", json={"email": "ganga@gmail.com", "code": code})
        self.assertEqual(r.status_code, 400)
        self.assertIn("Too many", r.get_json()["message"])

    def test_resend_is_throttled_and_generic(self):
        self.register()
        before = len(self.sent)
        r = self.client.post("/api/verify-email/resend", json={"email": "ganga@gmail.com"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(self.sent), before)  # within 60s of the first code
        r2 = self.client.post("/api/verify-email/resend", json={"email": "nobody@gmail.com"})
        self.assertEqual(r2.get_json()["message"], r.get_json()["message"])

    def test_unverified_signup_can_be_reclaimed_but_verified_cannot(self):
        self.register(password="squatter1", name="Squatter")
        r = self.register(password="realowner1", name="Real Owner")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(self.users.docs), 1)
        self.assertEqual(self.users.docs[0]["name"], "Real Owner")

        self.users.docs[0]["email_verified"] = True
        r = self.register(password="another1")
        self.assertEqual(r.status_code, 400)
        self.assertIn("already registered", r.get_json()["message"])

    def test_registration_refused_when_email_cannot_be_sent(self):
        from backend import config
        with mock.patch.object(config, "email_configured", lambda: False):
            r = self.register()
        self.assertEqual(r.status_code, 503)
        self.assertEqual(self.users.docs, [])

    def test_password_reset_also_verifies_email(self):
        self.register()
        result = self.auth.create_password_reset_code("ganga@gmail.com")
        r = self.auth.reset_password_with_code("ganga@gmail.com", result["code"], "newpass99")
        self.assertTrue(r["success"])
        self.assertIs(self.users.docs[0]["email_verified"], True)
        self.assertEqual(self.login(password="newpass99").status_code, 200)

    # ---------------- email validation ----------------

    def test_email_validation(self):
        validate = self.auth.validate_email_address
        for good in ("dhanya.shree616@gmail.com", "a+wardrobe@gmail.com",
                     "someone@iisc.ac.in", "x@sub.example.co"):
            self.assertIsNone(validate(good), good)
        for bad in ("", "plainaddress", "a@gmail", "a@@gmail.com", "a@gmail..com",
                    ".a@gmail.com", "a b@gmail.com", "a_b@gmail.com", "a@-bad.com",
                    "x" * 65 + "@gmail.com"):
            self.assertIsNotNone(validate(bad), bad)
        self.assertIsNotNone(validate("me@yahoo.com", ("gmail.com",)))
        self.assertIsNone(validate("me@gmail.com", ("gmail.com",)))

    def test_short_password_rejected_at_registration(self):
        r = self.register(password="123")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.users.docs, [])

    # ---------------- login notification ----------------

    def test_login_notification_contents(self):
        self.add_legacy_user()
        r = self.login("old@gmail.com", "oldpass1", ua=WINDOWS_CHROME,
                       client={"timezone": "Asia/Kolkata", "standalone": False})
        self.assertEqual(r.status_code, 200)
        token = r.get_json()["token"]

        notices = [m for m in self.sent if m["subject"] == "New Login to Your Wardrobe-AI Account"]
        self.assertEqual(len(notices), 1)
        mail = notices[0]
        self.assertEqual(mail["to"], "old@gmail.com")
        for expected in ("Wardrobe-AI", "successfully accessed", "Date:", "Time:",
                         "Desktop - Windows", "Chrome 128", "Location: Not available",
                         "IST", "don't recognize this login", "Security Team"):
            self.assertIn(expected, mail["text"])
        for secret in ("oldpass1", token):
            self.assertNotIn(secret, mail["text"])
            self.assertNotIn(secret, mail["html"])

    def test_no_notification_on_failed_login(self):
        self.add_legacy_user()
        self.login("old@gmail.com", "wrong")
        self.login("stranger@gmail.com", "whatever")
        self.assertFalse(any("New Login" in m["subject"] for m in self.sent))

    def test_mail_server_down_does_not_block_login(self):
        from backend import config, email_service
        self.add_legacy_user()
        with mock.patch.object(email_service, "send_async",
                               lambda *a, **k: email_service.send_email(*a, **k)), \
             mock.patch.object(config, "SMTP_USE_SSL", False), \
             mock.patch.object(smtplib, "SMTP", side_effect=OSError("down")):
            r = self.login("old@gmail.com", "oldpass1")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["token"])

    def test_notification_builder_crash_does_not_block_login(self):
        from backend import auth_routes
        self.add_legacy_user()
        with mock.patch.object(auth_routes, "describe_login", side_effect=RuntimeError):
            r = self.login("old@gmail.com", "oldpass1")
        self.assertEqual(r.status_code, 200)

    def test_user_supplied_text_is_escaped_in_html(self):
        from backend import email_service
        _, _, html_body = email_service.build_login_notification(
            "<script>x</script>", {"device": "<b>evil</b>", "browser": "B"})
        self.assertNotIn("<script>", html_body)
        self.assertNotIn("<b>evil</b>", html_body)

    # ---------------- brute force / rate limits ----------------

    def test_account_locks_after_repeated_wrong_passwords(self):
        self.add_legacy_user()
        for _ in range(5):
            self.assertEqual(self.login("old@gmail.com", "wrong").status_code, 401)
        r = self.login("old@gmail.com", "oldpass1")
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.get_json()["code"], "account_locked")

        result = self.auth.create_password_reset_code("old@gmail.com")
        self.auth.reset_password_with_code("old@gmail.com", result["code"], "brandnew1")
        self.assertEqual(self.login("old@gmail.com", "brandnew1").status_code, 200)

    def test_successful_login_clears_failure_count(self):
        self.add_legacy_user()
        for _ in range(4):
            self.login("old@gmail.com", "wrong")
        self.assertEqual(self.login("old@gmail.com", "oldpass1").status_code, 200)
        self.assertNotIn("failed_login_attempts", self.users.docs[0])

    def test_ip_rate_limit(self):
        from backend import auth_routes
        with mock.patch.dict(auth_routes.RATE_LIMITS, {"login": (3, 60)}):
            codes = [self.login("x@gmail.com", "nope").status_code for _ in range(4)]
        self.assertEqual(codes[-1], 429)

    # ---------------- multiple devices ----------------

    def test_same_account_on_every_device_gets_same_identity(self):
        from flask_jwt_extended import decode_token
        self.add_legacy_user()
        identities = set()
        for ua in (WINDOWS_CHROME, MAC_SAFARI, ANDROID_CHROME, IPHONE_SAFARI):
            r = self.login("old@gmail.com", "oldpass1", ua=ua)
            self.assertEqual(r.status_code, 200)
            with self.client.application.app_context():
                identities.add(decode_token(r.get_json()["token"])["sub"])
        self.assertEqual(identities, {"old@gmail.com"})


class LoginContextTests(unittest.TestCase):

    def test_user_agents(self):
        from backend.login_context import parse_user_agent as p
        self.assertEqual(p(WINDOWS_CHROME), {"os": "Windows", "device_type": "Desktop", "browser": "Chrome 128"})
        self.assertEqual(p(MAC_SAFARI), {"os": "macOS", "device_type": "Desktop", "browser": "Safari 17"})
        self.assertEqual(p(ANDROID_CHROME), {"os": "Android 14", "device_type": "Mobile", "browser": "Chrome 128"})
        self.assertEqual(p(IPHONE_SAFARI), {"os": "iOS 17", "device_type": "Mobile", "browser": "Safari 17"})
        self.assertEqual(p(IPAD_DESKTOP_MODE)["device_type"], "Tablet")
        self.assertEqual(p(EDGE)["browser"], "Microsoft Edge 128")
        self.assertEqual(p(""), {"os": "", "device_type": "", "browser": ""})

    def test_time_zone_formatting(self):
        from backend.login_context import format_login_time
        when = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
        date_text, time_text = format_login_time(when, "Asia/Kolkata")
        self.assertEqual(date_text, "Wednesday, 30 September 2026")
        self.assertEqual(time_text, "5:30 PM (IST)")
        # Garbage from the client falls back to the configured default.
        _, fallback = format_login_time(when, "../../etc/passwd")
        self.assertIn("5:30 PM", fallback)

    @unittest.skipUnless(HAVE_DEPS, "flask not installed")
    def test_location_only_from_trusted_proxy(self):
        from flask import Flask, request
        from backend import config
        from backend.login_context import describe_login
        app = Flask(__name__)
        headers = {"User-Agent": ANDROID_CHROME, "X-Forwarded-For": "8.8.8.8",
                   "CF-IPCity": "Bengaluru", "CF-IPCountry": "IN"}

        with mock.patch.object(config, "TRUST_PROXY_HEADERS", False):
            with app.test_request_context("/", headers=headers, environ_base={"REMOTE_ADDR": "127.0.0.1"}):
                self.assertEqual(describe_login(request)["location"], "")

        with mock.patch.object(config, "TRUST_PROXY_HEADERS", True):
            with app.test_request_context("/", headers=headers, environ_base={"REMOTE_ADDR": "10.0.0.1"}):
                details = describe_login(request, {"standalone": True})
        self.assertEqual(details["location"], "Bengaluru, IN")
        self.assertEqual(details["device"], "Mobile - Android 14")
        self.assertIn("installed app", details["browser"])


if __name__ == "__main__":
    unittest.main()
