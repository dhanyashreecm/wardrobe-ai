"""
ACCOUNT ROUTES - register, verify email, login, forgot/reset password.

These used to live directly in app.py. They moved here, with the SAME
URLs and the same response shapes, so they can be tested without
loading TensorFlow and the rest of the app (see
backend/tests/test_email_auth.py). app.py registers this blueprint.

The security rules, in one place:

  * A new account starts with email_verified = False and cannot log in
    (no token is ever issued) until the 6-digit code mailed to it is
    entered. Accounts from before this change have no such field and
    keep working exactly as before - see auth.is_email_verified().
  * The login notification is sent only AFTER the password check
    passed and a token was created, only to the address on the
    account, on a background thread, and never contains the password
    or the token. If the mail server is down, the login still succeeds.
  * Every route here is rate limited per client IP, and repeated wrong
    passwords lock the account for a few minutes (auth.verify_login).
"""

import threading
import time
from collections import defaultdict, deque

from flask import Blueprint, jsonify, request
from flask_jwt_extended import create_access_token

from backend import config, email_service
from backend.auth import (
    find_user_by_email,
    register_user,
    verify_login,
    create_password_reset_code,
    reset_password_with_code,
    create_email_verification_code,
    verify_email_with_code,
    RESET_CODE_MINUTES,
    VERIFY_CODE_MINUTES,
)
from backend.identity import normalize_email
from backend.login_context import client_ip, describe_login


auth_blueprint = Blueprint("auth_routes", __name__)


# =========================================================
# RATE LIMITING (in memory, per client IP and route group)
#
# Enough to stop a script hammering the login form or using the
# "send code" buttons to flood someone's inbox. It resets when the
# server restarts and is per-process - fine for this app's single
# Flask process; a multi-server deployment would move it to a shared
# store such as Redis.
# =========================================================

RATE_LIMITS = {
    # group: (max requests, window seconds)
    "login": (20, 15 * 60),
    "register": (10, 60 * 60),
    "verify": (20, 15 * 60),
    "send_code": (6, 15 * 60),
}

_hits = defaultdict(deque)
_hits_lock = threading.Lock()


def _rate_limited(group):
    limit, window = RATE_LIMITS[group]
    key = (group, client_ip(request))
    now = time.monotonic()
    with _hits_lock:
        bucket = _hits[key]
        while bucket and now - bucket[0] > window:
            bucket.popleft()
        if len(bucket) >= limit:
            return True
        bucket.append(now)
    return False


def _too_many():
    return jsonify({
        "success": False,
        "code": "rate_limited",
        "message": "Too many attempts from this device. Please wait a few "
                   "minutes and try again.",
    }), 429


def reset_rate_limits():
    """For tests."""
    with _hits_lock:
        _hits.clear()


def _body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _send_verification(result):
    """Mail a code produced by create_email_verification_code()."""
    if result.get("status") == "ok":
        email_service.send_verification_code(
            result.get("name"), result["email"], result["code"], VERIFY_CODE_MINUTES
        )


# =========================================================
# REGISTER
# =========================================================

@auth_blueprint.route("/api/register", methods=["POST"])
def register():
    if _rate_limited("register"):
        return _too_many()

    data = _body()

    name = (data.get("name") or "").strip()
    email = normalize_email(data.get("email"))
    password = data.get("password")
    # Gender is MANDATORY - register_user() is the actual gate that
    # rejects anything that isn't exactly "Male" or "Female".
    gender = data.get("gender")

    if not name or not email or not password:
        return jsonify({"success": False, "message": "All fields required"}), 400

    require_verification = config.REQUIRE_EMAIL_VERIFICATION

    if require_verification and not config.email_configured():
        # Creating the account would strand it: the code could never
        # arrive, so the owner could never log in.
        return jsonify({
            "success": False,
            "message": "Registration is temporarily unavailable: the server "
                       "can't send verification emails yet. Please try again later.",
        }), 503

    result = register_user(
        name, email, password, gender,
        require_verification=require_verification,
        allowed_domains=config.ALLOWED_EMAIL_DOMAINS,
    )

    if not result["success"]:
        return jsonify(result), 400

    if result.get("verification_required"):
        _send_verification(create_email_verification_code(email))
        return jsonify({
            "success": True,
            "verification_required": True,
            "email": email,
            "message": f"Account created. We sent a 6-digit code to {email} - "
                       "enter it to activate your account.",
        }), 200

    # Verification switched off (offline development): old behaviour.
    if config.SEND_WELCOME_EMAIL:
        email_service.send_welcome_email(name, email)

    return jsonify(result), 200


# =========================================================
# VERIFY EMAIL
# =========================================================

@auth_blueprint.route("/api/verify-email", methods=["POST"])
def verify_email():
    if _rate_limited("verify"):
        return _too_many()

    data = _body()
    email = normalize_email(data.get("email"))
    code = str(data.get("code") or "").strip()

    if not email or not code:
        return jsonify({"success": False, "message": "Email and code are required"}), 400

    result = verify_email_with_code(email, code)

    if result["success"] and not result.get("already_verified") and config.SEND_WELCOME_EMAIL:
        # The welcome message now waits until the address is proven,
        # so we never send it to a mailbox that didn't ask for it.
        user = find_user_by_email(email) or {}
        email_service.send_welcome_email(user.get("name"), email)

    return jsonify(result), (200 if result["success"] else 400)


@auth_blueprint.route("/api/verify-email/resend", methods=["POST"])
def resend_verification():
    if _rate_limited("send_code"):
        return _too_many()

    email = normalize_email(_body().get("email"))
    if not email:
        return jsonify({"success": False, "message": "Enter your email address"}), 400

    if not config.email_configured():
        return jsonify({
            "success": False,
            "message": "The server can't send email right now. Please try again later.",
        }), 503

    _send_verification(create_email_verification_code(email))

    # Same answer whatever happened, so this can't be used to find
    # out which addresses have (unverified) accounts.
    return jsonify({
        "success": True,
        "message": "If this address has an account waiting for verification, "
                   "a new code has been sent. Check your inbox (and spam). "
                   "You can request another code after a minute.",
    }), 200


# =========================================================
# LOGIN
# =========================================================

@auth_blueprint.route("/api/login", methods=["POST"])
def login():
    if _rate_limited("login"):
        return _too_many()

    data = _body()

    email = normalize_email(data.get("email"))
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"success": False, "message": "Enter your email and password"}), 400

    result = verify_login(email, password)

    if not result["success"]:
        if result.get("code") == "email_not_verified":
            # Right password, unverified address: make sure a working
            # code is on its way (throttled to one a minute).
            if config.email_configured():
                _send_verification(create_email_verification_code(result["email"]))
            return jsonify(result), 403
        if result.get("code") == "account_locked":
            return jsonify(result), 429
        return jsonify(result), 401

    # The ACCOUNT's canonical email, not the string as typed - so the
    # same account gets the same identity (and so the same wardrobe)
    # on every device: Windows, Mac, Android, iOS. Tokens are
    # stateless, so logging in on one device never logs out another.
    result["token"] = create_access_token(identity=result["email"])

    # Sent only now - after the password check passed and the token
    # exists - and only to the address stored on the account. Runs on
    # a background thread; any failure (mail server down, bad App
    # Password) is logged and swallowed, never turned into a failed
    # login. The email never includes the password or the token.
    if config.SEND_LOGIN_EMAIL:
        try:
            details = describe_login(request, data.get("client"))
            email_service.send_login_notification(result.get("name"), result["email"], details)
        except Exception as error:  # noqa: BLE001 - must never block login
            print(f"Login notification skipped: {type(error).__name__}")

    return jsonify(result), 200


# =========================================================
# FORGOT PASSWORD
# =========================================================

@auth_blueprint.route("/api/password/forgot", methods=["POST"])
def forgot_password():
    if _rate_limited("send_code"):
        return _too_many()

    email = normalize_email(_body().get("email"))

    if not email:
        return jsonify({"success": False, "message": "Enter your email address"}), 400

    if not config.email_configured():
        return jsonify({
            "success": False,
            "message": "Password reset by email isn't set up on the server yet."
        }), 503

    result = create_password_reset_code(email)
    if result["status"] == "ok":
        email_service.send_password_reset_code(
            result.get("name"), email, result["code"], RESET_CODE_MINUTES
        )

    # Same answer whether or not the account exists.
    return jsonify({
        "success": True,
        "message": "If an account exists for this email, a 6-digit code has been sent. "
                   "Check your inbox (and spam)."
    }), 200


@auth_blueprint.route("/api/password/reset", methods=["POST"])
def reset_password():
    if _rate_limited("verify"):
        return _too_many()

    data = _body()
    email = normalize_email(data.get("email"))
    code = str(data.get("code") or "").strip()
    new_password = data.get("new_password") or ""

    if not email or not code:
        return jsonify({"success": False, "message": "Email and code are required"}), 400

    result = reset_password_with_code(email, code, new_password)
    return jsonify(result), (200 if result["success"] else 400)
