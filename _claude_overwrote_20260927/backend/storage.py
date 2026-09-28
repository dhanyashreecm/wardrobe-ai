"""
Where uploaded images actually go.

Wardrobe photos used to be written straight to backend/uploads/ on
whichever computer received the upload, and the database stored a path
like "/api/uploads/ganga_digital_wardrobe/shirt.jpg". That path is
only meaningful on the machine holding the file, so even with a shared
database the other computer would show a broken image. This module
sends the file to Cloudinary instead and returns a permanent https URL
that any machine (and any browser) can load.

TWO BACKENDS, ONE FUNCTION
---------------------------
save_image() picks the backend from configuration, so no caller needs
to know which is in use:

  * "cloudinary" - all three CLOUDINARY_* values are set. The file is
    uploaded and the returned URL is a full https://res.cloudinary.com
    link. This is what makes images work across computers.

  * "local" - Cloudinary is not configured. The file is written to
    backend/uploads/ exactly as before and the returned URL is the old
    relative "/api/uploads/..." path. Nothing breaks, but those images
    stay on that one machine. config.warnings() says so at startup and
    /api/health reports it, so this is a visible state, not a silent
    one.

BACKWARD COMPATIBILITY
-----------------------
Items uploaded before this change still hold a relative
"/api/uploads/..." path in the database. Nothing rewrites them: the
route that serves those files is still there, and the frontend's
assetUrl() helper passes an absolute https URL through untouched while
prefixing a relative one with the API base. So old items keep working
on the machine that holds their files, and new items work everywhere.
Existing items can be moved to Cloudinary properly with
backend/migrate_to_atlas.py.

PRIVACY OF THE FOLDER NAME
---------------------------
Cloudinary paths are effectively public to anyone holding the URL, so
the folder is keyed by a short hash of the email rather than the email
itself ("ai-wardrobe/9f86d081884c7d65/wardrobe/..."). It still groups
one user's images together for debugging, without putting an address
into a public URL.
"""

import hashlib
import io
import os
import time
import uuid

from werkzeug.utils import secure_filename

from backend import config


# Where the "local" backend writes, and where legacy images already
# live. Unchanged from the original app.py behaviour.
BASE_UPLOAD_FOLDER = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "uploads",
)

os.makedirs(BASE_UPLOAD_FOLDER, exist_ok=True)


# Set on the first Cloudinary call rather than at import time, so the
# backend still starts (in local mode) on a machine where the
# cloudinary package was never installed.
_cloudinary_ready = False


class StorageError(RuntimeError):
    """
    An upload failed. Raised instead of returning None so a caller
    cannot accidentally save a wardrobe item whose image never made it
    anywhere - a row pointing at nothing is worse than a failed upload
    the user can retry.
    """


def user_folder_key(user_email):
    """
    Short, stable, non-reversible id for one user's images. The same
    email always yields the same folder, so a user's uploads group
    together, but the folder name reveals nothing about who they are.
    Normalised first, so "Ganga@Gmail.com" and "ganga@gmail.com" share
    one folder.
    """
    user_email = (user_email or "").strip().lower()
    digest = hashlib.sha256(user_email.encode("utf-8")).hexdigest()
    return digest[:16]


def legacy_local_folder(user_email):
    """
    The pre-Cloudinary folder name for a user ("ganga_digital_wardrobe")
    and its path on disk.

    Still needed for two reasons: the local backend keeps using it (so
    a machine without Cloudinary behaves exactly as before), and
    deleting an account still has to clean up the folder its older
    images are in.
    """
    username = (user_email or "unknown").split("@")[0]

    folder_name = f"{username}_digital_wardrobe"

    folder_path = os.path.join(BASE_UPLOAD_FOLDER, folder_name)

    os.makedirs(folder_path, exist_ok=True)

    return folder_name, folder_path


def _ensure_cloudinary():
    """
    Configures the cloudinary SDK once, and turns the two predictable
    setup failures into errors that say what to do about them.
    """
    global _cloudinary_ready

    try:
        import cloudinary  # noqa: F401
        import cloudinary.uploader  # noqa: F401
    except ImportError:
        raise StorageError(
            "Cloudinary is configured in .env but the 'cloudinary' Python "
            "package is not installed in this environment. Install it with: "
            "pip install cloudinary"
        )

    if not _cloudinary_ready:

        import cloudinary

        cloudinary.config(
            cloud_name=config.CLOUDINARY_CLOUD_NAME,
            api_key=config.CLOUDINARY_API_KEY,
            api_secret=config.CLOUDINARY_API_SECRET,
            secure=True,
        )

        _cloudinary_ready = True

    import cloudinary.uploader

    return cloudinary.uploader


def _unique_public_id(filename):
    """
    A collision-proof name for the stored file.

    Two users both uploading "IMG_1234.jpg" - or the same user
    uploading it twice - must not overwrite each other, which a plain
    filename would allow. The original name is kept as a readable
    prefix purely so a human browsing the storage can recognise it.
    """
    stem = os.path.splitext(secure_filename(filename or "image"))[0]

    stem = stem[:40] or "image"

    return f"{stem}_{int(time.time())}_{uuid.uuid4().hex[:8]}"


def save_image(file_storage, user_email, kind="wardrobe"):
    """
    Stores an uploaded file and returns (url, details).

    `file_storage` is the Werkzeug object straight off request.files.
    `kind` separates wardrobe photos from profile pictures in storage.

    `url` is what belongs in the database: an https Cloudinary URL when
    Cloudinary is configured, or the relative "/api/uploads/..." path
    when it is not. `details` carries the backend name, the storage
    identifier (needed to delete the image later) and, for the local
    backend, the filesystem path.

    Raises StorageError if the file could not be stored - never returns
    a URL that does not point at a real image.
    """
    if file_storage is None:
        raise StorageError("No image file was provided.")

    if config.storage_backend() == "cloudinary":
        return _save_to_cloudinary(file_storage, user_email, kind)

    return _save_locally(file_storage, user_email, kind)


def _save_to_cloudinary(file_storage, user_email, kind):

    uploader = _ensure_cloudinary()

    folder = f"ai-wardrobe/{user_folder_key(user_email)}/{kind}"

    public_id = _unique_public_id(getattr(file_storage, "filename", ""))

    try:
        # file_storage.stream is re-read by other code paths (the AI
        # classifier reads the saved file, not this stream), so rewind
        # first - a stream left at EOF by an earlier read would upload
        # zero bytes without erroring.
        file_storage.stream.seek(0)

        result = uploader.upload(
            file_storage.stream,
            folder=folder,
            public_id=public_id,
            resource_type="image",
            overwrite=False,
        )

    except StorageError:
        raise

    except Exception as error:
        raise StorageError(
            f"Could not upload the image to Cloudinary: {error}"
        )

    url = result.get("secure_url")

    if not url:
        raise StorageError(
            "Cloudinary accepted the upload but returned no secure_url."
        )

    return url, {
        "backend": "cloudinary",
        "public_id": result.get("public_id"),
        "local_path": None,
    }


def _save_locally(file_storage, user_email, kind):

    folder_name, folder_path = legacy_local_folder(user_email)

    if kind != "wardrobe":
        folder_path = os.path.join(folder_path, kind)
        folder_name = f"{folder_name}/{kind}"
        os.makedirs(folder_path, exist_ok=True)

    filename = secure_filename(
        getattr(file_storage, "filename", "") or "image.jpg"
    )

    path = os.path.join(folder_path, filename)

    try:
        file_storage.stream.seek(0)
        file_storage.save(path)
    except Exception as error:
        raise StorageError(f"Could not save the image on this computer: {error}")

    return f"/api/uploads/{folder_name}/{filename}", {
        "backend": "local",
        "public_id": None,
        "local_path": path,
    }


# Cloudinary's free plan rejects images over 10 MB, while the app
# accepts photos up to 15 MB - so a large phone photo used to pass
# validation and then fail with "Upload failed" at the very last step.
# Anything over this size is sent as a resized JPEG copy instead (the
# original on disk is never modified).
CLOUD_MAX_BYTES = 9_500_000
CLOUD_MAX_SIDE = 2560


def _within_upload_limit(path):
    try:
        if os.path.getsize(path) <= CLOUD_MAX_BYTES:
            return path
        from PIL import Image, ImageOps

        with Image.open(path) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail((CLOUD_MAX_SIDE, CLOUD_MAX_SIDE))
            smaller = f"{path}.cloud.jpg"
            image.save(smaller, "JPEG", quality=88, optimize=True)
        return smaller
    except Exception as error:  # noqa: BLE001 - fall back to the original
        print(f"Could not shrink {os.path.basename(path)} before upload: {error}")
        return path


def upload_local_file(path, user_email, kind="wardrobe", public_id=None):
    """
    Uploads a file that is ALREADY on disk (as opposed to one arriving
    in a request). Used by the upload route and by the migration script
    to move a machine's existing backend/uploads/ images into
    Cloudinary; kept here so there is exactly one piece of code that
    knows how Cloudinary folders and public ids are built.

    `public_id` lets the migration use a STABLE id per source item, so
    a re-run after an interruption finds the image it already uploaded
    (overwrite=False returns the existing asset) instead of creating a
    second copy in Cloudinary.
    """
    uploader = _ensure_cloudinary()

    folder = f"ai-wardrobe/{user_folder_key(user_email)}/{kind}"

    public_id = public_id or _unique_public_id(os.path.basename(path))

    upload_path = _within_upload_limit(path)

    try:
        result = uploader.upload(
            upload_path,
            folder=folder,
            public_id=public_id,
            resource_type="image",
            overwrite=False,
        )
    except Exception as error:
        raise StorageError(f"Could not upload {path} to Cloudinary: {error}")

    finally:
        if upload_path != path:
            try:
                os.remove(upload_path)
            except OSError:
                pass

    url = result.get("secure_url")

    if not url:
        raise StorageError(f"Cloudinary returned no secure_url for {path}.")

    return url


def save_bytes(image_bytes, user_email, kind="wardrobe", filename_hint="image.png"):
    """
    Stores an image we GENERATED rather than one that arrived in a
    request, and returns (url, details) in the same shape as
    save_image.

    Needed because a virtual try-on result exists only as bytes in
    memory: there is no Werkzeug FileStorage to hand to save_image,
    and writing it to a temporary file just to re-read it would be
    two pointless copies of a large image.
    """
    if not image_bytes:
        raise StorageError("There was no image to store.")

    if config.storage_backend() == "cloudinary":

        uploader = _ensure_cloudinary()

        folder = f"ai-wardrobe/{user_folder_key(user_email)}/{kind}"

        public_id = _unique_public_id(filename_hint)

        try:
            result = uploader.upload(
                io.BytesIO(image_bytes),
                folder=folder,
                public_id=public_id,
                resource_type="image",
                overwrite=False,
            )
        except Exception as error:
            raise StorageError(f"Could not upload the image: {error}")

        url = result.get("secure_url")

        if not url:
            raise StorageError(
                "Cloudinary accepted the upload but returned no secure_url."
            )

        return url, {
            "backend": "cloudinary",
            "public_id": result.get("public_id"),
            "local_path": None,
        }

    folder_name, folder_path = legacy_local_folder(user_email)

    if kind != "wardrobe":
        folder_path = os.path.join(folder_path, kind)
        folder_name = f"{folder_name}/{kind}"
        os.makedirs(folder_path, exist_ok=True)

    filename = secure_filename(_unique_public_id(filename_hint) + ".png")

    path = os.path.join(folder_path, filename)

    try:
        with open(path, "wb") as handle:
            handle.write(image_bytes)
    except Exception as error:
        raise StorageError(f"Could not save the image on this computer: {error}")

    return f"/api/uploads/{folder_name}/{filename}", {
        "backend": "local",
        "public_id": None,
        "local_path": path,
    }


def delete_image(details):
    """
    Removes an image this application stored. Best effort, returning
    (removed, detail) rather than raising.

    Best effort on purpose: this is called when a user deletes their
    own photo or try-on result, and the database record must be
    removed either way. A file that has already vanished, or a
    Cloudinary account that is briefly unreachable, must not leave the
    user unable to delete a picture of themselves - the worst outcome
    of a failure here is an orphaned file, and the worst outcome of
    raising would be a photo the user cannot get rid of.
    """
    details = details or {}

    public_id = details.get("public_id")

    if public_id:
        try:
            uploader = _ensure_cloudinary()
            uploader.destroy(public_id, resource_type="image")
            return True, "removed from Cloudinary"
        except Exception as error:
            return False, f"could not remove from Cloudinary: {type(error).__name__}"

    local_path = details.get("local_path")

    if local_path:
        try:
            os.remove(local_path)
            return True, "removed from this computer"
        except FileNotFoundError:
            return True, "already gone"
        except Exception as error:
            return False, f"could not remove the file: {type(error).__name__}"

    return False, "nothing recorded to remove"


def local_copy_of(url, cache_folder=None):
    """
    Downloads a remote image once and returns a local file path for it,
    caching the result.

    This exists for the AI code that has to READ pixel data
    (clothing_similarity.extract_feature opens a path on disk, not a
    URL). Before images moved to Cloudinary every wardrobe image was
    already on disk; afterwards, "find similar in my wardrobe" would
    quietly find nothing, because every item's path pointed at an https
    URL that does not exist as a file.

    The cache is keyed by a hash of the URL, so the same item is
    fetched once per machine and reused on every later comparison
    rather than re-downloaded for each search. Cache files live under
    backend/uploads/_remote_cache/ and are disposable: deleting them
    only costs one re-download.

    Returns None (never raises) if the image cannot be fetched - a
    comparison that has to skip one item is much better than a failed
    request for the whole search.
    """
    import urllib.request

    if not is_remote_url(url):
        return None

    folder = cache_folder or os.path.join(BASE_UPLOAD_FOLDER, "_remote_cache")

    os.makedirs(folder, exist_ok=True)

    extension = os.path.splitext(url.split("?")[0])[1][:5] or ".jpg"

    cached_path = os.path.join(
        folder,
        hashlib.sha256(url.encode("utf-8")).hexdigest()[:32] + extension,
    )

    if os.path.isfile(cached_path):
        return cached_path

    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            data = response.read()

        # Written to a temporary name first, then moved into place, so
        # an interrupted download can never leave a half-written file
        # that later looks like a valid cache hit.
        temporary_path = cached_path + ".part"

        with open(temporary_path, "wb") as handle:
            handle.write(data)

        os.replace(temporary_path, cached_path)

        return cached_path

    except Exception as error:
        print(f"Could not fetch remote image {url}: {error}")
        return None


def is_remote_url(value):
    """
    True for an image reference that already points at shared storage
    (any absolute http/https URL) rather than at this machine's disk.
    Used to decide whether an item still needs migrating, and by
    delete/cleanup code that must not try to unlink a URL.
    """
    return isinstance(value, str) and value.startswith(("http://", "https://"))
