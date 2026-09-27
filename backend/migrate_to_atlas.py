"""
ONE-TIME MIGRATION: this computer's local database and images ->
the shared MongoDB Atlas database and Cloudinary.

Each laptop that used Wardrobe-AI before the centralisation change has
its own local "wardrobe_db" full of real wardrobe items and trips,
plus the actual image files under backend/uploads/. This script copies
them into the shared setup so nothing has to be typed in again.

RECOMMENDED: migrate ONE account at a time
------------------------------------------
    python -m backend.migrate_to_atlas --only-email you@gmail.com --dry-run
    python -m backend.migrate_to_atlas --only-email you@gmail.com

With --only-email:
  * the account must ALREADY exist in Atlas - it is never created,
    and its password, name and profile are never touched;
  * only that account's wardrobe items and trips are copied (matched
    case-insensitively), and they are attached to the Atlas account's
    canonical email - which is exactly what the app uses to decide
    whose wardrobe an item is;
  * no other account on this computer is copied anywhere.

WHAT IT WILL NOT DO
-------------------
  * It never deletes or edits the local database or local image files.
  * It never writes a local path ("/api/uploads/...") into Atlas. An
    item whose image file is missing, or whose Cloudinary upload
    fails, is NOT inserted at all - it is listed, and a re-run picks
    it up once the problem is fixed. Every migrated item therefore
    points at an https Cloudinary URL.
  * It never overwrites an account that already exists in Atlas.
  * It never guesses an owner (full-machine mode only: items whose
    owner has no account are parked under LEGACY_UNASSIGNED).

SAFE TO RUN TWICE (idempotent)
------------------------------
  * Every copied row carries "migrated_from_id" (its local _id), and
    Atlas has a UNIQUE index on it (db.ensure_indexes) - so a row can
    never be inserted twice, even by two runs at once.
  * The Cloudinary public_id is derived from that same id, so an
    image uploaded by an interrupted run is reused, not re-uploaded.
  * An item whose exact photo (SHA-256 of the file) is already in that
    account's cloud wardrobe is skipped as a duplicate - this is what
    stops a second machine's copy of the same wardrobe doubling it.

FULL-MACHINE MODE (the original behaviour, all accounts):
    python -m backend.migrate_to_atlas --dry-run
    python -m backend.migrate_to_atlas
"""

import argparse
import hashlib
import os
import socket
import sys
from datetime import datetime

from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

from backend import config, storage
from backend.identity import normalize_email, email_match_filter


LEGACY_UNASSIGNED = "legacy_unassigned"

DEFAULT_SOURCE_URI = "mongodb://localhost:27017/"
DEFAULT_SOURCE_DB = "wardrobe_db"


def local_path_for(image_path):
    """
    A stored image reference -> a real file on this disk, or None.

    Old rows hold "/api/uploads/<folder>/<file>", which maps onto
    backend/uploads/<folder>/<file>. A row that already holds an https
    URL needs no upload.
    """
    if not image_path or storage.is_remote_url(image_path):
        return None

    relative = image_path

    for prefix in ("/api/uploads/", "api/uploads/", "/uploads/", "uploads/"):
        if relative.startswith(prefix):
            relative = relative[len(prefix):]
            break

    candidate = os.path.normpath(os.path.join(storage.BASE_UPLOAD_FOLDER, relative))

    # Never follow a stored path out of the uploads folder.
    if not candidate.startswith(os.path.normpath(storage.BASE_UPLOAD_FOLDER) + os.sep):
        return None

    return candidate if os.path.isfile(candidate) else None


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# Names too generic to identify a photo on their own.
GENERIC_NAMES = {"image.jpg", "image.jpeg", "image.png", "item.jpg", "photo.jpg", "blob", "upload.jpg"}


def photo_name(path_or_url):
    """Original file name of a local image path, lower-cased ('' if generic)."""
    name = os.path.basename(str(path_or_url or "")).strip().lower()
    return "" if name in GENERIC_NAMES else name


def new_report():
    return {
        "users_migrated": 0,
        "users_already_present": 0,
        "users_skipped_no_email": 0,
        "wardrobe_source": 0,
        "wardrobe_migrated": 0,
        "wardrobe_already_present": 0,
        "wardrobe_duplicate_photo": 0,
        "trips_source": 0,
        "trips_migrated": 0,
        "trips_already_present": 0,
        "images_uploaded": 0,
        "images_to_upload": 0,
        "images_missing_on_disk": [],
        "image_failures": [],
        "unassigned": [],
    }


def migrate_users(source_db, destination_db, report, dry_run):
    """Full-machine mode only. Never touches an account already in Atlas."""
    from backend.auth import find_user_by_email

    for user in source_db["users"].find({}):

        email = normalize_email(user.get("email"))

        if not email:
            report["users_skipped_no_email"] += 1
            continue

        if find_user_by_email(email):
            report["users_already_present"] += 1
            continue

        document = dict(user)
        document["email"] = email
        document["migrated_from_id"] = str(document.pop("_id", ""))

        if not dry_run:
            try:
                destination_db["users"].insert_one(document)
            except DuplicateKeyError:
                report["users_already_present"] += 1
                continue

        report["users_migrated"] += 1


def migrate_collection(
    name,
    source_db,
    destination_db,
    report,
    dry_run,
    upload_images,
    owner_resolver,
    source_filter,
):
    """
    Copies one owned collection ("wardrobe" or "trips").

    owner_resolver(raw_email) -> the canonical Atlas email to store as
    user_email, or None when the owner has no account.
    """
    destination = destination_db[name]
    source_rows = list(source_db[name].find(source_filter))
    report[f"{name}_source"] = len(source_rows)

    # Photos already in each owner's cloud wardrobe, for the
    # duplicate-photo check. Loaded lazily per owner.
    #
    # Items copied by the OLDER migration script carry no fingerprint,
    # only their original file name (original_filename, or the legacy
    # local_image_path) - so the same photo is also recognised by name.
    known_hashes = {}
    known_names = {}

    def hashes_for(owner):
        if owner not in known_hashes:
            known_hashes[owner] = set()
            known_names[owner] = set()
            for row in destination.find({"user_email": owner}):
                if row.get("image_sha256"):
                    known_hashes[owner].add(row["image_sha256"])
                name = photo_name(row.get("original_filename") or row.get("local_image_path"))
                if name:
                    known_names[owner].add(name)
        return known_hashes[owner]

    for row in source_rows:

        original_id = str(row.get("_id", ""))

        if original_id and destination.find_one({"migrated_from_id": original_id}):
            report[f"{name}_already_present"] += 1
            continue

        document = dict(row)
        document.pop("_id", None)
        document.pop("local_image_path", None)
        document["migrated_from_id"] = original_id
        document["migrated_at"] = datetime.utcnow()
        document["migrated_from_host"] = socket.gethostname()

        raw_owner = document.get("user_email")
        owner = owner_resolver(raw_owner)

        if owner is None:
            document["original_user_email"] = raw_owner or ""
            owner = LEGACY_UNASSIGNED
            report["unassigned"].append(f"{name}: {original_id} (owner: {raw_owner or 'missing'})")

        document["user_email"] = owner

        if upload_images:

            stored = document.get("image_path")
            source_path = local_path_for(stored)

            if stored and not storage.is_remote_url(stored) and not source_path:
                # The file is not on this computer. Inserting the row
                # would put a dead local path into the cloud database,
                # so it is skipped and listed instead.
                report["images_missing_on_disk"].append(f"{original_id}: {stored}")
                continue

            if source_path:

                photo_hash = file_sha256(source_path)
                document["image_sha256"] = photo_hash
                document["original_filename"] = os.path.basename(source_path)
                name_key = photo_name(source_path)

                if photo_hash in hashes_for(owner) or (name_key and name_key in known_names[owner]):
                    report[f"{name}_duplicate_photo"] += 1
                    continue

                if dry_run:
                    report["images_to_upload"] += 1
                    hashes_for(owner).add(photo_hash)
                    if name_key:
                        known_names[owner].add(name_key)
                    report[f"{name}_migrated"] += 1
                    continue

                try:
                    document["image_path"] = storage.upload_local_file(
                        source_path,
                        owner,
                        kind="wardrobe",
                        public_id=f"migrated_{original_id}",
                    )
                    document["image_public_id"] = (
                        f"ai-wardrobe/{storage.user_folder_key(owner)}/wardrobe/"
                        f"migrated_{original_id}"
                    )
                    report["images_uploaded"] += 1
                except storage.StorageError as error:
                    report["image_failures"].append(f"{original_id}: {error}")
                    continue

                if not storage.is_remote_url(document["image_path"]):
                    report["image_failures"].append(f"{original_id}: upload returned no https URL")
                    continue

                hashes_for(owner).add(photo_hash)
                if name_key:
                    known_names[owner].add(name_key)

        if not dry_run:
            try:
                destination.insert_one(document)
            except DuplicateKeyError:
                report[f"{name}_already_present"] += 1
                continue

        report[f"{name}_migrated"] += 1


def verify_owner(destination_db, email, check_urls=True):
    """
    Re-reads Atlas (never trusts the migration's own counters) and
    returns (ok, lines) describing one account's cloud data.
    """
    from backend.auth import find_user_by_email

    lines = []
    ok = True

    accounts = list(destination_db["users"].find(email_match_filter(email), {"_id": 1, "email": 1}))
    lines.append(f"Accounts for this email      : {len(accounts)}")
    if len(accounts) != 1:
        ok = False
        lines.append("  PROBLEM: expected exactly one account")

    user = find_user_by_email(email)
    if not user:
        return False, lines

    owner = normalize_email(user.get("email"))
    lines.append(f"Account id                   : {user['_id']}")

    items = list(destination_db["wardrobe"].find({"user_email": owner}))
    stray = destination_db["wardrobe"].count_documents(
        {"$and": [email_match_filter(owner, "user_email"), {"user_email": {"$ne": owner}}]}
    )
    remote = [i for i in items if str(i.get("image_path", "")).startswith("https://")]
    local = [i for i in items if i.get("image_path") and not storage.is_remote_url(i.get("image_path"))]
    migrated = [i for i in items if i.get("migrated_from_id")]
    origin_ids = [i["migrated_from_id"] for i in migrated]
    hashes = [i.get("image_sha256") for i in items if i.get("image_sha256")]

    lines.append(f"Wardrobe items               : {len(items)}")
    lines.append(f"  of which migrated          : {len(migrated)}")
    lines.append(f"  with https cloud image URL : {len(remote)}")
    legacy = [i for i in items if i.get("local_image_path")]
    lines.append(f"  with a LOCAL image path    : {len(local)}")
    lines.append(f"  with a leftover local_image_path field: {len(legacy)}")
    lines.append(f"  duplicate migrations       : {len(origin_ids) - len(set(origin_ids))}")
    lines.append(f"  duplicate photos           : {len(hashes) - len(set(hashes))}")
    lines.append(f"  missing category           : {sum(1 for i in items if not i.get('category'))}")
    lines.append(f"Items under a mis-cased email: {stray}")
    lines.append(f"Trips                        : {destination_db['trips'].count_documents({'user_email': owner})}")

    if local or legacy or stray or len(origin_ids) != len(set(origin_ids)):
        ok = False

    if check_urls and remote:
        import urllib.request

        loaded = 0
        failed = []
        for item in remote:
            try:
                request = urllib.request.Request(item["image_path"], method="HEAD")
                with urllib.request.urlopen(request, timeout=15) as response:
                    if response.status == 200:
                        loaded += 1
                        continue
            except Exception as error:  # noqa: BLE001
                failed.append(f"{item['_id']}: {type(error).__name__}")
                continue
            failed.append(str(item["_id"]))
        lines.append(f"Cloud image URLs that load   : {loaded}/{len(remote)}")
        if failed:
            ok = False
            lines.extend(f"  did not load: {f}" for f in failed[:10])

    return ok, lines


def main(argv=None):

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source-uri", default=DEFAULT_SOURCE_URI)
    parser.add_argument("--source-db", default=DEFAULT_SOURCE_DB)
    parser.add_argument("--only-email", default=None,
                        help="Migrate ONLY this account's items and trips into its existing Atlas account.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would be migrated without writing or uploading.")
    parser.add_argument("--verify-only", action="store_true",
                        help="With --only-email: just report that account's cloud state.")
    parser.add_argument("--skip-images", action="store_true",
                        help="Full-machine mode only: copy rows without images (NOT for real migrations).")
    args = parser.parse_args(argv)

    config.validate(strict=True)

    from backend.db import db as destination_db, ping as ping_destination, ensure_indexes
    from backend.auth import find_user_by_email

    ok, detail = ping_destination()
    if not ok:
        print(f"Could not connect to the shared database: {detail}")
        return 1

    only_email = normalize_email(args.only_email) if args.only_email else None

    if args.verify_only:
        if not only_email:
            print("--verify-only needs --only-email")
            return 1
        passed, lines = verify_owner(destination_db, only_email)
        print("\n".join(lines))
        print("\nVerification passed." if passed else "\nVerification found problems (see above).")
        return 0 if passed else 1

    if config.MONGODB_URI.strip().rstrip("/") == args.source_uri.strip().rstrip("/"):
        print("Source and destination are the same database - point MONGODB_URI in .env at Atlas first.")
        return 1

    # A computer whose local data must NEVER be migrated (e.g. one that
    # holds only an older, partial copy of someone's wardrobe) carries
    # this marker file. It lives in backend/uploads/, which git ignores,
    # so it stays on that one computer.
    blocker = os.path.join(storage.BASE_UPLOAD_FOLDER, ".not_a_migration_source")
    if os.path.isfile(blocker):
        print("This computer is marked as NOT a migration source")
        print(f"({blocker} exists): its local data is an old/partial copy")
        print("and must not be copied to Atlas. Run the migration on the")
        print("computer that holds the original data instead. Nothing was changed.")
        return 1

    if only_email and args.skip_images:
        print("--skip-images is not allowed with --only-email: it would leave local paths in Atlas.")
        return 1

    upload_images = not args.skip_images

    if upload_images and not config.cloudinary_configured():
        print("Cloudinary is not configured (CLOUDINARY_* in .env), so images cannot be migrated.")
        return 1

    # Uniqueness guarantees must be in place BEFORE anything is copied.
    problems = ensure_indexes()
    for problem in problems:
        print(f"WARNING: index not in place - {problem}")
    if only_email and any("migrated_from_id" in p for p in problems):
        print("Stopping: the duplicate-protection index could not be created.")
        return 1

    source_client = MongoClient(args.source_uri, serverSelectionTimeoutMS=8000)
    try:
        source_client.admin.command("ping")
    except Exception as error:  # noqa: BLE001
        print(f"Could not connect to the local database at {args.source_uri}: {error}")
        return 1
    source_db = source_client[args.source_db]

    report = new_report()

    print(f"Source      : {args.source_uri} / {args.source_db}")
    print(f"Destination : {config.safe_mongo_host()} / {config.MONGODB_DB_NAME}")
    print(f"Account     : {only_email or 'ALL accounts on this computer'}")
    print(f"Images      : {'skipped' if not upload_images else 'uploaded to Cloudinary'}")
    print(f"Mode        : {'DRY RUN (nothing is written)' if args.dry_run else 'LIVE'}")
    print()

    if only_email:

        account = find_user_by_email(only_email)
        if not account:
            print(f"No Atlas account exists for {only_email}. Nothing was migrated.")
            print("(This script never creates the account - register it in the app first.)")
            return 1

        canonical = normalize_email(account.get("email"))
        print(f"Atlas account found: id {account['_id']} - it will not be modified.\n")

        def owner_resolver(_raw):
            return canonical

        source_filter = email_match_filter(only_email, "user_email")

        files_here = 0
        folder = os.path.join(storage.BASE_UPLOAD_FOLDER, f"{only_email.split('@')[0]}_digital_wardrobe")
        if os.path.isdir(folder):
            files_here = sum(1 for n in os.listdir(folder) if os.path.isfile(os.path.join(folder, n)))
        print(f"Local image files in {os.path.basename(folder)}: {files_here}")

    else:
        migrate_users(source_db, destination_db, report, args.dry_run)

        known = {
            normalize_email(u.get("email"))
            for u in destination_db["users"].find({}, {"email": 1})
            if u.get("email")
        }
        if args.dry_run:
            known |= {normalize_email(u.get("email")) for u in source_db["users"].find({}, {"email": 1}) if u.get("email")}

        def owner_resolver(raw):
            email = normalize_email(raw)
            return email if email in known else None

        source_filter = {}

    migrate_collection("wardrobe", source_db, destination_db, report, args.dry_run,
                       upload_images, owner_resolver, source_filter)
    migrate_collection("trips", source_db, destination_db, report, args.dry_run,
                       False, owner_resolver, source_filter)

    print("Summary")
    print("-------")
    if not only_email:
        print(f"  Users migrated              : {report['users_migrated']}")
        print(f"  Users already in Atlas      : {report['users_already_present']}")
    print(f"  Wardrobe items on this PC   : {report['wardrobe_source']}")
    print(f"  Wardrobe items {'to migrate ' if args.dry_run else 'migrated   '} : {report['wardrobe_migrated']}")
    print(f"  Wardrobe already in Atlas   : {report['wardrobe_already_present']}")
    print(f"  Same photo already in cloud : {report['wardrobe_duplicate_photo']}")
    print(f"  Trips on this PC            : {report['trips_source']}")
    print(f"  Trips {'to migrate' if args.dry_run else 'migrated  '}            : {report['trips_migrated']}")
    print(f"  Trips already in Atlas      : {report['trips_already_present']}")
    if args.dry_run:
        print(f"  Images that would upload    : {report['images_to_upload']}")
    else:
        print(f"  Images uploaded             : {report['images_uploaded']}")

    for key, title in (
        ("unassigned", "record(s) had no matching account and were parked"),
        ("images_missing_on_disk", "item(s) NOT migrated: image file is not on this computer"),
        ("image_failures", "item(s) NOT migrated: Cloudinary upload failed (re-run to retry)"),
    ):
        if report[key]:
            print(f"\n  {len(report[key])} {title}:")
            for line in report[key][:20]:
                print(f"    - {line}")

    incomplete = bool(report["images_missing_on_disk"] or report["image_failures"])

    if only_email and not args.dry_run:
        print("\nVerification (re-read from Atlas)")
        print("---------------------------------")
        passed, lines = verify_owner(destination_db, only_email)
        print("\n".join("  " + line for line in lines))
        incomplete = incomplete or not passed

    print()
    if args.dry_run:
        print("Dry run complete - nothing was written or uploaded.")
    else:
        print("Done. Your local database and local image files were NOT modified.")
        if incomplete:
            print("Some items still need attention (listed above). Re-running is safe.")

    return 1 if (incomplete and not args.dry_run) else 0


if __name__ == "__main__":
    sys.exit(main())
