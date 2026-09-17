from backend.db import db
from datetime import datetime
from bson.objectid import ObjectId

wardrobe_collection = db["wardrobe"]

def add_item(user_email, category, color, image_path, occasion="", material=None):
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

    result = wardrobe_collection.insert_one(item)
    return str(result.inserted_id)

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
    allowed_fields = {"category", "color", "occasion", "material", "favorite"}

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
