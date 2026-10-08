"""
My Saved Outfits - one document per saved look, per account.

Only ids that belong to the signed-in user's wardrobe are stored, and
the image URLs are read from the database - never trusted from the
browser - so a saved look can't point at someone else's clothes or at
an external (inspiration) image.
"""
from datetime import datetime

from bson.objectid import ObjectId

from backend.db import db

saved_collection = db["saved_looks"]
wardrobe_collection = db["wardrobe"]
MAX_SAVED = 200


def _owned_items(user_email, item_ids):
    object_ids = []
    for value in item_ids or []:
        try:
            object_ids.append(ObjectId(str(value)))
        except Exception:
            continue
    if not object_ids:
        return []
    return list(wardrobe_collection.find({"_id": {"$in": object_ids}, "user_email": user_email}))


def _clean_text(value, limit):
    return str(value or "").strip()[:limit]


def save(user_email, gender, payload):
    items = _owned_items(user_email, payload.get("item_ids"))
    if not items:
        return None, "None of these pieces are in your wardrobe."
    if saved_collection.count_documents({"user_email": user_email}) >= MAX_SAVED:
        return None, f"You can keep up to {MAX_SAVED} saved outfits - delete one first."
    doc = {
        "user_email": user_email,
        "gender": gender,
        "name": _clean_text(payload.get("name"), 60) or "My Outfit",
        "occasion": _clean_text(payload.get("occasion"), 40),
        "item_ids": [str(i["_id"]) for i in items],
        "image_urls": [i.get("image_path") for i in items],
        "style_tags": [_clean_text(t, 30) for t in (payload.get("style_tags") or [])][:6],
        "style_label": _clean_text(payload.get("style_label"), 40),
        "trend_id": _clean_text(payload.get("trend_id"), 60) or None,
        "trend_name": _clean_text(payload.get("trend_name"), 60) or None,
        "explanation": [_clean_text(t, 300) for t in (payload.get("why") or [])][:4],
        "styling_notes": _clean_text(payload.get("styling_tip"), 300),
        "created_at": datetime.utcnow(),
    }
    result = saved_collection.insert_one(doc)
    return str(result.inserted_id), None


def list_for(user_email, wardrobe_items):
    by_id = {str(i.get("_id")): i for i in wardrobe_items}
    out = []
    for doc in saved_collection.find({"user_email": user_email}).sort("created_at", -1):
        pieces = []
        missing = 0
        for item_id in doc.get("item_ids", []):
            item = by_id.get(item_id)
            if item:
                pieces.append({"_id": item_id, "category": item.get("category"), "color": item.get("color"),
                               "display_name": item.get("display_name") or item.get("category"),
                               "image_path": item.get("image_path")})
            else:
                missing += 1
        out.append({
            "id": str(doc["_id"]), "name": doc.get("name"), "occasion": doc.get("occasion"),
            "style_label": doc.get("style_label"), "style_tags": doc.get("style_tags", []),
            "trend_name": doc.get("trend_name"), "why": doc.get("explanation", []),
            "styling_tip": doc.get("styling_notes"), "pieces": pieces,
            "item_ids": [p["_id"] for p in pieces],
            "missing_pieces": missing,
            "created_at": doc["created_at"].isoformat() + "Z" if doc.get("created_at") else None,
        })
    return out


def delete(user_email, saved_id):
    try:
        oid = ObjectId(str(saved_id))
    except Exception:
        return False
    return saved_collection.delete_one({"_id": oid, "user_email": user_email}).deleted_count == 1


def delete_all_for_user(user_email):
    saved_collection.delete_many({"user_email": user_email})
