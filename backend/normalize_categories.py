"""
Checks every stored wardrobe item against the gender-specific
category catalogue (backend/category_catalog.py).

Safe by default - it only REPORTS:

    python -m backend.normalize_categories            # report only
    python -m backend.normalize_categories --apply    # write the safe fixes

With --apply, and only for items whose category is valid for the
owner's saved gender:
  * adds item["gender"] (the owner's gender) if missing
  * renames a legacy name to its catalogue name ("Denims" -> "Jeans")

Items that are NOT valid for the owner's gender (e.g. a "Saree" in a
men's account) or have an unknown category are never changed or
deleted: they are marked needs_review=True so the Wardrobe page can ask
the owner, and recommendations already skip them. Images, users and
accounts are never touched.
"""
import argparse
from collections import Counter

from backend import category_catalog as cc
from backend.db import db, users_collection


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    genders = {
        (u.get("email") or "").lower(): cc.normalize_gender(u.get("gender"))
        for u in users_collection.find({}, {"email": 1, "gender": 1})
    }
    wardrobe = db["wardrobe"]
    stats = Counter()
    for item in wardrobe.find({}, {"user_email": 1, "category": 1, "gender": 1}):
        owner_gender = genders.get((item.get("user_email") or "").lower())
        category = item.get("category") or ""
        update = {}
        if not owner_gender:
            stats["owner has no gender"] += 1
            continue
        if cc.is_valid_for(category, owner_gender):
            stats["valid"] += 1
            if item.get("gender") != owner_gender:
                update["gender"] = owner_gender
            new_name = cc.canonical_for_gender(category, owner_gender)
            if new_name and new_name != category:
                update["category"] = new_name
                stats[f"rename {category} -> {new_name}"] += 1
        else:
            reason = "unknown category" if not cc.known(category) else "other gender's category"
            stats[f"needs review ({reason}): {category}"] += 1
            update["needs_review"] = True
        if update and args.apply:
            wardrobe.update_one({"_id": item["_id"]}, {"$set": update})
    for line, count in sorted(stats.items()):
        print(f"{count:5}  {line}")
    print("Applied." if args.apply else "Report only - run with --apply to write the safe fixes.")


if __name__ == "__main__":
    main()
