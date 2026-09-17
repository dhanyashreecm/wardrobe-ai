from backend.db import db
from datetime import datetime
from bson.objectid import ObjectId

wardrobe_collection = db["wardrobe"]

def add_item(user_email, category, color, image_path, occasion="casual", material=None):
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

def delete_item(item_id):
    wardrobe_collection.delete_one({"_id": ObjectId(item_id)})

def update_item(item_id, user_email, updates):
    """
    Update editable fields (category, color, occasion) on a wardrobe item.
    Only touches fields that were actually provided, and only matches items
    owned by user_email so one user can't edit another user's item.
    """
    allowed_fields = {"category", "color", "occasion", "material", "favorite"}

    set_fields = {
        key: value
        for key, value in updates.items()
        if key in allowed_fields and value not in (None, "")
    }

    if not set_fields:
        return False

    result = wardrobe_collection.update_one(
        {"_id": ObjectId(item_id), "user_email": user_email},
        {"$set": set_fields}
    )

    return result.matched_count > 0
