"""
WEAR HISTORY + LIKE/DISLIKE for outfit recommendations.

Two small collections, both scoped to the logged-in user:

  wear_log         one document per "I wore this" click
                   {user_email, item_ids, outfit_key, occasion, worn_at}
  outfit_feedback  one document per rated outfit
                   {user_email, outfit_key, value: "like"|"dislike", updated_at}

outfit_recommendation.recommend_outfits() reads both: recently worn
pieces are ranked lower (so suggestions rotate), liked combinations
are ranked higher, and disliked ones are never suggested again.

An outfit_key is the sorted _ids of the outfit's main garments
(see outfit_builder.outfit_key), so the same shirt + jeans is the same
outfit whichever accessories were shown with it.
"""
from datetime import datetime, timedelta

from bson.objectid import ObjectId

from backend.db import db

wear_log_collection = db["wear_log"]
feedback_collection = db["outfit_feedback"]
wardrobe_collection = db["wardrobe"]

HISTORY_DAYS = 30
VALID_FEEDBACK = {"like", "dislike"}


def owned_item_ids(user_email, item_ids):
    """Only the ids that really belong to this user's wardrobe."""
    object_ids = []
    for value in item_ids or []:
        try:
            object_ids.append(ObjectId(str(value)))
        except Exception:
            continue
    if not object_ids:
        return []
    found = wardrobe_collection.find(
        {"_id": {"$in": object_ids}, "user_email": user_email}, {"_id": 1}
    )
    return sorted(str(doc["_id"]) for doc in found)


def make_outfit_key(item_ids):
    return "|".join(sorted(str(value) for value in item_ids))


def log_wear(user_email, item_ids, occasion=None):
    owned = owned_item_ids(user_email, item_ids)
    if not owned:
        return None
    entry = {
        "user_email": user_email,
        "item_ids": owned,
        "outfit_key": make_outfit_key(owned),
        "occasion": occasion,
        "worn_at": datetime.utcnow(),
    }
    wear_log_collection.insert_one(entry)
    return entry


def get_wear_history(user_email, days=HISTORY_DAYS):
    since = datetime.utcnow() - timedelta(days=days)
    entries = wear_log_collection.find(
        {"user_email": user_email, "worn_at": {"$gte": since}},
        {"_id": 0, "item_ids": 1, "outfit_key": 1, "occasion": 1, "worn_at": 1},
    ).sort("worn_at", -1)
    return list(entries)


def set_feedback(user_email, item_ids, value):
    """value: "like", "dislike", or None to clear. Returns the outfit_key."""
    owned = owned_item_ids(user_email, item_ids)
    if not owned:
        return None
    key = make_outfit_key(owned)
    if value is None:
        feedback_collection.delete_one({"user_email": user_email, "outfit_key": key})
    else:
        feedback_collection.update_one(
            {"user_email": user_email, "outfit_key": key},
            {"$set": {"value": value, "updated_at": datetime.utcnow()}},
            upsert=True,
        )
    return key


def get_feedback(user_email):
    return {
        doc["outfit_key"]: doc["value"]
        for doc in feedback_collection.find({"user_email": user_email})
        if doc.get("value") in VALID_FEEDBACK
    }


def delete_all_for_user(user_email):
    wear_log_collection.delete_many({"user_email": user_email})
    feedback_collection.delete_many({"user_email": user_email})
