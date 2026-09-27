import bcrypt
import secrets
from datetime import datetime, timedelta
from pymongo.errors import DuplicateKeyError

from backend.db import users_collection
from backend.identity import normalize_email, email_match_filter

# The only two accepted values, anywhere gender is written. Kept as
# a single source of truth so register/migrate can't drift apart on
# what's valid.
VALID_GENDERS = {"Male", "Female"}


# =========================================================
# ACCOUNT LOOKUP - the one place that finds a user by email
#
# Accounts live ONLY in the shared Atlas database (see db.py - there
# is no local fallback), and an account is identified by its
# NORMALISED email (see identity.py). Exact match on the normalised
# form is tried first (fast, uses the unique index); a case-/space-
# insensitive match is the fallback for accounts stored before
# normalisation existed, so such an account is still found instead of
# looking like "no account" and inviting a duplicate registration.
# =========================================================

def find_user_by_email(email):
    canonical = normalize_email(email)
    if not canonical:
        return None
    user = users_collection.find_one({"email": canonical})
    if user:
        return user
    return users_collection.find_one(email_match_filter(canonical))


def _hash_bytes(stored):
    """
    The stored bcrypt hash as bytes, whatever shape it was saved in.
    Hashes written by this app are BSON binary (bytes), but a record
    created or edited by another tool (Atlas UI, a script, a JSON
    import) can hold the same hash as a str - which used to crash
    bcrypt.checkpw with a TypeError and make a correct password look
    like a server error. Returns None if there is no usable hash.
    """
    if stored is None:
        return None
    if isinstance(stored, str):
        stored = stored.encode("utf-8")
    try:
        stored = bytes(stored)
    except Exception:
        return None
    if not stored.startswith((b"$2a$", b"$2b$", b"$2y$")) or len(stored) != 60:
        return None
    return stored


def check_password(password, stored_hash):
    """True only when `password` matches the stored bcrypt hash."""
    hashed = _hash_bytes(stored_hash)
    if hashed is None or not isinstance(password, str) or not password:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed)
    except ValueError:
        return False


def register_user(name, email, password, gender=None):
    """
    Gender is now MANDATORY and PERMANENTLY LOCKED at registration:
    once set here, nothing in this codebase ever updates it again
    (see update_item()/allowed_fields in wardrobe.py, and the fact
    that there is no "update user" route at all in app.py - the only
    other way a stored gender can change is the one-time
    migrate_user_gender() below, and only for an account that has
    none yet). The frontend is expected to require a choice before
    calling this, but that's a UX nicety, not the real guard - this
    function is the real guard, since it's the only thing that
    actually writes to the users collection.
    """
    if gender not in VALID_GENDERS:
        return {
            "success": False,
            "message": 'Please choose "Male" or "Female" to continue - '
                        "this sets your wardrobe categories and can't "
                        "be changed later."
        }

    email = normalize_email(email)

    if not email or "@" not in email:
        return {"success": False, "message": "Please enter a valid email address"}

    # Case-insensitive: "Ganga@Gmail.com" must find the existing
    # "ganga@gmail.com" account rather than create a second one.
    if find_user_by_email(email):
        return {"success": False, "message": "Email already registered"}

    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())

    user = {
        "name": name,
        "email": email,
        "password_hash": hashed,
        "gender": gender,
        "created_at": datetime.utcnow()
    }

    try:
        users_collection.insert_one(user)
    except DuplicateKeyError:
        # The unique index (db.ensure_indexes) caught a registration
        # racing another one for the same address.
        return {"success": False, "message": "Email already registered"}
    return {"success": True, "message": "Registration successful"}


def verify_login(email, password):
    """
    Authenticates against the ONE shared (Atlas) account for this
    email. The returned "email" is the account's canonical address,
    which app.py uses as the login token's identity - so every device
    that logs in to this account gets the same identity, and therefore
    the same wardrobe, trips and profile.
    """
    user = find_user_by_email(email)
    if not user:
        return {"success": False, "message": "No account with this email"}

    if _hash_bytes(user.get("password_hash")) is None:
        # Never silently reset or replace a password here - report it
        # so the account can be repaired deliberately (password reset).
        print(f"Login refused: account {user.get('_id')} has no valid password hash")
        return {
            "success": False,
            "message": "This account's password needs to be reset - use "
                       "'Forgot password' to set a new one.",
        }

    if check_password(password, user.get("password_hash")):
        return {
            "success": True,
            "name": user.get("name"),
            "email": normalize_email(user.get("email")),
            # None here means a pre-existing account created before
            # gender became mandatory. The frontend treats a missing
            # gender as "needs one-time setup" (see Login.js) rather
            # than ever silently assigning one.
            "gender": user.get("gender")
        }
    else:
        return {"success": False, "message": "Incorrect password"}


def get_user_profile(email):
    """
    Full profile info for the PROFILE PAGE - name, email, gender,
    plus the two new optional fields (phone, profile_picture) added
    this round. Only ever called with the CALLER's own email (taken
    from their JWT in app.py, never a value supplied by the client),
    so this can't be used to look up someone else's profile.

    Returns None if the account somehow doesn't exist (shouldn't
    happen for a valid JWT, but callers should treat None as a 404,
    not assume a dict back).
    """
    user = find_user_by_email(email)

    if not user:
        return None

    return {
        "name": user.get("name"),
        "email": user.get("email"),
        "gender": user.get("gender"),
        # Both optional and absent on most existing accounts - "" is
        # the honest "not set yet" value the frontend already treats
        # every other optional field (color, material, styling) as.
        "phone": user.get("phone", ""),
        "profile_picture": user.get("profile_picture", ""),
        # Default city/location for weather-aware recommendations
        # (see backend.app's /api/ai/recommend, which falls back to
        # this when the request doesn't pass an explicit ?city=) -
        # same "" not-set-yet convention as phone above.
        "city": user.get("city", ""),
    }


def update_user_profile(email, name=None, phone=None, city=None):
    """
    Updates ONLY "name", "phone" and "city" - fields that are
    genuinely safe to let a user change themselves.

    Email is deliberately NOT editable here: it's the account's
    permanent identifier - the JWT identity, and every wardrobe item/
    trip's user_email, are keyed on it - so changing it would orphan
    all of that account's existing data. Gender is permanently locked
    at registration (see register_user/migrate_user_gender above,
    which remain the only things that ever write "gender"). Neither
    is accepted as a parameter here at all, so there's no field name
    a caller could pass to slip past that.
    """
    set_fields = {}

    if name is not None and name.strip():
        set_fields["name"] = name.strip()

    if phone is not None:
        # "" is a meaningful value here (clearing a previously-set
        # phone number) - unlike name, which should never be blanked
        # out to empty since every account must have SOME name.
        set_fields["phone"] = phone.strip()

    if city is not None:
        # Same "clearing is meaningful" reasoning as phone - a user
        # who travels a lot may deliberately want to go back to
        # entering a city by hand each time instead of a stale default.
        set_fields["city"] = city.strip()

    if not set_fields:
        return {"success": False, "message": "Nothing to update"}

    user = find_user_by_email(email)
    if not user:
        return {"success": False, "message": "No account with this email"}

    users_collection.update_one({"_id": user["_id"]}, {"$set": set_fields})

    return {"success": True}


def set_profile_picture(email, picture_url):
    """
    Records the URL of a just-uploaded profile picture (see
    app.py's /api/user/profile/picture route, which does the actual
    file handling - this just points the account at the result).
    """
    user = find_user_by_email(email)
    if user:
        users_collection.update_one(
            {"_id": user["_id"]}, {"$set": {"profile_picture": picture_url}}
        )


def delete_user_account(email):
    """
    Permanently deletes the account itself. Does NOT delete that
    user's wardrobe items/trips/uploaded files - see app.py's
    /api/user/account DELETE route, which calls this ALONGSIDE
    wardrobe.delete_all_for_user() and trips.delete_all_for_user()
    and removes their upload folder from disk, so all of an account's
    data is cleaned up together rather than this function silently
    doing only part of the job.

    Returns False if there was no such account, so the caller can
    turn that into a 404 instead of a silent success.
    """
    user = find_user_by_email(email)
    if not user:
        return False
    result = users_collection.delete_one({"_id": user["_id"]})
    return result.deleted_count > 0


def get_user_gender(email):
    """
    Looks up just the stored gender for a user, if any. Used by
    app.py to gender-guard AI auto-detection, similar search, and
    recommendations.
    """

    user = find_user_by_email(email)
    return (user or {}).get("gender")


def migrate_user_gender(email, gender):
    """
    ONE-TIME migration path for an account created before gender was
    mandatory. Deliberately narrow:
      - rejects an invalid gender value, exactly like register_user.
      - rejects outright if the account already HAS a gender set -
        this is what makes the lock permanent: this function can
        only ever take an account from "no gender" to "one gender",
        never change an existing one. There is no other route/field
        anywhere that writes to "gender" after this.
      - never auto-assigns anything - the caller (a real logged-in
        request) must supply an explicit choice.
    """

    if gender not in VALID_GENDERS:
        return {
            "success": False,
            "message": 'Please choose "Male" or "Female".'
        }

    user = find_user_by_email(email)

    if not user:
        return {"success": False, "message": "No account with this email"}

    if user.get("gender"):
        return {
            "success": False,
            "message": "Your account's gender is already set and can't be changed."
        }

    users_collection.update_one(
        {"_id": user["_id"]},
        {"$set": {"gender": gender}}
    )

    return {"success": True, "gender": gender}


# =========================================================
# FORGOT PASSWORD (6-digit code sent by email)
#
# The code itself is never stored - only its bcrypt hash, exactly
# like a password. It expires after RESET_CODE_MINUTES, allows only
# RESET_MAX_ATTEMPTS wrong guesses, and is wiped once used.
# =========================================================

RESET_CODE_MINUTES = 15
RESET_MAX_ATTEMPTS = 5
RESET_RESEND_SECONDS = 60
MIN_PASSWORD_LENGTH = 6


def create_password_reset_code(email):
    """
    Returns {"status": "ok", "code", "name"} when a code was made,
    {"status": "no_account"} or {"status": "too_soon"} otherwise.
    The route never tells the browser which of these happened, so the
    form can't be used to find out which emails have accounts.
    """
    user = find_user_by_email(email)
    if not user:
        return {"status": "no_account"}

    now = datetime.utcnow()
    last = user.get("reset_requested_at")
    if last and (now - last).total_seconds() < RESET_RESEND_SECONDS:
        return {"status": "too_soon"}

    code = f"{secrets.randbelow(1000000):06d}"
    users_collection.update_one(
        {"_id": user["_id"]},
        {"$set": {
            "reset_code_hash": bcrypt.hashpw(code.encode("utf-8"), bcrypt.gensalt()),
            "reset_expires_at": now + timedelta(minutes=RESET_CODE_MINUTES),
            "reset_attempts": 0,
            "reset_requested_at": now,
        }}
    )
    return {"status": "ok", "code": code, "name": user.get("name")}


def reset_password_with_code(email, code, new_password):
    if not new_password or len(new_password) < MIN_PASSWORD_LENGTH:
        return {"success": False,
                "message": f"New password must be at least {MIN_PASSWORD_LENGTH} characters"}

    user = find_user_by_email(email)
    invalid = {"success": False, "message": "Invalid or expired code. Request a new one."}

    if not user or not user.get("reset_code_hash"):
        return invalid

    if datetime.utcnow() > user.get("reset_expires_at", datetime.min):
        return invalid

    if user.get("reset_attempts", 0) >= RESET_MAX_ATTEMPTS:
        return {"success": False,
                "message": "Too many wrong codes. Request a new one."}

    if not check_password(str(code).strip(), user["reset_code_hash"]):
        users_collection.update_one({"_id": user["_id"]}, {"$inc": {"reset_attempts": 1}})
        left = RESET_MAX_ATTEMPTS - user.get("reset_attempts", 0) - 1
        return {"success": False,
                "message": f"Wrong code. {left} attempt(s) left." if left > 0
                           else "Too many wrong codes. Request a new one."}

    users_collection.update_one(
        {"_id": user["_id"]},
        {"$set": {"password_hash": bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt())},
         "$unset": {"reset_code_hash": "", "reset_expires_at": "",
                    "reset_attempts": "", "reset_requested_at": ""}}
    )
    return {"success": True, "message": "Password changed. You can log in now."}
