"""
API for Style & Trends (Outfit Studio) and the Outfit Calendar.
Every route needs a JWT and touches only the signed-in user's data; the
account's SAVED gender decides everything gender-related. Plain JSON so
the future mobile app can reuse it.
"""
from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from backend import outfit_feedback
from backend.auth import get_user_gender
from backend.category_catalog import normalize_gender
from backend.identity import normalize_email
from backend.outfit_presentation import present_item
from backend.style_studio import calendar, engine, gaps, saved
from backend.wardrobe import get_user_wardrobe

style_bp = Blueprint("style", __name__)
GENDER_REQUIRED = "Set Men or Women in your Profile so your stylist knows what to suggest."


def _user():
    return normalize_email(get_jwt_identity())


def _context():
    email = _user()
    gender = normalize_gender(get_user_gender(email))
    if not gender:
        return None
    items = [present_item(i) for i in get_user_wardrobe(email)]
    try:
        history = outfit_feedback.get_wear_history(email, days=60)
        feedback = outfit_feedback.get_feedback(email)
    except Exception as error:  # noqa: BLE001
        print(f"[style] history skipped: {error}")
        history, feedback = [], {}
    return engine.Context(email, items, gender, history, feedback)


def _need_gender():
    return jsonify({"success": False, "code": "gender_required", "message": GENDER_REQUIRED}), 409


@style_bp.route("/api/style/overview", methods=["GET"])
@jwt_required()
def style_overview():
    ctx = _context()
    return (jsonify({"success": True, **engine.overview(ctx)}), 200) if ctx else _need_gender()


@style_bp.route("/api/style/outfits", methods=["POST"])
@jwt_required()
def style_outfits():
    ctx = _context()
    if not ctx:
        return _need_gender()
    d = request.get_json(silent=True) or {}
    return jsonify({"success": True, **engine.create_outfits(
        ctx, occasion=d.get("occasion") or None, colour=d.get("color") or None,
        style=d.get("style") or None, trend_id=d.get("trend_id") or None)}), 200


@style_bp.route("/api/style/ideas", methods=["GET"])
@jwt_required()
def style_ideas():
    ctx = _context()
    return (jsonify({"success": True, "ideas": engine.wardrobe_ideas(ctx)}), 200) if ctx else _need_gender()


@style_bp.route("/api/style/shopping", methods=["GET"])
@jwt_required()
def style_shopping():
    ctx = _context()
    return (jsonify({"success": True, **gaps.analyse(ctx)}), 200) if ctx else _need_gender()


@style_bp.route("/api/style/saved", methods=["GET"])
@jwt_required()
def saved_list():
    email = _user()
    items = [present_item(i) for i in get_user_wardrobe(email)]
    return jsonify({"success": True, "saved": saved.list_for(email, items)}), 200


@style_bp.route("/api/style/saved", methods=["POST"])
@jwt_required()
def saved_create():
    email = _user()
    saved_id, error = saved.save(email, normalize_gender(get_user_gender(email)),
                                 request.get_json(silent=True) or {})
    if error:
        return jsonify({"success": False, "message": error}), 400
    return jsonify({"success": True, "id": saved_id}), 201


@style_bp.route("/api/style/saved/<saved_id>", methods=["DELETE"])
@jwt_required()
def saved_delete(saved_id):
    if not saved.delete(_user(), saved_id):
        return jsonify({"success": False, "message": "Not found"}), 404
    return jsonify({"success": True}), 200


@style_bp.route("/api/calendar", methods=["GET"])
@jwt_required()
def calendar_month():
    email = _user()
    value = request.args.get("month") or calendar.local_today().strftime("%Y-%m")
    try:
        year, month_no = (int(p) for p in value.split("-")[:2])
        if not 1 <= month_no <= 12:
            raise ValueError
    except Exception:
        return jsonify({"success": False, "message": "Use month=YYYY-MM"}), 400
    entries = calendar.month(email, year, month_no, get_user_wardrobe(email))
    return jsonify({"success": True, "month": f"{year:04d}-{month_no:02d}",
                    "today": calendar.local_today().isoformat(), "entries": entries}), 200


@style_bp.route("/api/calendar", methods=["POST"])
@jwt_required()
def calendar_log():
    d = request.get_json(silent=True) or {}
    entry, note = calendar.log(_user(), d.get("item_ids"), day=d.get("date"),
                               occasion=d.get("occasion"), name=d.get("name"))
    if not entry:
        return jsonify({"success": False, "message": note}), 400
    return jsonify({"success": True, "id": str(entry["_id"]), "date": entry["worn_on"], "warning": note}), 201


@style_bp.route("/api/calendar/<entry_id>", methods=["DELETE"])
@jwt_required()
def calendar_delete(entry_id):
    if not calendar.delete(_user(), entry_id):
        return jsonify({"success": False, "message": "Not found"}), 404
    return jsonify({"success": True}), 200


@style_bp.route("/api/wardrobe/last-worn", methods=["GET"])
@jwt_required()
def wardrobe_last_worn():
    return jsonify({"success": True, "last_worn": calendar.last_worn(_user())}), 200
