from backend.db import db
from datetime import datetime
from bson.objectid import ObjectId

wardrobe_collection = db["wardrobe"]

def add_item(user_email, category, color, image_path, occasion="casual"):
    item = {
        "user_email": user_email,
        "category": category,
        "color": color,
        "image_path": image_path,
        "occasion": occasion,
        "created_at": datetime.utcnow()
    }
    result = wardrobe_collection.insert_one(item)
    return str(result.inserted_id)

def get_user_wardrobe(user_email):
    items = list(wardrobe_collection.find({"user_email": user_email}))
    for item in items:
        item["_id"] = str(item["_id"])
    return items

def delete_item(item_id):
    wardrobe_collection.delete_one({"_id": ObjectId(item_id)})
