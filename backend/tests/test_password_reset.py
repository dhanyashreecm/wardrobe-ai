"""
Forgot-password flow, end to end, without touching Atlas or Gmail.

    python -m unittest backend.tests.test_password_reset -v

Runs the REAL auth.py / auth_routes.py / email_service.py code against
an in-memory users collection. The last test goes one step further and
sends a real SMTP conversation to a tiny local SMTP server, to prove the
message is addressed (envelope AND To: header) to the account owner -
never to the sender/admin mailbox.
"""
import socket
import threading
import unittest
from datetime import datetime, timedelta
from unittest import mock

try:
    import bcrypt  # noqa: F401
    import flask  # noqa: F401
    import flask_jwt_extended  # noqa: F401
    HAVE_DEPS = True
except ImportError:
    HAVE_DEPS = False

from backend.tests.test_email_auth import FakeUsers

ADMIN = "wardrobe.sender@gmail.com"
USER_A = "dhanya.test@gmail.com"
USER_B = "ganga.test@gmail.com"


@unittest.skipUnless(HAVE_DEPS, "run with the project venv (ai_env)")
class PasswordResetFlowTests(unittest.TestCase):

    def setUp(self):
        from flask import Flask
        from flask_jwt_extended import JWTManager
        from backend import auth, auth_routes, config, email_service

        self.auth = auth
        self.users = FakeUsers(unique_ci="email")
        self.sent = []

        def fake_send_async(to, subject, text, html_body=None):
            self.sent.append({"to": to, "subject": subject, "text": text, "html": html_body})

        # Forgot Password now waits for the mail server's answer
        # (send_email) instead of sending in the background.
        def fake_send_email(to, subject, text, html_body=None):
            fake_send_async(to, subject, text, html_body)
            return True, "sent"

        for p in [
            mock.patch.object(auth, "users_collection", self.users),
            mock.patch.object(email_service, "send_async", fake_send_async),
            mock.patch.object(email_service, "send_email", fake_send_email),
            mock.patch.object(config, "SMTP_USERNAME", ADMIN),
            mock.patch.object(config, "email_configured", lambda: True),
            mock.patch.object(config, "TRUST_PROXY_HEADERS", False),
        ]:
            p.start()
            self.addCleanup(p.stop)

        auth_routes.reset_rate_limits()
        self.addCleanup(auth_routes.reset_rate_limits)

        app = Flask(__name__)
        app.config["JWT_SECRET_KEY"] = "test-secret-" + "x" * 40
        JWTManager(app)
        app.register_blueprint(auth_routes.auth_blueprint)
        self.client = app.test_client()

        for email, pw in ((USER_A, "oldpassA1"), (USER_B, "oldpassB1")):
            self.users.insert_one({
                "name": email.split(".")[0].title(), "email": email, "gender": "Female",
                "password_hash": bcrypt.hashpw(pw.encode(), bcrypt.gensalt()),
            })

    # helpers
    def forgot(self, email):
        return self.client.post("/api/password/forgot", json={"email": email})

    def reset(self, email, code, pw="brandnew99"):
        return self.client.post("/api/password/reset",
                                json={"email": email, "code": code, "new_password": pw})

    def login(self, email, pw):
        return self.client.post("/api/login", json={"email": email, "password": pw})

    def last_code(self):
        import re
        return re.search(r"\b(\d{6})\b", self.sent[-1]["text"]).group(1)

    def allow_resend(self, email):
        self.users.update_one({"email": email}, {"$set": {
            "reset_requested_at": datetime.utcnow() - timedelta(seconds=61)}})

    # Test 1 - existing registered user
    def test_1_registered_user_gets_code(self):
        r = self.forgot(USER_A)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(self.sent), 1)
        mail = self.sent[0]
        self.assertEqual(mail["to"], USER_A)
        self.assertEqual(mail["subject"], "Wardrobe AI Password Reset Code")
        self.assertRegex(mail["text"], r"\b\d{6}\b")
        for phrase in ("Wardrobe AI", "expires in 15 minutes", "Don't share it",
                       "didn't request a password reset"):
            self.assertIn(phrase, mail["text"])
        # never in the API response, never stored in plain text
        self.assertNotIn(self.last_code(), r.get_data(as_text=True))
        stored = self.users.find_one({"email": USER_A})
        self.assertNotEqual(stored["reset_code_hash"], self.last_code())
        self.assertNotIn("oldpassA1", mail["text"])

    # Test 2 - a different user's email goes to THAT user, not the admin
    def test_2_other_user_gets_their_own_email(self):
        self.forgot(USER_B)
        self.assertEqual([m["to"] for m in self.sent], [USER_B])
        self.assertNotIn(ADMIN, [m["to"] for m in self.sent])
        # typed with different case/spaces -> still the account's address
        self.forgot("  Dhanya.Test@GMAIL.com ")
        self.assertEqual(self.sent[-1]["to"], USER_A)

    # Test 3 - unregistered email: same safe answer, nothing sent
    def test_3_unregistered_email_is_not_revealed(self):
        known = self.forgot(USER_A).get_json()
        unknown = self.forgot("nobody.here@gmail.com").get_json()
        self.assertEqual(known, unknown)
        self.assertIn("If an account exists with this email", unknown["message"])
        self.assertEqual(len(self.sent), 1)

    # Test 4 - invalid email
    def test_4_invalid_email_rejected(self):
        for bad in ("", "abc", "name@gmail", "name@@gmail.com", "a b@gmail.com"):
            r = self.forgot(bad)
            self.assertEqual(r.status_code, 400, bad)
            self.assertFalse(r.get_json()["success"])
        self.assertEqual(self.sent, [])

    # Test 5 - expired code
    def test_5_expired_code_rejected(self):
        self.forgot(USER_A)
        code = self.last_code()
        self.users.update_one({"email": USER_A}, {"$set": {
            "reset_expires_at": datetime.utcnow() - timedelta(seconds=1)}})
        r = self.reset(USER_A, code)
        self.assertEqual(r.status_code, 400)
        self.assertIn("expired", r.get_json()["message"])
        self.assertEqual(self.login(USER_A, "oldpassA1").status_code, 200)

    # Test 6 - wrong code, with attempts capped
    def test_6_wrong_code_rejected_and_capped(self):
        self.forgot(USER_A)
        code = self.last_code()
        wrong = "000000" if code != "000000" else "111111"
        r = self.reset(USER_A, wrong)
        self.assertEqual(r.status_code, 400)
        self.assertIn("Wrong code. 4 attempt(s) left.", r.get_json()["message"])
        for _ in range(4):
            self.reset(USER_A, wrong)
        r = self.reset(USER_A, code)  # even the right code is now refused
        self.assertIn("Too many wrong codes", r.get_json()["message"])
        # a code for user A never works on user B
        self.allow_resend(USER_A)
        self.forgot(USER_A)
        self.assertEqual(self.reset(USER_B, self.last_code()).status_code, 400)

    # Test 7 - correct code resets password, code is single-use
    def test_7_correct_code_resets_password(self):
        self.forgot(USER_A)
        code = self.last_code()
        r = self.reset(USER_A, code)
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(self.login(USER_A, "brandnew99").status_code, 200)
        self.assertEqual(self.login(USER_A, "oldpassA1").status_code, 401)
        self.assertEqual(self.reset(USER_A, code, "another99").status_code, 400)
        # the other user is untouched
        self.assertEqual(self.login(USER_B, "oldpassB1").status_code, 200)

    # Test 8 - resend: new code, old one invalid, same recipient
    def test_8_resend_invalidates_previous_code(self):
        self.forgot(USER_A)
        first = self.last_code()
        self.forgot(USER_A)  # within 60s: throttled, no second email
        self.assertEqual(len(self.sent), 1)
        self.allow_resend(USER_A)
        self.forgot(USER_A)
        self.assertEqual(len(self.sent), 2)
        second = self.last_code()
        self.assertEqual(self.sent[1]["to"], USER_A)
        if first != second:
            self.assertEqual(self.reset(USER_A, first).status_code, 400)
        self.assertEqual(self.reset(USER_A, second).status_code, 200)

    # Step 2 on its own screen: verify-code checks without consuming
    def test_verify_code_step(self):
        self.forgot(USER_A)
        code = self.last_code()
        wrong = "000000" if code != "000000" else "111111"
        v = lambda c: self.client.post("/api/password/verify-code",
                                       json={"email": USER_A, "code": c})
        r = v(wrong)
        self.assertEqual(r.status_code, 400)
        self.assertIn("4 attempt(s) left", r.get_json()["message"])
        self.assertEqual(v(code).status_code, 200)
        self.assertEqual(v(code).status_code, 200)       # not used up yet
        self.assertEqual(self.reset(USER_A, code).status_code, 200)
        self.assertEqual(v(code).status_code, 400)       # used once -> gone
        # wrong guesses at the verify step count toward the same cap of 5
        self.allow_resend(USER_A)
        self.forgot(USER_A)
        code = self.last_code()
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(5):
            v(wrong)
        self.assertIn("Too many wrong codes", v(code).get_json()["message"])
        self.assertEqual(self.reset(USER_A, code).status_code, 400)

    # The exact journey: register -> login -> forgot -> code -> new pw -> login
    def test_new_user_full_journey_no_extra_auth(self):
        from backend import config
        with mock.patch.object(config, "REQUIRE_EMAIL_VERIFICATION", False), \
             mock.patch.object(config, "SEND_WELCOME_EMAIL", False), \
             mock.patch.object(config, "SEND_LOGIN_EMAIL", False):
            new_user = "new.person@gmail.com"
            r = self.client.post("/api/register", json={
                "name": "New Person", "email": new_user,
                "password": "firstpass1", "gender": "Female"})
            self.assertEqual(r.status_code, 200, r.get_json())
            self.assertEqual(self.login(new_user, "firstpass1").status_code, 200)

            self.assertEqual(self.forgot(new_user).status_code, 200)
            self.assertEqual(self.sent[-1]["to"], new_user)
            code = self.last_code()
            r = self.client.post("/api/password/verify-code",
                                 json={"email": new_user, "code": code})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(self.reset(new_user, code, "secondpass2").status_code, 200)

            self.assertEqual(self.login(new_user, "secondpass2").status_code, 200)
            self.assertEqual(self.login(new_user, "firstpass1").status_code, 401)
            # nobody else got this user's code
            self.assertEqual({m["to"] for m in self.sent}, {new_user})

    # Gmail refuses -> the user is TOLD, and "Send again" works at once
    def test_smtp_failure_reported_and_retry_allowed(self):
        from backend import email_service
        with mock.patch.object(email_service, "send_email",
                               lambda *a, **k: (False, "the mail server closed the connection")):
            r = self.forgot(USER_A)
        self.assertEqual(r.status_code, 502)
        self.assertEqual(r.get_json()["code"], "email_send_failed")
        self.assertIn("couldn't send", r.get_json()["message"])
        self.assertNotIn("reset_code_hash", self.users.find_one({"email": USER_A}))
        self.forgot(USER_A)                      # immediately, mail works again
        self.assertEqual([m["to"] for m in self.sent], [USER_A])
        self.assertEqual(self.reset(USER_A, self.last_code()).status_code, 200)

    # A record stored with odd case/spaces is still found, and the email
    # goes to the address ON the account.
    def test_legacy_stored_address_is_matched(self):
        self.users.insert_one({"name": "Old", "email": " Old.User@Gmail.com ",
                               "gender": "Female",
                               "password_hash": bcrypt.hashpw(b"x123456", bcrypt.gensalt())})
        r = self.forgot("old.user@gmail.com  ")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0]["to"], "old.user@gmail.com")

    # logging must never contain the code
    def test_logs_never_contain_code(self):
        with self.assertLogs("backend.email_service", level="INFO") as logs:
            self.forgot(USER_A)
        joined = "\n".join(logs.output)
        self.assertIn("Password reset requested", joined)
        self.assertIn(f"email recipient: {USER_A}", joined)
        self.assertNotIn(self.last_code(), joined)


@unittest.skipUnless(HAVE_DEPS, "run with the project venv (ai_env)")
class RealSmtpRecipientTest(unittest.TestCase):
    """A real SMTP conversation with a minimal local server."""

    def test_envelope_and_header_go_to_account_owner(self):
        from backend import config, email_service

        received = {}
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]

        def serve():
            conn, _ = srv.accept()
            f = conn.makefile("rwb")

            def say(line):
                f.write(line.encode() + b"\r\n")
                f.flush()
            say("220 test")
            data_mode, body = False, []
            for raw in f:
                line = raw.decode().rstrip("\r\n")
                if data_mode:
                    if line == ".":
                        data_mode = False
                        received["data"] = "\n".join(body)
                        say("250 ok")
                    else:
                        body.append(line)
                    continue
                cmd = line.upper()
                if cmd.startswith("EHLO"):
                    say("250-test")
                    say("250 AUTH PLAIN LOGIN")
                elif cmd.startswith("AUTH"):
                    say("235 ok")
                elif cmd.startswith("MAIL FROM"):
                    received["from"] = line
                    say("250 ok")
                elif cmd.startswith("RCPT TO"):
                    received.setdefault("rcpt", []).append(line)
                    say("250 ok")
                elif cmd == "DATA":
                    data_mode = True
                    say("354 go")
                elif cmd == "QUIT":
                    say("221 bye")
                    break
                else:
                    say("250 ok")
            conn.close()

        t = threading.Thread(target=serve, daemon=True)
        t.start()

        with mock.patch.object(config, "SMTP_HOST", "127.0.0.1"), \
             mock.patch.object(config, "SMTP_PORT", port), \
             mock.patch.object(config, "SMTP_USE_SSL", False), \
             mock.patch.object(config, "SMTP_USERNAME", ADMIN), \
             mock.patch.object(config, "SMTP_PASSWORD", "pw"), \
             mock.patch.object(config, "email_configured", lambda: True), \
             mock.patch("smtplib.SMTP.starttls", lambda self, *a, **k: (220, b"")):
            subject, text, html = email_service.build_password_reset_email("Ganga", "123456", 15)
            ok, detail = email_service.send_email(USER_B, subject, text, html)

        t.join(5)
        srv.close()
        self.assertTrue(ok, detail)
        self.assertEqual([r.upper() for r in received["rcpt"]], [f"RCPT TO:<{USER_B}>".upper()])
        self.assertIn(ADMIN, received["from"])
        self.assertIn(f"To: {USER_B}", received["data"])
        self.assertIn("Subject: Wardrobe AI Password Reset Code", received["data"])


if __name__ == "__main__":
    unittest.main()
