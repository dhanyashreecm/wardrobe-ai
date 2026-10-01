"""
The shopping wishlist - products a user saved from "Shop this look".

One small document per saved product, owned by the account's
normalised email exactly like wardrobe items and trips. Only what is
needed to show the card again and open the shop is kept: no copies of
descriptions or images, just the product's own image URL. Prices go
stale, so the saved price is labelled with the date it was seen.

Every function takes the owner's email from the caller's login token
(see shopping_routes.py) - a user can only ever read or change their
own list.
"""

from datetime import datetime

from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from backend.db import db
from backend.identity import normalize_email
from backend.shopping.retailers import is_safe_product_url, retailer_name

wishlist_collection = db["wishlist"]

MAX_ITEMS = 300


def _clean_text(value, limit):
    return " ".join(str(value or "").split())[:limit]


def _public(doc):
    saved = doc.get("saved_at")
    return {
        "id": str(doc["_id"]),
        "title": doc.get("title", ""),
        "url": doc.get("url", ""),
        "image": doc.get("image", ""),
        "platform": doc.get("platform", ""),
        "price": doc.get("price"),
        "price_text": doc.get("price_text"),
        "currency": doc.get("currency"),
        "saved_at": saved.isoformat() + "Z" if isinstance(saved, datetime) else None,
    }


def list_items(user_email):
    owner = normalize_email(user_email)
    docs = wishlist_collection.find({"user_email": owner})
    items = sorted(docs, key=lambda d: d.get("saved_at") or datetime.min, reverse=True)
    return [_public(d) for d in items]


def add_item(user_email, product):
    """Returns (item, error). Saving the same product twice is a no-op."""
    owner = normalize_email(user_email)
    product = product if isinstance(product, dict) else {}

    url = str(product.get("url") or "").strip()
    title = _clean_text(product.get("title"), 300)
    if not title or not is_safe_product_url(url) or len(url) > 2000:
        return None, "That product can't be saved (missing title or link)."

    image = str(product.get("image") or "").strip()
    if not is_safe_product_url(image) or len(image) > 2000:
        image = ""

    price = product.get("price")
    price = float(price) if isinstance(price, (int, float)) and price >= 0 else None

    existing = wishlist_collection.find_one({"user_email": owner, "url": url})
    if existing:
        return _public(existing), None

    if wishlist_collection.count_documents({"user_email": owner}) >= MAX_ITEMS:
        return None, f"Your wishlist is full ({MAX_ITEMS} items). Remove some first."

    doc = {
        "user_email": owner,
        "url": url,
        "title": title,
        "image": image,
        "platform": _clean_text(product.get("platform") or retailer_name(url) or "", 60),
        "price": price,
        "price_text": _clean_text(product.get("price_text"), 40) or None,
        "currency": _clean_text(product.get("currency"), 8) or None,
        "saved_at": datetime.utcnow(),
    }
    try:
        result = wishlist_collection.insert_one(doc)
    except DuplicateKeyError:
        return _public(wishlist_collection.find_one({"user_email": owner, "url": url})), None
    doc["_id"] = result.inserted_id
    return _public(doc), None


def remove_item(user_email, item_id):
    owner = normalize_email(user_email)
    try:
        oid = ObjectId(str(item_id))
    except Exception:  # noqa: BLE001 - any malformed id is simply "not found"
        return False
    # Owner is part of the filter: another user's id deletes nothing.
    result = wishlist_collection.delete_one({"_id": oid, "user_email": owner})
    return result.deleted_count > 0


def delete_all_for_user(user_email):
    wishlist_collection.delete_many({"user_email": normalize_email(user_email)})
