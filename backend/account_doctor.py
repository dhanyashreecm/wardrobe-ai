"""
ACCOUNT DOCTOR - checks (and, only when asked, safely repairs) how an
account is stored in the shared Atlas database.

    python -m backend.account_doctor --email you@gmail.com
    python -m backend.account_doctor --all
    python -m backend.account_doctor --all --fix

What it reports, per account (never a password, hash or secret):
  * how many account records match the email ignoring case (must be 1)
  * whether the stored email is already normalised (trimmed, lower-case)
  * whether the stored password hash is a valid bcrypt hash - i.e.
    whether a correct password CAN log in - without revealing it
  * wardrobe items / trips owned, and how many are filed under a
    differently-cased copy of the email (these are invisible to the
    account in the app)
  * how many wardrobe images are https cloud URLs vs local paths

--fix does ONLY this, and only where it is unambiguous:
  * lower-cases/trims the stored email of an account, if no OTHER
    account already uses that normalised email;
  * re-files wardrobe items, trips and outfit history stored under a
    differently-cased email onto the account's normalised email;
  * creates the uniqueness indexes (db.ensure_indexes).
It never deletes anything, never merges two accounts and never changes
a password. Two accounts that differ only by case are reported for a
human decision instead.
"""

import argparse
import sys
from collections import defaultdict

from backend import config
from backend.identity import normalize_email, email_match_filter


OWNED = ("wardrobe", "trips", "outfit_feedback", "wear_log")


def hash_state(stored):
    from backend.auth import _hash_bytes
    if stored is None:
        return "MISSING"
    kind = type(stored).__name__
    return f"valid bcrypt ({kind})" if _hash_bytes(stored) else f"INVALID ({kind})"


def describe(db, email):
    canonical = normalize_email(email)
    accounts = list(db["users"].find(email_match_filter(canonical)))
    print(f"\n== {canonical}")
    print(f"   account records (any case) : {len(accounts)}")
    for user in accounts:
        stored = user.get("email")
        print(f"   - id {user['_id']}: stored email "
              f"{'normalised' if stored == canonical else 'NOT normalised'}, "
              f"password hash {hash_state(user.get('password_hash'))}, "
              f"gender {'set' if user.get('gender') else 'not set'}")

    for name in OWNED:
        exact = db[name].count_documents({"user_email": canonical})
        any_case = db[name].count_documents(email_match_filter(canonical, "user_email"))
        line = f"   {name:<15}: {exact}"
        if any_case != exact:
            line += f"  (+{any_case - exact} filed under a different capitalisation)"
        print(line)

    items = list(db["wardrobe"].find(email_match_filter(canonical, "user_email"), {"image_path": 1, "category": 1}))
    https = sum(1 for i in items if str(i.get("image_path", "")).startswith("https://"))
    print(f"   images: {https} cloud (https), {len(items) - https} local/other; "
          f"{sum(1 for i in items if not i.get('category'))} without category")
    return accounts


def fix(db):
    changed = 0
    groups = defaultdict(list)
    for user in db["users"].find({}, {"email": 1}):
        groups[normalize_email(user.get("email"))].append(user)

    for canonical, users in groups.items():
        if not canonical:
            continue
        if len(users) > 1:
            print(f"  NEEDS A DECISION: {len(users)} accounts share {canonical} "
                  f"(ids {', '.join(str(u['_id']) for u in users)}) - not merged automatically.")
            continue
        user = users[0]
        if user.get("email") != canonical:
            db["users"].update_one({"_id": user["_id"]}, {"$set": {"email": canonical}})
            print(f"  normalised stored email of account {user['_id']}")
            changed += 1
        for name in OWNED:
            result = db[name].update_many(
                {"$and": [email_match_filter(canonical, "user_email"), {"user_email": {"$ne": canonical}}]},
                {"$set": {"user_email": canonical}},
            )
            if result.modified_count:
                print(f"  re-filed {result.modified_count} {name} record(s) onto {canonical}")
                changed += result.modified_count

    from backend.db import ensure_indexes
    problems = ensure_indexes()
    for problem in problems:
        print(f"  index not in place: {problem}")
    if not problems:
        print("  uniqueness indexes: in place")
    return changed, problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--fix", action="store_true")
    args = parser.parse_args(argv)

    config.validate(strict=True)
    from backend.db import db, ping

    ok, detail = ping()
    if not ok:
        print(f"Cannot reach the shared database: {detail}")
        return 1
    print(f"Database: {config.MONGODB_DB_NAME} at {config.safe_mongo_host()}")

    if args.fix:
        print("\nRepairing (no deletions, no password changes):")
        changed, problems = fix(db)
        print(f"  {changed} change(s) made")

    if args.email:
        describe(db, args.email)
    elif args.all:
        emails = sorted({normalize_email(u.get("email")) for u in db["users"].find({}, {"email": 1})} - {""})
        print(f"\nAccounts: {len(emails)}")
        for email in emails:
            describe(db, email)

    return 0


if __name__ == "__main__":
    sys.exit(main())
