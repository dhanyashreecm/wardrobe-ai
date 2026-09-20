from backend.db import db
from datetime import datetime
from bson.objectid import ObjectId

wardrobe_collection = db["wardrobe"]

def add_item(user_email, category, color, image_path, occasion="", material=None, styling=None):
    # occasion is now an OPTIONAL manual override, not a required
    # field - "" (the default) means "fully automatic": which
    # occasions this item is eligible for gets worked out from its
    # category alone (see backend.outfit_recommendation.
    # effective_occasions). A non-empty value here only ever ADDS an
    # occasion on top of that, it never restricts it - see the same
    # module for why.
    item = {
        "user_email": user_email,
        "category": category,
        "color": color,
        "image_path": image_path,
        "occasion": occasion,
        "favorite": False,
        "created_at": datetime.utcnow()
    }

    if material:
        item["material"] = material

    # Optional manual "styling" tag - "Casual" or "Wedding/Festive" -
    # offered only for Saree/Lehenga/Kurta-type items (see Wardrobe.js
    # STYLING_CATEGORIES). This is what lets a user tell the app "this
    # exact saree is a casual one" vs "this one is for weddings" - a
    # distinction the AI model can never make on its own, since it
    # only ever outputs the garment type ("saree"), not how formal a
    # specific one is. Read by backend.style_compatibility.
    # resolve_style() when scoring outfits.
    if styling:
        item["styling"] = styling

    result = wardrobe_collection.insert_one(item)
    return str(result.inserted_id)

def delete_all_for_user(user_email):
    """
    Deletes every wardrobe item belonging to this account. Used only
    by the "delete account" flow (see app.py's /api/user/account
    DELETE route) - a wardrobe item is only ever meaningful tied to
    the account that owns it, so once the account is gone these
    would otherwise be orphaned rows nobody can see or clean up.
    Does not touch the actual uploaded image files on disk - that's
    handled separately by removing the whole user folder (see
    get_user_folder() in app.py), since that folder holds the files
    for every item at once rather than one at a time.

    Returns how many items were deleted, purely informational.
    """
    result = wardrobe_collection.delete_many({"user_email": user_email})
    return result.deleted_count


def get_user_wardrobe(user_email):
    items = list(wardrobe_collection.find({"user_email": user_email}))
    for item in items:
        item["_id"] = str(item["_id"])
    return items

def delete_item(item_id, user_email):
    """
    Deletes a wardrobe item, but ONLY if it belongs to user_email.
    Previously this matched on _id alone, which meant any logged-in
    user could delete ANY other user's item just by guessing/
    enumerating an item_id - a real cross-user isolation gap. Mirrors
    the same ownership check update_item() already had.

    Returns True if something was actually deleted, False if the id
    didn't exist or belonged to someone else - callers should turn a
    False into a 404, not a silent 200.
    """
    try:
        object_id = ObjectId(item_id)
    except Exception:
        return False

    before = wardrobe_collection.find_one(
        {"_id": object_id, "user_email": user_email}
    )

    if not before:
        return False

    wardrobe_collection.delete_one(
        {"_id": object_id, "user_email": user_email}
    )
    return True

def update_item(item_id, user_email, updates):
    """
    Update editable fields (category, color, occasion, ...) on a
    wardrobe item. Only touches fields that were actually provided,
    and only matches items owned by user_email so one user can't
    edit another user's item.

    "occasion" is handled specially: an empty string IS a meaningful
    value for it (it clears a manual override so the item goes back
    to fully automatic, category-based occasion detection), so it's
    not treated the same as "field omitted" the way other fields are.
    """
    allowed_fields = {"category", "color", "occasion", "material", "favorite", "styling"}

    set_fields = {}

    for key, value in updates.items():
        if key not in allowed_fields:
            continue

        if key == "occasion":
            if value is None:
                continue
            set_fields[key] = value.strip() if isinstance(value, str) else value
        elif value not in (None, ""):
            set_fields[key] = value

    if not set_fields:
        return False

    result = wardrobe_collection.update_one(
        {"_id": ObjectId(item_id), "user_email": user_email},
        {"$set": set_fields}
    )

    return result.matched_count > 0