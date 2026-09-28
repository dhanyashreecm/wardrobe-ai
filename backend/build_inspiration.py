"""
Publishes the curated style-inspiration pictures (see
backend/inspiration.py and inspiration_images/README.md).

    python -m backend.build_inspiration --dry-run     # check the folders, change nothing
    python -m backend.build_inspiration               # upload to Cloudinary + record in Atlas
    python -m backend.build_inspiration --local-only  # this computer only (development)

For every picture in inspiration_images/<male|female>/<occasion>/:
  * it must be a real image at least MIN_SIDE pixels on its short side -
    small thumbnails are refused rather than blown up;
  * it is uploaded once to Cloudinary (ai-wardrobe/inspiration/...),
    named by a hash of its content so re-running never duplicates it;
  * it is recorded in the Atlas collection "inspiration" with its
    Cloudinary https URL, so every device sees it.
Pictures removed from the folders are removed from the Atlas list too.
The uploaded files are only pictures - no source links are stored.
"""
import argparse
import hashlib
import json
import os

from backend.inspiration import COLLECTION, MANIFEST, PROJECT_ROOT

ROOT = os.path.join(PROJECT_ROOT, "inspiration_images")
MIN_SIDE = 400
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp")
GENDERS = ("male", "female")
OCCASIONS = ("casual", "day_outing", "college", "office", "interview",
             "date", "party", "wedding", "traditional", "sports")
# friendlier folder names that mean the same occasion
FOLDER_ALIASES = {"formal": "interview", "date_night": "date", "festive": "traditional",
                  "day_out": "day_outing", "workout": "sports", "normal": "casual"}


def occasion_for_folder(name):
    name = name.strip().lower().replace("-", "_").replace(" ", "_")
    name = FOLDER_ALIASES.get(name, name)
    return name if name in OCCASIONS else None


def collect(root=ROOT):
    """(accepted entries, [(path, reason) skipped])"""
    from PIL import Image
    accepted, skipped = [], []
    for gender in GENDERS:
        gender_dir = os.path.join(root, gender)
        if not os.path.isdir(gender_dir):
            continue
        for folder in sorted(os.listdir(gender_dir)):
            path_dir = os.path.join(gender_dir, folder)
            if not os.path.isdir(path_dir):
                continue
            occasion = occasion_for_folder(folder)
            if not occasion:
                skipped.append((path_dir, "unknown occasion folder"))
                continue
            for name in sorted(os.listdir(path_dir)):
                path = os.path.join(path_dir, name)
                if not name.lower().endswith(IMAGE_EXT):
                    continue
                try:
                    with Image.open(path) as img:
                        img.verify()
                    with Image.open(path) as img:
                        width, height = img.size
                except Exception:
                    skipped.append((path, "not a readable image"))
                    continue
                if min(width, height) < MIN_SIDE:
                    skipped.append((path, f"too small ({width}x{height}); needs {MIN_SIDE}px+"))
                    continue
                with open(path, "rb") as handle:
                    digest = hashlib.sha1(handle.read()).hexdigest()[:20]
                accepted.append({
                    "id": f"{gender}-{occasion}-{digest}", "gender": gender, "occasion": occasion,
                    "caption": "", "width": width, "height": height,
                    "src": "project:" + os.path.relpath(path, PROJECT_ROOT),
                })
    return accepted, skipped


def publish(entries):
    """Upload to Cloudinary and sync the Atlas list. Returns entries with url."""
    from backend import config, storage
    from backend.db import db
    if config.storage_backend() != "cloudinary":
        raise SystemExit("Cloudinary is not configured in .env - cannot publish for other devices. "
                         "Use --local-only for this computer only.")
    uploader = storage._ensure_cloudinary()
    for entry in entries:
        path = os.path.join(PROJECT_ROOT, entry["src"][len("project:"):])
        result = uploader.upload(
            path, folder=f"ai-wardrobe/inspiration/{entry['gender']}/{entry['occasion']}",
            public_id=entry["id"], overwrite=False, resource_type="image")
        url = result["secure_url"]
        # delivered resized and in a modern format, from the full-size original
        entry["url"] = url.replace("/upload/", "/upload/c_limit,w_720,f_auto,q_auto/", 1)
        db[COLLECTION].update_one(
            {"_id": entry["id"]},
            {"$set": {k: entry[k] for k in ("gender", "occasion", "url", "caption", "width", "height")}},
            upsert=True)
        print("published", entry["gender"], entry["occasion"], entry["id"])
    keep = [e["id"] for e in entries]
    removed = db[COLLECTION].delete_many({"_id": {"$nin": keep}}).deleted_count
    if removed:
        print(f"removed {removed} picture(s) no longer in inspiration_images/")
    return entries


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--local-only", action="store_true")
    args = parser.parse_args()

    entries, skipped = collect()
    for path, reason in skipped:
        print(f"SKIPPED {os.path.relpath(path, PROJECT_ROOT)}: {reason}")
    counts = {}
    for e in entries:
        counts[(e["gender"], e["occasion"])] = counts.get((e["gender"], e["occasion"]), 0) + 1
    for gender in GENDERS:
        for occasion in OCCASIONS:
            print(f"{gender:6} {occasion:12} {counts.get((gender, occasion), 0)} picture(s)")
    if args.dry_run:
        print("Dry run - nothing uploaded or written.")
        return
    if not args.local_only:
        entries = publish(entries)
    else:
        for e in entries:
            e["url"] = e["src"]
    os.makedirs(os.path.dirname(MANIFEST), exist_ok=True)
    with open(MANIFEST, "w", encoding="utf-8") as handle:
        json.dump({"images": [{k: v for k, v in e.items() if k != "src" or args.local_only}
                              for e in entries]}, handle, indent=1)
    print(f"{len(entries)} picture(s). Wrote {os.path.relpath(MANIFEST, PROJECT_ROOT)}"
          + ("" if args.local_only else " and the Atlas 'inspiration' list."))


if __name__ == "__main__":
    main()
