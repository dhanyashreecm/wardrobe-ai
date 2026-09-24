"""
ONE COMMAND to move this computer onto the shared setup:

    python -m backend.sync_setup

It runs the whole sequence in the only safe order, stopping the moment
anything is wrong:

    1. CHECK    - .env, MongoDB Atlas, Cloudinary (backend.check_setup)
    2. BACKUP   - a JSON snapshot of this machine's local database
    3. DRY RUN  - exactly what would be migrated, writing nothing
    4. CONFIRM  - waits for you to type "yes"
    5. MIGRATE  - the real thing (backend.migrate_to_atlas)
    6. VERIFY   - re-reads Atlas and checks the result, including that
                  every local file is still where it was

Nothing here deletes anything, on either side. The local database and
the local image files are only ever READ. Step 2 additionally writes a
snapshot of the local data to disk before a single row moves, so even
a catastrophic mistake at the far end leaves the original recoverable.

Each step is also runnable on its own if you prefer:

    python -m backend.check_setup
    python -m backend.migrate_to_atlas --dry-run
    python -m backend.migrate_to_atlas
    python -m backend.sync_setup --verify-only

Resumability comes from migrate_to_atlas itself: every migrated row
records the id it came from, so a run interrupted halfway (laptop
closed, wifi dropped) can simply be run again - it copies only what is
genuinely missing and re-uploads nothing.

No secret is ever printed, by this or by anything it calls.
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime


SEPARATOR = "=" * 64


def heading(text):
    print()
    print(SEPARATOR)
    print(text)
    print(SEPARATOR)


def run_step(description, arguments):
    """
    Runs one stage as its own process. Separate processes rather than
    imports because each stage builds its own database connections and
    configuration; a stage that fails then cannot leave a half-built
    client behind for the next one.
    """
    print(f"\n$ python -m {' '.join(arguments)}\n")

    result = subprocess.run([sys.executable, "-m", *arguments])

    if result.returncode != 0:
        print(f"\n{description} did not succeed. Stopping here.")
        print("Nothing has been migrated, and nothing local was changed.")

    return result.returncode == 0


def snapshot_local_database(source_uri, source_db_name, folder):
    """
    Writes a plain-JSON copy of this machine's local users, wardrobe
    and trips before anything is migrated.

    The migration never deletes local data, so this is belt-and-braces
    - but it costs a second and it is the difference between "something
    went wrong, restore the snapshot" and "something went wrong, hope
    the local database is still intact". Stored as JSON rather than a
    mongodump so it is readable and restorable without extra tools.

    Password hashes are copied as-is (they are hashes, not passwords);
    nothing here is printed to the terminal.
    """
    from pymongo import MongoClient

    client = MongoClient(source_uri, serverSelectionTimeoutMS=8000)

    try:
        client.admin.command("ping")
    except Exception as error:
        print(f"  Could not read the local database at {source_uri}: {error}")
        return None, {}

    database = client[source_db_name]

    snapshot = {}
    counts = {}

    for name in ("users", "wardrobe", "trips"):

        documents = []

        for document in database[name].find({}):
            # _id and datetimes are not JSON types; stringify them so
            # the snapshot is a plain file anyone can open.
            clean = {}
            for key, value in document.items():
                if isinstance(value, (str, int, float, bool, list, dict)) or value is None:
                    clean[key] = value
                elif isinstance(value, bytes):
                    clean[key] = value.decode("utf-8", errors="replace")
                else:
                    clean[key] = str(value)
            documents.append(clean)

        snapshot[name] = documents
        counts[name] = len(documents)

    os.makedirs(folder, exist_ok=True)

    path = os.path.join(
        folder,
        f"local_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
    )

    with open(path, "w", encoding="utf-8") as handle:
        json.dump(snapshot, handle, indent=2, default=str)

    return path, counts


def count_local_images():
    """How many image files this machine actually holds, and where."""
    from backend import storage

    per_folder = {}
    total = 0

    if not os.path.isdir(storage.BASE_UPLOAD_FOLDER):
        return per_folder, total

    for root, _, files in os.walk(storage.BASE_UPLOAD_FOLDER):

        if "_remote_cache" in root:
            continue

        images = [
            name for name in files
            if os.path.splitext(name)[1].lower()
            in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")
        ]

        if images:
            relative = os.path.relpath(root, storage.BASE_UPLOAD_FOLDER)
            per_folder[relative] = len(images)
            total += len(images)

    return per_folder, total


def verify(expected=None):
    """
    Checks the result of a migration against the shared database, and
    confirms the local originals are untouched.

    Deliberately re-reads everything from Atlas rather than trusting
    the migration's own summary - a report generated by the thing being
    tested proves nothing.
    """
    heading("VERIFY")

    from backend import config
    from backend.db import db, ping
    from backend.migrate_to_atlas import LEGACY_UNASSIGNED

    ok, detail = ping()

    if not ok:
        print(f"  Could not reach the shared database: {detail}")
        return False

    print(f"  Shared database : {config.MONGODB_DB_NAME} at {config.safe_mongo_host()}")

    users = list(db["users"].find({}))
    items = list(db["wardrobe"].find({}))
    trips = list(db["trips"].find({}))

    print(f"  Users in Atlas       : {len(users)}")
    print(f"  Wardrobe items       : {len(items)}")
    print(f"  Trips                : {len(trips)}")

    problems = []

    # --- duplicates -------------------------------------------------
    emails = [user.get("email") for user in users if user.get("email")]

    duplicate_emails = {
        email for email in emails if emails.count(email) > 1
    }

    if duplicate_emails:
        problems.append(
            f"{len(duplicate_emails)} email(s) appear on more than one account"
        )
    else:
        print("  Duplicate accounts   : none")

    origin_ids = [
        item.get("migrated_from_id")
        for item in items
        if item.get("migrated_from_id")
    ]

    duplicate_origins = {
        value for value in origin_ids if origin_ids.count(value) > 1
    }

    if duplicate_origins:
        problems.append(
            f"{len(duplicate_origins)} wardrobe item(s) were migrated twice"
        )
    else:
        print("  Duplicate items      : none")

    # --- image references ------------------------------------------
    remote = [
        item for item in items
        if str(item.get("image_path", "")).startswith("https://")
    ]
    local_only = [
        item for item in items
        if item.get("image_path")
        and not str(item.get("image_path")).startswith(("http://", "https://"))
    ]

    print(f"  Items with cloud URL : {len(remote)}")

    if local_only:
        print(
            f"  Items still local    : {len(local_only)} "
            "(their image file was not on this computer - run the "
            "migration on the machine that has it)"
        )

    # --- ownership --------------------------------------------------
    known_emails = set(emails)

    orphans = [
        item for item in items
        if item.get("user_email") == LEGACY_UNASSIGNED
    ]

    misowned = [
        item for item in items
        if item.get("user_email")
        and item.get("user_email") != LEGACY_UNASSIGNED
        and item.get("user_email") not in known_emails
    ]

    if orphans:
        print(f"  Unassigned items     : {len(orphans)} (parked, not guessed at)")

    if misowned:
        problems.append(
            f"{len(misowned)} item(s) reference an account that does not exist"
        )
    else:
        print("  Ownership            : every item belongs to a real account")

    # --- are the URLs actually loadable? ----------------------------
    if remote:
        import urllib.request

        sample = remote[: min(3, len(remote))]
        reachable = 0

        for item in sample:
            try:
                with urllib.request.urlopen(item["image_path"], timeout=15) as response:
                    if response.status == 200:
                        reachable += 1
            except Exception:
                pass

        print(f"  Image URLs reachable : {reachable}/{len(sample)} sampled")

        if reachable < len(sample):
            problems.append(
                "at least one migrated image URL did not load - check Cloudinary"
            )

    # --- the local originals still exist ----------------------------
    per_folder, total_images = count_local_images()

    print(f"  Local image files    : {total_images} still on this computer")

    if expected is not None and total_images < expected:
        problems.append(
            f"expected at least {expected} local image files, found {total_images}"
        )

    print()

    if problems:
        print("  PROBLEMS FOUND:")
        for problem in problems:
            print(f"    - {problem}")
        return False

    print("  Verification passed.")
    return True


def main():

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-uri",
        default="mongodb://localhost:27017/",
        help="This machine's local MongoDB (default: mongodb://localhost:27017/)",
    )
    parser.add_argument(
        "--source-db",
        default="wardrobe_db",
        help="This machine's local database name (default: wardrobe_db)",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Skip straight to verification of an already-migrated setup.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt (for an unattended re-run).",
    )
    args = parser.parse_args()

    if args.verify_only:
        return 0 if verify() else 1

    # ---------------------------------------------------------------
    heading("STEP 1 of 6 - CHECKING THIS COMPUTER'S SETUP")

    if not run_step("The setup check", ["backend.check_setup"]):
        return 1

    # ---------------------------------------------------------------
    heading("STEP 2 of 6 - BACKING UP THIS COMPUTER'S LOCAL DATA")

    print("  Reading the local database (read-only) before anything moves.")

    backup_path, counts = snapshot_local_database(
        args.source_uri, args.source_db, os.path.join("backups"),
    )

    if backup_path is None:
        print(
            "\n  No local database was readable at "
            f"{args.source_uri}.\n"
            "  If this machine has no old data to migrate, that is fine - "
            "re-run with --verify-only after the other machine has "
            "migrated.\n"
            "  If it DOES have old data, start MongoDB first and try again."
        )
        return 1

    for name, count in counts.items():
        print(f"    {name}: {count} record(s)")

    per_folder, total_images = count_local_images()

    print(f"    image files: {total_images}")

    for folder, count in sorted(per_folder.items()):
        print(f"      {folder}: {count}")

    print(f"\n  Snapshot written to: {backup_path}")
    print("  (Your local database and image files were not modified.)")

    # ---------------------------------------------------------------
    heading("STEP 3 of 6 - DRY RUN (nothing is written or uploaded)")

    if not run_step("The dry run", ["backend.migrate_to_atlas", "--dry-run"]):
        return 1

    # ---------------------------------------------------------------
    heading("STEP 4 of 6 - CONFIRMATION")

    print("  The dry run above shows exactly what the real migration will do.")
    print("  It will COPY data to the shared database and upload images to")
    print("  Cloudinary. It will NOT delete or change anything on this")
    print("  computer - your local database and image files stay as they are.")

    if not args.yes:

        print()
        try:
            answer = input("  Type 'yes' to run the real migration: ").strip().lower()
        except EOFError:
            answer = ""

        if answer != "yes":
            print("\n  Stopped. Nothing was migrated.")
            print(f"  Your backup is still at: {backup_path}")
            return 0

    # ---------------------------------------------------------------
    heading("STEP 5 of 6 - MIGRATING")

    if not run_step("The migration", ["backend.migrate_to_atlas"]):
        print(f"\n  Your local data is untouched, and backed up at: {backup_path}")
        print("  Fix the problem above and run this command again - it will")
        print("  resume, copying only what is still missing.")
        return 1

    # ---------------------------------------------------------------
    heading("STEP 6 of 6 - VERIFYING THE RESULT")

    passed = verify(expected=total_images)

    print()
    print(SEPARATOR)

    if passed:
        print("DONE. This computer's data is now in the shared setup.")
        print()
        print("Next:")
        print("  1. Run this same command on the OTHER computer (with the")
        print("     same .env values) if it also has old local data.")
        print("  2. Point both computers' .env at the shared database, then")
        print("     start the app and check the wardrobe appears on both:")
        print("        python -m backend.sync_test send     (on one machine)")
        print("        python -m backend.sync_test check    (on the other)")
    else:
        print("Migration ran, but verification found problems - see above.")
        print(f"Your local data is untouched, and backed up at: {backup_path}")

    print(SEPARATOR)

    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
