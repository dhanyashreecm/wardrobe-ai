"""
READ-ONLY breakdown of one account's cloud wardrobe: where each item
came from, and whether any look like duplicates. Changes nothing.

    python -m backend.inspect_owner_items --email you@gmail.com

Prints no secrets and no image URLs - only counts, dates, hostnames
recorded by the migration, and short item descriptions.
"""

import argparse
import glob
import json
import os
import sys
from collections import Counter, defaultdict

from backend import config
from backend.identity import normalize_email


def local_backup_ids(email):
    """Local _ids of this owner's items in THIS computer's sync_setup backups."""
    ids = set()
    for path in glob.glob("backups/local_backup_*.json"):
        try:
            with open(path) as handle:
                data = json.load(handle)
        except Exception:
            continue
        for row in data.get("wardrobe", []):
            if normalize_email(row.get("user_email")) == email:
                ids.add(str(row.get("_id")))
    return ids


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    args = parser.parse_args(argv)
    email = normalize_email(args.email)

    config.validate(strict=True)
    from backend.db import db

    items = list(db["wardrobe"].find({"user_email": email}))
    print(f"Items for {email}: {len(items)}\n")

    def day(value):
        return str(value)[:10] if value else "unknown"

    print("By origin (migration host / migration day):")
    origin = Counter()
    for item in items:
        if item.get("migrated_from_id"):
            origin[(item.get("migrated_from_host", "old script (no host recorded)"), day(item.get("migrated_at")))] += 1
        else:
            origin[("uploaded directly to the cloud app", day(item.get("created_at")))] += 1
    for (host, when), count in sorted(origin.items()):
        print(f"  {count:>3}  {host}  {when}")

    print("\nFields left by the older migration script:")
    print(f"  items with a 'local_image_path' field : {sum(1 for i in items if i.get('local_image_path'))}")
    print(f"  items with a photo fingerprint (sha256): {sum(1 for i in items if i.get('image_sha256'))}")

    mac_ids = local_backup_ids(email)
    if mac_ids:
        from_here = [i for i in items if str(i.get("migrated_from_id")) in mac_ids]
        print(f"\nItems that came from THIS computer's local copy ({len(mac_ids)} in its backup): {len(from_here)}")

    groups = defaultdict(list)
    for item in items:
        name = os.path.basename(str(item.get("local_image_path") or ""))
        key = name or f"{item.get('category')}|{item.get('color')}|{day(item.get('created_at'))}"
        groups[key].append(item)
    dupes = {k: v for k, v in groups.items() if len(v) > 1 and "|" not in k}
    print(f"\nSame original photo file migrated more than once: {len(dupes)} photo(s), "
          f"{sum(len(v) - 1 for v in dupes.values())} extra item(s)")
    for name, rows in list(dupes.items())[:15]:
        print(f"  {len(rows)}x  {name[:50]}  ({rows[0].get('category')}, {rows[0].get('color')})")

    by_cat = Counter(str(i.get("category")) for i in items)
    print("\nBy category: " + ", ".join(f"{c} {n}" for c, n in by_cat.most_common()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
