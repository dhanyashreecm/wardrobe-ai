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
    user = users_collection.find_one({"email": email})

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
    }


def update_user_profile(email, name=None, phone=None):
    """
    Updates ONLY "name" and "phone" - the two fields that are
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

    if not set_fields:
        return {"success": False, "message": "Nothing to update"}

    users_collection.update_one({"email": email}, {"$set": set_fields})

    return {"success": True}


def set_profile_picture(email, picture_url):
    """
    Records the URL of a just-uploaded profile picture (see
    app.py's /api/user/profile/picture route, which does the actual
    file handling - this just points the account at the result).
    """
    users_collection.update_one(
        {"email": email}, {"$set": {"profile_picture": picture_url}}
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
    result = users_collection.delete_one({"email": email})
    return result.deleted_count > 0


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