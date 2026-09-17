import bcrypt
from datetime import datetime
from backend.db import users_collection

# The only two accepted values, anywhere gender is written. Kept as
# a single source of truth so register/migrate can't drift apart on
# what's valid.
VALID_GENDERS = {"Male", "Female"}


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

    existing = users_collection.find_one({"email": email})
    if existing:
        return {"success": False, "message": "Email already registered"}

    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())

    user = {
        "name": name,
        "email": email,
        "password_hash": hashed,
        "gender": gender,
        "created_at": datetime.utcnow()
    }

    users_collection.insert_one(user)
    return {"success": True, "message": "Registration successful"}


def verify_login(email, password):
    user = users_collection.find_one({"email": email})
    if not user:
        return {"success": False, "message": "No account with this email"}

    if bcrypt.checkpw(password.encode("utf-8"), user["password_hash"]):
        return {
            "success": True,
            "name": user["name"],
            "email": user["email"],
            # None here means a pre-existing account created before
            # gender became mandatory. The frontend treats a missing
            # gender as "needs one-time setup" (see Login.js) rather
            # than ever silently assigning one.
            "gender": user.get("gender")
        }
    else:
        return {"success": False, "message": "Incorrect password"}


def get_user_gender(email):
    """
    Looks up just the stored gender for a user, if any. Used by
    app.py to gender-guard AI auto-detection, similar search, and
    recommendations.
    """

    user = users_collection.find_one({"email": email})
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

    user = users_collection.find_one({"email": email})

    if not user:
        return {"success": False, "message": "No account with this email"}

    if user.get("gender"):
        return {
            "success": False,
            "message": "Your account's gender is already set and can't be changed."
        }

    users_collection.update_one(
        {"email": email},
        {"$set": {"gender": gender}}
    )

    return {"success": True, "gender": gender}
