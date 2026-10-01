"""
API for "Shop this look" and the wishlist. Every route needs a login
token, and the owner always comes from that token - never from the
request - so nobody can read or change another user's wishlist.

    POST   /api/shop/search      photo + detected attributes -> products + shop links
    GET    /api/shop/status      is product search configured on this server?
    GET    /api/wishlist         the caller's saved products
    POST   /api/wishlist         save one product
    DELETE /api/wishlist/<id>    remove one of the caller's saved products

The wardrobe half of Find Similar stays where it was
(POST /api/ai/similar in app.py), which now also returns the photo's
attributes so this search doesn't analyse the photo again.

Kept separate from app.py so it can be tested without TensorFlow.
"""

import json
import threading
import time
from collections import defaultdict, deque

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from backend import config
from backend.identity import normalize_email
from backend.shopping import service
from backend.shopping.analysis import clean_client_analysis

shopping_blueprint = Blueprint("shopping_routes", __name__)

MAX_IMAGE_BYTES = 10 * 1024 * 1024

# Each search can spend from a small monthly allowance, so one account
# gets at most this many shop searches per hour (cached repeats of the
# same photo don't reach Google and are cheap, but still count here).
SEARCHES_PER_HOUR = 30
_search_hits = defaultdict(deque)
_search_lock = threading.Lock()


def reset_limits():
    with _search_lock:
        _search_hits.clear()


def _over_limit(owner):
    now = time.monotonic()
    with _search_lock:
        bucket = _search_hits[owner]
        while bucket and now - bucket[0] > 3600:
            bucket.popleft()
        if len(bucket) >= SEARCHES_PER_HOUR:
            return True
        bucket.append(now)
    return False


def _owner():
    return normalize_email(get_jwt_identity())


def _read_image():
    """(bytes, error message)"""
    file = request.files.get("image")
    if not file:
        return None, "Please choose a photo first."
    data = file.read(MAX_IMAGE_BYTES + 1)
    if not data:
        return None, "That photo is empty."
    if len(data) > MAX_IMAGE_BYTES:
        return None, "That photo is too large (10 MB maximum)."
    try:
        import io
        from PIL import Image
        with Image.open(io.BytesIO(data)) as img:
            img.verify()
    except Exception:  # noqa: BLE001
        return None, "That file isn't a photo we can read (use JPG, PNG or WebP)."
    return data, None


@shopping_blueprint.route("/api/shop/status", methods=["GET"])
@jwt_required()
def shop_status():
    return jsonify({
        "success": True,
        "product_search": config.shopping_api_configured(),
        "country": config.SHOP_COUNTRY,
    }), 200


@shopping_blueprint.route("/api/shop/search", methods=["POST"])
@jwt_required()
def shop_search():
    owner = _owner()
    if _over_limit(owner):
        return jsonify({"success": False, "code": "rate_limited",
                        "message": "You've run a lot of shop searches this hour - "
                                   "please try again a little later."}), 429

    image_bytes, problem = _read_image()
    if problem:
        return jsonify({"success": False, "message": problem}), 400

    try:
        raw_analysis = json.loads(request.form.get("analysis") or "{}")
    except ValueError:
        raw_analysis = {}
    analysis = clean_client_analysis(raw_analysis)

    try:
        result = service.search(image_bytes, analysis)
    except Exception as error:  # noqa: BLE001 - always answer with links, never a 500
        print(f"Shop search failed: {type(error).__name__}")
        from backend.shopping.analysis import build_query
        from backend.shopping.retailers import search_links
        query = build_query(analysis)
        result = {
            "query": query, "analysis": analysis, "products": [],
            "links": search_links(query), "status": "provider_error",
            "message": "Online product search hit a problem. Here are searches "
                       "for this look on each shop instead.",
        }

    return jsonify({"success": True, **result}), 200


# =========================================================
# WISHLIST
# =========================================================

@shopping_blueprint.route("/api/wishlist", methods=["GET"])
@jwt_required()
def get_wishlist():
    from backend import wishlist
    return jsonify({"success": True, "items": wishlist.list_items(_owner())}), 200


@shopping_blueprint.route("/api/wishlist", methods=["POST"])
@jwt_required()
def save_to_wishlist():
    from backend import wishlist
    item, error = wishlist.add_item(_owner(), request.get_json(silent=True))
    if error:
        return jsonify({"success": False, "message": error}), 400
    return jsonify({"success": True, "item": item}), 200


@shopping_blueprint.route("/api/wishlist/<item_id>", methods=["DELETE"])
@jwt_required()
def remove_from_wishlist(item_id):
    from backend import wishlist
    if not wishlist.remove_item(_owner(), item_id):
        return jsonify({"success": False, "message": "Not found in your wishlist."}), 404
    return jsonify({"success": True}), 200
