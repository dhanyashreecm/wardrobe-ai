"""
OUTFIT CALENDAR - built on the existing wear_log collection, so the
recommendation engine's "worn recently" logic keeps working with every
entry logged here (and every "I wore this" click shows in the calendar).

Entries logged from the calendar can be back-dated (you forgot to log
yesterday). Each stores:
    worn_on   "YYYY-MM-DD" in the user's local (India) day
    worn_at   that day at local noon, in UTC - what the engine reads
Old "I wore this" entries have no worn_on; it's derived from worn_at.
"""
from datetime import date, datetime, timedelta

from bson.objectid import ObjectId

from backend import config
from backend.outfit_feedback import make_outfit_key, owned_item_ids, wear_log_collection

MAX_BACKDATE_DAYS = 400
REPEAT_WARN_DAYS = 14


def _offset():
    return timedelta(hours=float(getattr(config, "TRYON_RESET_OFFSET_HOURS", 5.5) or 5.5))


def local_today(now=None):
    return ((now or datetime.utcnow()) + _offset()).date()


def _local_day(entry):
    if entry.get("worn_on"):
        return entry["worn_on"]
    worn_at = entry.get("worn_at")
    return (worn_at + _offset()).date().isoformat() if worn_at else None


def parse_day(value, now=None):
    today = local_today(now)
    if not value:
        return today, None
    try:
        day = date.fromisoformat(str(value)[:10])
    except ValueError:
        return None, "Use a date like 2026-10-08."
    if day > today:
        return None, "You can't log an outfit for a future date."
    if (today - day).days > MAX_BACKDATE_DAYS:
        return None, "That date is too far back."
    return day, None


def log(user_email, item_ids, day=None, occasion=None, name=None, source="calendar", now=None):
    owned = owned_item_ids(user_email, item_ids)
    if not owned:
        return None, "None of these pieces are in your wardrobe."
    when, error = parse_day(day, now)
    if error:
        return None, error
    key = make_outfit_key(owned)
    noon_utc = datetime(when.year, when.month, when.day, 12) - _offset()
    warning = None
    previous = wear_log_collection.find_one(
        {"user_email": user_email, "outfit_key": key,
         "worn_at": {"$gte": noon_utc - timedelta(days=REPEAT_WARN_DAYS),
                     "$lte": noon_utc + timedelta(days=REPEAT_WARN_DAYS)}})
    if previous:
        gap = abs((when - date.fromisoformat(_local_day(previous))).days)
        warning = ("You logged this exact outfit on the same day already." if gap == 0 else
                   f"Heads up: you wore this exact outfit {gap} day{'s' if gap != 1 else ''} apart.")
    entry = {
        "user_email": user_email, "item_ids": owned, "outfit_key": key,
        "occasion": (occasion or None), "worn_at": noon_utc, "worn_on": when.isoformat(),
        "name": (str(name)[:60] if name else None), "source": source,
    }
    result = wear_log_collection.insert_one(entry)
    entry["_id"] = result.inserted_id
    return entry, warning


def month(user_email, year, month_no, wardrobe_items):
    start = datetime(year, month_no, 1) - _offset() - timedelta(days=1)
    end = (datetime(year + (month_no == 12), month_no % 12 + 1, 1)) - _offset() + timedelta(days=1)
    by_id = {str(i.get("_id")): i for i in wardrobe_items}
    prefix = f"{year:04d}-{month_no:02d}-"
    out = []
    for doc in wear_log_collection.find(
            {"user_email": user_email, "worn_at": {"$gte": start, "$lt": end}}).sort("worn_at", 1):
        day = _local_day(doc)
        if not day or not day.startswith(prefix):
            continue
        out.append({
            "id": str(doc["_id"]), "date": day, "occasion": doc.get("occasion"),
            "name": doc.get("name"), "source": doc.get("source") or "worn_button",
            "pieces": [{"_id": i, "category": by_id[i].get("category"), "color": by_id[i].get("color"),
                        "image_path": by_id[i].get("image_path")}
                       for i in doc.get("item_ids", []) if i in by_id],
            "removed_pieces": sum(1 for i in doc.get("item_ids", []) if i not in by_id),
        })
    return out


def delete(user_email, entry_id):
    try:
        oid = ObjectId(str(entry_id))
    except Exception:
        return False
    return wear_log_collection.delete_one({"_id": oid, "user_email": user_email}).deleted_count == 1


def last_worn(user_email, now=None):
    """{item_id: {"date": "YYYY-MM-DD", "days_ago": n}} over the whole log."""
    today = local_today(now)
    latest = {}
    for doc in wear_log_collection.find({"user_email": user_email},
                                        {"item_ids": 1, "worn_at": 1, "worn_on": 1}):
        day = _local_day(doc)
        if not day:
            continue
        for item_id in doc.get("item_ids", []):
            if item_id not in latest or day > latest[item_id]:
                latest[item_id] = day
    return {item_id: {"date": day, "days_ago": (today - date.fromisoformat(day)).days}
            for item_id, day in latest.items()}
