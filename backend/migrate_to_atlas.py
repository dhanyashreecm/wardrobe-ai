"""
ONE-TIME MIGRATION: this computer's local database and images ->
the shared MongoDB Atlas database and Cloudinary.

Each laptop that used Wardrobe-AI before the centralisation change has
its own local "wardrobe_db" full of real accounts, wardrobe items and
trips, plus the actual image files under backend/uploads/. This script
copies all of that into the shared setup so nothing has to be typed in
again.

WHAT IT WILL NOT DO
-------------------
  * It never deletes or edits the local database. The source is opened
    read-only in practice - the only writes go to the destination.
  * It never deletes local image files.
  * It never guesses who an item belongs to. An item whose owner has
    no matching account is imported with its user_email replaced by
    LEGACY_UNASSIGNED so it is preserved but attributed to nobody, and
    every such item is listed in the summary.
  * It never overwrites an account that already exists in the shared
    database - if the same email registered on both laptops, the copy
    already in Atlas wins and the local one is reported as skipped.

SAFE TO RUN TWICE
-----------------
Re-running does not duplicate anything. Users are matched by email.
Wardrobe items and trips carry their original local _id in a
"migrated_from_id" field, which is what the script checks before
inserting - so an interrupted run can simply be run again, and only
what is genuinely missing gets copied.

USAGE (from the project root, with the virtualenv active and .env
already pointing at the shared database):

    # See exactly what WOULD happen - writes nothing, uploads nothing:
    python -m backend.migrate_to_atlas --dry-run

    # Do it:
    python -m backend.migrate_to_atlas

    # If the old data lives somewhere other than the default:
    python -m backend.migrate_to_atlas \
        --source-uri mongodb://localhost:27017/ --source-db wardrobe_db
"""

import argparse
import os
import sys

from pymongo import MongoClient

from backend import config, storage


LEGACY_UNASSIGNED = "legacy_unassigned"

DEFAULT_SOURCE_URI = "mongodb://localhost:27017/"
DEFAULT_SOURCE_DB = "wardrobe_db"


def local_path_for(image_path):
    """
    Turns a stored image reference into a real path on this disk, or
    None when there is nothing local to upload.

    Old rows hold "/api/uploads/<folder>/<file>", which maps directly
    onto backend/uploads/<folder>/<file>. A row that already holds an
    https URL has been migrated (or was uploaded after the change) and
    needs no work.
    """
    if not image_path or storage.is_remote_url(image_path):
        return None

    relative = image_path

    for prefix in ("/api/uploads/", "api/uploads/", "/uploads/", "uploads/"):
        if relative.startswith(prefix):
            relative = relative[len(prefix):]
            break

    candidate = os.path.join(storage.BASE_UPLOAD_FOLDER, relative)

    return candidate if os.path.isfile(candidate) else None


def migrate_users(source_db, destination_db, report, dry_run):

    source_users = list(source_db["users"].find({}))

    destination_users = destination_db["users"]

    for user in source_users:

        email = user.get("email")

        if not email:
            report["users_skipped_no_email"] += 1
            continue

        if destination_users.find_one({"email": email}):
            report["users_already_present"] += 1
            continue

        document = dict(user)

        # The local _id is dropped so the shared database assigns its
        # own, but it is remembered: wardrobe rows reference their
        # owner by EMAIL, not by _id, so nothing breaks - and keeping
        # it makes the migration auditable afterwards.
        document["migrated_from_id"] = str(document.pop("_id", ""))

        if not dry_run:
            destination_users.insert_one(document)

        report["users_migrated"] += 1


def migrate_collection(
    name,
    source_db,
    destination_db,
    known_emails,
    report,
    dry_run,
    upload_images,
):
    """
    Copies one owned collection ("wardrobe" or "trips"). Shared by
    both because the ownership and de-duplication rules are identical;
    only wardrobe rows carry an image, which upload_images controls.
    """

    source_rows = list(source_db[name].find({}))

    destination = destination_db[name]

    for row in source_rows:

        original_id = str(row.get("_id", ""))

        if original_id and destination.find_one({"migrated_from_id": original_id}):
            report[f"{name}_already_present"] += 1
            continue

        document = dict(row)
        document.pop("_id", None)
        document["migrated_from_id"] = original_id

        owner = document.get("user_email")

        # No guessing: an orphaned row keeps all of its data but is
        # parked under a reserved owner nobody can log in as, so it is
        # never shown to - or deletable by - the wrong person.
        if not owner or owner not in known_emails:
            document["original_user_email"] = owner or ""
            document["user_email"] = LEGACY_UNASSIGNED
            report["unassigned"].append(
                f"{name}: {original_id} (owner: {owner or 'missing'})"
            )

        if upload_images:

            source_path = local_path_for(document.get("image_path"))

            if source_path:

                if dry_run:
                    report["images_to_upload"] += 1

                else:
                    try:
                        document["local_image_path"] = document.get("image_path")

                        document["image_path"] = storage.upload_local_file(
                            source_path,
                            document.get("user_email") or LEGACY_UNASSIGNED,
                            kind="wardrobe",
                        )

                        report["images_uploaded"] += 1

                    except storage.StorageError as error:
                        # The row is still migrated - losing the
                        # metadata would be worse than an item whose
                        # picture needs re-uploading by hand later.
                        report["image_failures"].append(
                            f"{original_id}: {error}"
                        )

            elif document.get("image_path") and not storage.is_remote_url(
                document.get("image_path")
            ):
                report["images_missing_on_disk"].append(
                    f"{original_id}: {document.get('image_path')}"
                )

        if not dry_run:
            destination.insert_one(document)

        report[f"{name}_migrated"] += 1


def main():

    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument(
        "--source-uri",
        default=DEFAULT_SOURCE_URI,
        help=f"Local MongoDB to read from (default: {DEFAULT_SOURCE_URI})",
    )
    parser.add_argument(
        "--source-db",
        default=DEFAULT_SOURCE_DB,
        help=f"Local database name (default: {DEFAULT_SOURCE_DB})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be migrated without writing or uploading.",
    )
    parser.add_argument(
        "--skip-images",
        action="store_true",
        help="Migrate database rows only, leaving image paths untouched.",
    )

    args = parser.parse_args()

    # The destination comes from .env - the same configuration the app
    # itself uses - so this can never migrate into a different place
    # than the one the app will read from.
    config.validate(strict=True)

    if config.MONGODB_URI.strip().rstrip("/") == args.source_uri.strip().rstrip("/"):
        print(
            "Source and destination are the same database - nothing to "
            "migrate. Point MONGODB_URI in .env at the shared Atlas cluster "
            "first."
        )
        return 1

    upload_images = not args.skip_images

    if upload_images and not config.cloudinary_configured():
        print(
            "Cloudinary is not configured, so images cannot be migrated.\n"
            "Either set CLOUDINARY_CLOUD_NAME / CLOUDINARY_API_KEY / "
            "CLOUDINARY_API_SECRET in .env, or re-run with --skip-images to "
            "migrate the database rows only."
        )
        return 1

    source_client = MongoClient(args.source_uri, serverSelectionTimeoutMS=8000)

    try:
        source_client.admin.command("ping")
    except Exception as error:
        print(f"Could not connect to the local database at {args.source_uri}: {error}")
        return 1

    source_db = source_client[args.source_db]

    from backend.db import db as destination_db, ping as ping_destination

    ok, detail = ping_destination()

    if not ok:
        print(f"Could not connect to the shared database: {detail}")
        return 1

    report = {
        "users_migrated": 0,
        "users_already_present": 0,
        "users_skipped_no_email": 0,
        "wardrobe_migrated": 0,
        "wardrobe_already_present": 0,
        "trips_migrated": 0,
        "trips_already_present": 0,
        "images_uploaded": 0,
        "images_to_upload": 0,
        "images_missing_on_disk": [],
        "image_failures": [],
        "unassigned": [],
    }

    print(f"Source      : {args.source_uri} / {args.source_db}")
    print(f"Destination : {config.safe_mongo_host()} / {config.MONGODB_DB_NAME}")
    print(f"Images      : {'skipped' if not upload_images else 'uploaded to Cloudinary'}")
    print(f"Mode        : {'DRY RUN (nothing is written)' if args.dry_run else 'LIVE'}")
    print()

    migrate_users(source_db, destination_db, report, args.dry_run)

    # Built AFTER the user migration so accounts copied in this same
    # run count as known owners, not as orphans.
    known_emails = {
        user.get("email")
        for user in destination_db["users"].find({}, {"email": 1})
        if user.get("email")
    }

    if args.dry_run:
        known_emails |= {
            user.get("email")
            for user in source_db["users"].find({}, {"email": 1})
            if user.get("email")
        }

    migrate_collection(
        "wardrobe", source_db, destination_db, known_emails, report,
        args.dry_run, upload_images,
    )

    migrate_collection(
        "trips", source_db, destination_db, known_emails, report,
        args.dry_run, False,
    )

    print("Summary")
    print("-------")
    print(f"  Users migrated          : {report['users_migrated']}")
    print(f"  Users already in Atlas  : {report['users_already_present']}")
    print(f"  Wardrobe items migrated : {report['wardrobe_migrated']}")
    print(f"  Wardrobe already there  : {report['wardrobe_already_present']}")
    print(f"  Trips migrated          : {report['trips_migrated']}")
    print(f"  Trips already there     : {report['trips_already_present']}")

    if args.dry_run:
        print(f"  Images that would upload: {report['images_to_upload']}")
    else:
        print(f"  Images uploaded         : {report['images_uploaded']}")

    if report["unassigned"]:
        print()
        print(
            f"  {len(report['unassigned'])} record(s) had no matching account "
            f"and were marked '{LEGACY_UNASSIGNED}' rather than guessed at:"
        )
        for line in report["unassigned"][:20]:
            print(f"    - {line}")

    if report["images_missing_on_disk"]:
        print()
        print(
            f"  {len(report['images_missing_on_disk'])} item(s) referenced an "
            "image file that is not on this computer (it may be on the other "
            "laptop - run this script there too):"
        )
        for line in report["images_missing_on_disk"][:20]:
            print(f"    - {line}")

    if report["image_failures"]:
        print()
        print(f"  {len(report['image_failures'])} image upload(s) failed:")
        for line in report["image_failures"][:20]:
            print(f"    - {line}")

    print()
    print(
        "Done. Your local database and local image files were NOT modified."
        if not args.dry_run
        else "Dry run complete - nothing was written or uploaded."
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
