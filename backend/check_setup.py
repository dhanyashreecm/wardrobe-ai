"""
SETUP VERIFIER - checks this computer against the REAL services.

Everything up to this point could be verified with stand-ins. This
script is what proves the real thing: that this machine's .env is
loaded, that MongoDB Atlas actually answers, and that an image really
does reach Cloudinary and come back over https. Run it on BOTH
computers - a setup that works on one and not the other is exactly the
failure this whole change exists to prevent.

    python -m backend.check_setup                 # everything
    python -m backend.check_setup --skip-upload   # no test upload
    python -m backend.check_setup --keep-test-image

NEVER PRINTS A SECRET
---------------------
A setup check is worthless if running it, or pasting its output to
someone helping you, leaks the database password. So no value from
.env is ever printed. Instead each setting is reported as present or
missing, with its length and a short fingerprint (the first 8
characters of its SHA-256 hash). The fingerprint is one-way, so it
cannot be turned back into the value, but it IS comparable: run this
on both computers and if the fingerprints for MONGODB_URI,
MONGODB_DB_NAME and JWT_SECRET_KEY match, the two machines really are
pointed at the same database with the same signing key - which is the
single most common thing to get wrong, and impossible to confirm by
eye when the values are long and secret.

The test image it uploads is a tiny generated square, not one of your
photos, and it is deleted from Cloudinary again unless you pass
--keep-test-image.
"""

import argparse
import hashlib
import io
import os
import sys
import urllib.request


GREEN = "ok  "
RED = "FAIL"
WARN = "warn"


def fingerprint(value):
    """
    Short one-way hash of a secret, safe to print and to compare
    across two computers. Not reversible; not a checksum anyone can
    use to guess the value.
    """
    if not value:
        return "--------"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


def line(status, label, detail=""):
    print(f"  [{status}] {label}" + (f" - {detail}" if detail else ""))


def check_environment():
    """
    Step 4: is .env being read, and is each required value present?
    Reports presence/length/fingerprint only.
    """
    print("\n1. CONFIGURATION")

    from backend import config

    env_file = config.PROJECT_ROOT / ".env"

    if env_file.is_file():
        line(GREEN, ".env found", str(env_file.name) + " in the project root")
    else:
        line(
            RED,
            ".env NOT found",
            f"expected at {env_file} - copy .env.example to .env and fill it in",
        )
        return False

    file_values = config._parse_env_file(env_file)

    line(GREEN, ".env parsed", f"{len(file_values)} setting(s) read from the file")

    settings = [
        ("MONGODB_URI", True),
        ("MONGODB_DB_NAME", True),
        ("JWT_SECRET_KEY", True),
        ("CLOUDINARY_CLOUD_NAME", False),
        ("CLOUDINARY_API_KEY", False),
        ("CLOUDINARY_API_SECRET", False),
        ("OPENWEATHER_API_KEY", False),
    ]

    all_required_present = True

    for name, required in settings:

        value = os.environ.get(name, "").strip()

        if not value:
            if required:
                all_required_present = False
                line(RED, f"{name} missing", "required - the app will not start")
            else:
                line(WARN, f"{name} not set", "optional - see README for what it enables")
            continue

        # A value the shell exported beats the file (config.py uses
        # setdefault). Worth surfacing: an old exported variable
        # silently winning over a corrected .env is a genuinely
        # confusing way to lose an afternoon.
        source = "from .env"

        if name in file_values and file_values[name] != value:
            source = "FROM SHELL (overriding .env)"

        elif name not in file_values:
            source = "from shell environment"

        line(
            GREEN,
            f"{name} present",
            f"{len(value)} chars, fingerprint {fingerprint(value)}, {source}",
        )

    print()
    print("  Compare the fingerprints above with the other computer's.")
    print("  MONGODB_URI, MONGODB_DB_NAME and JWT_SECRET_KEY must match")
    print("  on both machines, or they will not share one wardrobe.")

    return all_required_present


def check_database():
    """Step 5: does the REAL Atlas cluster answer, and which one is it?"""
    print("\n2. MONGODB ATLAS")

    from backend import config
    from backend.db import db, ping

    line(GREEN, "target database", config.MONGODB_DB_NAME)
    line(GREEN, "target host", config.safe_mongo_host())

    if config.safe_mongo_host().startswith(("localhost", "127.0.0.1")):
        line(
            WARN,
            "this is a LOCAL database",
            "fine for solo work, but two computers will NOT share data",
        )

    ok, detail = ping()

    if not ok:
        line(RED, "connection failed", detail)
        print()
        print("  Most common causes, in order:")
        print("   1. The password in MONGODB_URI is wrong, or still says")
        print("      <password>. Atlas -> Database Access -> Edit -> reset it.")
        print("   2. This computer's IP is not allowed. Atlas -> Network")
        print("      Access -> Add IP Address -> Add Current IP Address.")
        print("   3. dnspython is missing (needed for mongodb+srv://):")
        print("      pip install dnspython")

        if "SSL" in detail or "TLS" in detail or "handshake" in detail.lower():
            print()
            print("  This one is an SSL HANDSHAKE failure, which is a")
            print("  certificate problem on THIS computer, not a problem with")
            print("  your password, your IP allow-list, or Atlas itself:")
            print("   - make sure certifi is installed:  pip install certifi")
            print("   - if it still fails, this machine's Python is too old to")
            print("     negotiate TLS with Atlas (macOS system Python is the")
            print("     usual culprit). Installing Python 3.11+ from")
            print("     python.org and rebuilding the virtualenv fixes it.")

        return False

    line(GREEN, "connection", "Atlas answered a ping")

    # Read-only look at what is actually in there - this is also the
    # "did my migration land?" check after step 7.
    try:
        for collection in ("users", "wardrobe", "trips"):
            count = db[collection].count_documents({})
            line(GREEN, f"collection '{collection}'", f"{count} document(s)")

    except Exception as error:
        line(WARN, "could not count documents", str(error))

    return True


def check_storage(skip_upload=False, keep_test_image=False):
    """
    Step 6: does an image really reach Cloudinary, and does the URL
    really work? Uses the app's own storage module, so this tests the
    code path uploads actually take - not a separate one written to
    look good.
    """
    print("\n3. CLOUDINARY IMAGE STORAGE")

    from backend import config, storage

    if not config.cloudinary_configured():
        line(
            RED,
            "Cloudinary not configured",
            "images would be saved to THIS computer only and would not "
            "appear on the other machine",
        )
        return False

    line(GREEN, "credentials present", f"cloud name fingerprint {fingerprint(config.CLOUDINARY_CLOUD_NAME)}")

    if skip_upload:
        line(WARN, "upload test skipped", "--skip-upload was passed")
        return True

    try:
        from PIL import Image
    except ImportError:
        line(WARN, "upload test skipped", "Pillow not installed in this environment")
        return True

    # A generated 40x40 square, never one of the user's photos.
    buffer = io.BytesIO()
    Image.new("RGB", (40, 40), color=(90, 140, 200)).save(buffer, format="JPEG")
    buffer.seek(0)

    temporary_path = os.path.join(storage.BASE_UPLOAD_FOLDER, "_setup_check.jpg")

    with open(temporary_path, "wb") as handle:
        handle.write(buffer.getvalue())

    try:
        url = storage.upload_local_file(
            temporary_path,
            "setup-check@wardrobe-ai.local",
            kind="setup-check",
        )

    except storage.StorageError as error:
        line(RED, "upload failed", str(error))
        print()
        print("  Most common causes:")
        print("   1. One of the three CLOUDINARY_ values is wrong - check")
        print("      them against the Cloudinary dashboard.")
        print("   2. The 'cloudinary' package is not installed:")
        print("      pip install cloudinary")
        print("   3. No internet connection.")
        os.remove(temporary_path)
        return False

    finally:
        if os.path.isfile(temporary_path):
            os.remove(temporary_path)

    line(GREEN, "upload succeeded", "Cloudinary accepted the image")

    if not url.startswith("https://"):
        line(RED, "returned URL is not https", url[:60])
        return False

    line(GREEN, "URL is https", "this is what gets stored in the database")

    # The folder must identify the user without revealing them.
    if "setup-check@" in url or "wardrobe-ai.local" in url:
        line(RED, "URL contains the email address", "privacy problem")
        return False

    line(GREEN, "URL contains no email address", "folder is a one-way hash")

    # Fetching it back is the part that actually proves another
    # computer could display it.
    try:
        request = urllib.request.Request(url, method="GET")

        with urllib.request.urlopen(request, timeout=15) as response:
            status = response.status
            content_type = response.headers.get("Content-Type", "")
            body_length = len(response.read())

    except Exception as error:
        line(RED, "URL is not reachable", str(error))
        return False

    line(GREEN, "URL loads over the internet", f"HTTP {status}, {body_length} bytes")

    if not content_type.startswith("image/"):
        line(WARN, "unexpected content type", content_type)
    else:
        line(GREEN, "served as an image", content_type)

    # And that the AI code can still read the pixels back.
    cached = storage.local_copy_of(url)

    if cached and os.path.isfile(cached):
        line(GREEN, "readable by the AI modules", "fetched back to a local file")
    else:
        line(WARN, "could not cache the image locally", "similar-search may skip it")

    if keep_test_image:
        line(WARN, "test image kept in Cloudinary", "--keep-test-image was passed")
    else:
        _delete_test_image(url)

    return True


def _delete_test_image(url):
    """
    Removes the test upload again so the account is not left with
    clutter. Failing to delete is not a failure of the setup, so it is
    reported and shrugged off.
    """
    try:
        import cloudinary.uploader

        # public_id is the URL path after ".../upload/", minus the
        # version prefix and the extension.
        tail = url.split("/upload/", 1)[1]

        if tail.startswith("v") and "/" in tail:
            tail = tail.split("/", 1)[1]

        public_id = os.path.splitext(tail)[0]

        cloudinary.uploader.destroy(public_id)

        line(GREEN, "test image removed", "Cloudinary account left clean")

    except Exception as error:
        line(WARN, "could not remove the test image", f"harmless - {error}")


def main():

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-upload", action="store_true",
                        help="Check credentials without uploading a test image.")
    parser.add_argument("--keep-test-image", action="store_true",
                        help="Leave the test image in Cloudinary.")
    args = parser.parse_args()

    print("=" * 62)
    print("Wardrobe-AI setup check - no secret values are printed")
    print("=" * 62)

    try:
        environment_ok = check_environment()

    except Exception as error:
        print(f"\n  [{RED}] configuration could not be loaded - {error}")
        return 1

    if not environment_ok:
        print("\nStopping here: fix the missing settings above first.")
        return 1

    database_ok = check_database()

    if not database_ok:
        print("\nStopping here: the database must work before anything else.")
        print("Nothing was migrated and nothing was changed.")
        return 1

    storage_ok = check_storage(args.skip_upload, args.keep_test_image)

    print("\n" + "=" * 62)

    if database_ok and storage_ok:
        print("RESULT: this computer is correctly set up.")
        print()
        print("Next: run the same command on the OTHER computer and check")
        print("that the MONGODB_URI, MONGODB_DB_NAME and JWT_SECRET_KEY")
        print("fingerprints are identical on both.")
        return 0

    print("RESULT: the database works, but image storage does not.")
    print("The app will run, but photos uploaded here will not appear")
    print("on the other computer. Fix the Cloudinary values in .env.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
