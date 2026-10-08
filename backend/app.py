from backend.outfit_recommendation import recommend_outfits, effective_occasions, describe_missing_pieces, resolve_occasion_query
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    jwt_required,
    get_jwt_identity
)
from backend import email_service
from backend.auth import (
    register_user,
    verify_login,
    get_user_gender,
    migrate_user_gender,
    get_user_profile,
    update_user_profile,
    set_profile_picture,
    delete_user_account,
    create_password_reset_code,
    reset_password_with_code,
    RESET_CODE_MINUTES,
)
from backend.wardrobe import (
    add_item,
    get_user_wardrobe,
    delete_item,
    update_item,
    delete_all_for_user as delete_all_wardrobe_for_user,
)
from backend.category_gender import is_allowed_for_account
from backend import category_catalog
from backend import inspiration as inspiration_library
from backend.garment_taxonomy import model_may_override
# TensorFlow powers ONE feature - "find similar clothes" - and it is by
# far the heaviest and most fragile dependency in the project: a 280 MB
# wheel that does not build on every machine or Python version. Importing
# it at module level meant a laptop without it could not start the
# backend AT ALL: no login, no wardrobe, no uploads, no recommendations,
# no try-on, just a traceback. That is the wrong failure.
#
# So the import is guarded. With TensorFlow present nothing changes.
# Without it, everything else runs and /api/ai/similar alone reports
# that the feature is unavailable on this machine.
try:
    from backend.clothing_similarity import find_similar
    from backend.indofashion_similarity import find_similar_indofashion
    SIMILARITY_AVAILABLE = True
    SIMILARITY_UNAVAILABLE_REASON = ""
except Exception as _similarity_import_error:  # noqa: BLE001
    find_similar = None
    find_similar_indofashion = None
    SIMILARITY_AVAILABLE = False
    SIMILARITY_UNAVAILABLE_REASON = type(_similarity_import_error).__name__
    print(
        "Similar-clothes search is OFF on this machine "
        f"({SIMILARITY_UNAVAILABLE_REASON}: TensorFlow could not be "
        "imported). Everything else works. To enable it: "
        "pip install tensorflow"
    )
# Also TensorFlow-backed - see the note on the similarity imports above.
# Every call site already sits inside a try/except (the classifier is a
# suggestion, never a requirement), so a stand-in that raises keeps the
# behaviour on a machine without TensorFlow identical to the behaviour
# when the model file is missing: the user picks the category themselves.
try:
    from backend.indofashion_classifier import predict_category
except Exception as _classifier_import_error:  # noqa: BLE001
    _classifier_reason = type(_classifier_import_error).__name__

    def predict_category(*_args, **_kwargs):
        raise RuntimeError(
            "The IndoFashion classifier needs TensorFlow, which is not "
            f"installed on this computer ({_classifier_reason})."
        )
from backend.weather import get_weather, get_weather_forecast
from backend.trip_planner import plan_trip
from backend.trips import save_trip, get_user_trips, delete_all_for_user as delete_all_trips_for_user
from backend.color_detection import detect_dominant_color, detect_colors, detect_colors_from_pixels
from backend import image_pipeline
from backend.item_attributes import describe_item
from backend import config, storage
from backend.db import ping as ping_database, ensure_indexes
from backend.identity import normalize_email
from backend import outfit_feedback
from backend import garment_classifier
from backend import recommend_service
from backend import outfit_presentation
from backend import item_recommender
from backend import virtual_tryon, tryon_store, tryon_orchestrator
from backend import tryon_usage
from backend.outfit_builder import occasion_mode as outfit_builder_mode

import os
import uuid
import traceback
import io
import threading
from datetime import timedelta
import shutil
from werkzeug.utils import secure_filename


# =========================================================
# FLASK APP
# =========================================================

app = Flask(__name__)

CORS(app)

# Signing key for login tokens, read from this machine's .env (see
# config.py). It used to be a placeholder string committed in this
# file, which meant anyone with a copy of the repository could forge a
# login token for any account.
# config.validate() (already run when backend.db was imported above)
# refuses to start the app if it is missing, so this is never blank.
app.config["JWT_SECRET_KEY"] = config.JWT_SECRET_KEY

# A browser <img src="..."> cannot send an Authorization header, so a
# wardrobe image served from this machine's disk could not be
# protected by the header alone - which is why that route was open to
# anyone. Accepting the token from ?token= as well lets the image
# route check ownership like every other route. Headers stay first,
# so nothing else changes.
app.config["JWT_TOKEN_LOCATION"] = ["headers", "query_string"]
app.config["JWT_QUERY_STRING_NAME"] = "token"

# Login tokens used to expire after flask-jwt-extended's DEFAULT of 15
# minutes (nothing set it), so any upload or edit made more than 15
# minutes after logging in failed with a bare {"msg": "Token has
# expired"} - which the frontend could only show as "Upload failed.".
# Now configurable, 7 days by default (JWT_ACCESS_TOKEN_EXPIRES_SECONDS).
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(
    seconds=int(os.environ.get("JWT_ACCESS_TOKEN_EXPIRES_SECONDS", 7 * 24 * 3600))
)

jwt = JWTManager(app)


# Every auth failure answers in the same {"success", "message", "code"}
# shape as the rest of the API, so the frontend can say what happened
# ("your session expired") instead of a generic failure.
@jwt.expired_token_loader
def _expired_token(jwt_header, jwt_payload):
    return jsonify({"success": False, "code": "token_expired",
                    "message": "Your session has expired - please log in again."}), 401


@jwt.invalid_token_loader
def _invalid_token(reason):
    return jsonify({"success": False, "code": "token_invalid",
                    "message": "Your login is no longer valid - please log in again."}), 401


@jwt.unauthorized_loader
def _missing_token(reason):
    return jsonify({"success": False, "code": "token_missing",
                    "message": "Please log in first."}), 401


# One honest summary at startup of what this process is actually
# connected to - which database, which image storage - so a machine
# that is misconfigured says so in its own terminal instead of
# silently building up a second, separate copy of the data.
print(config.describe_startup())

for _warning in config.validate(strict=False):
    print(f"  WARNING: {_warning}")


# =========================================================
# ACCESSORY CATEGORIES
#
# The IndoFashion classifier only knows clothing classes -
# it has never seen a bag, watch, belt, or piece of jewelry.
# For these categories we always trust the manual category
# instead of running (and blindly trusting) AI detection.
# =========================================================

ACCESSORY_CATEGORIES = {
    "Bag",
    "Watch",
    "Belt",
    "Jewelry"
}


# =========================================================
# ETHNIC AUTO-DETECTION
#
# The IndoFashion classifier was trained on the 16 classes listed in
# dataset/indofashion/class_names.json - it can't be trusted on
# anything outside that list (a Western shirt, jacket, etc get
# force-fit into whatever ethnic class looks closest), so the raw
# prediction is only ever trusted when it lands on one of those 16
# trained classes, mapped here to the matching manual-dropdown
# label (see Wardrobe.js's ALL_CATEGORIES, which now exposes all of
# these as pickable categories too - not just Saree/Lehenga as
# before).
#
# Gender-gated in both directions (see account_gender check below):
# the AI is never allowed to silently promote an item into a
# category that's gendered opposite to the account's - a Male
# account's item never becomes a Saree/Lehenga/Blouse/etc, and a
# Female account's item never becomes a Sherwani/Dhoti Pants/etc,
# even on a confident prediction.
# =========================================================

ETHNIC_AUTO_CATEGORIES = {
    "blouse": "Blouse",
    "dhoti_pants": "Dhoti Pants",
    "dupattas": "Dupatta",
    "gowns": "Gown",
    "kurta_men": "Kurta (Men)",
    "leggings_and_salwars": "Leggings & Salwars",
    "lehenga": "Lehenga",
    "mojaris_men": "Mojaris (Men)",
    "mojaris_women": "Mojaris (Women)",
    "nehru_jackets": "Nehru Jacket",
    "palazzos": "Palazzos",
    "petticoats": "Petticoat",
    "saree": "Saree",
    "sherwanis": "Sherwani",
    "women_kurta": "Kurta (Women)"
    # "shirt" (the 16th class) is deliberately NOT in this map - a
    # confident "shirt" prediction never needs to override anything,
    # since Shirt is already the most common manual pick and is
    # unisex either way.
}

ETHNIC_DETECTION_CONFIDENCE_THRESHOLD = 0.5

# Labels the IndoFashion model gives WESTERN clothes it was never
# trained on (bootcut/skinny jeans -> leggings_and_salwars, crop top ->
# blouse, skirt -> petticoat). A photo of real leggings and a photo of
# jeans look alike to it, so these are never applied automatically -
# only offered as a suggestion the user can accept. The user's own
# category is kept.
UNRELIABLE_AUTO_LABELS = {"leggings_and_salwars", "blouse", "petticoats"}

# Below this, the garment classifier's best guess is still saved but
# the runner-up is offered to the user as a one-click correction.
GARMENT_CONFIDENCE_THRESHOLD = 0.45


# =========================================================
# UPLOAD FOLDER
#
# Still used for two things after the move to Cloudinary: it is where
# an uploaded file lands briefly so the AI modules (which read a
# filesystem path, not a URL) can analyse it, and it is where images
# uploaded BEFORE this change still live and are still served from.
# It is no longer where a wardrobe image permanently lives - see
# backend/storage.py.
# =========================================================

BASE_UPLOAD_FOLDER = storage.BASE_UPLOAD_FOLDER


# =========================================================
# USER WARDROBE FOLDER
# =========================================================

def get_user_folder(user_email):
    """
    This user's folder on THIS machine's disk. Kept (delegating to
    storage.py so there is one definition of the naming rule) because
    legacy images live under it, deleting an account must clean it up,
    and the AI step needs somewhere local to read the file from.
    """
    return storage.legacy_local_folder(user_email)


# =========================================================
# HEALTH CHECK
#
# Answers the question you actually have when something looks wrong:
# is the backend up, is it REACHING the shared database, and is it
# storing images somewhere both computers can see?
#
# Deliberately unauthenticated (it is the thing you call when you
# cannot log in) and therefore deliberately free of secrets: it
# reports the database NAME and HOST but never the connection string,
# and never any key, password or token. See config.safe_mongo_host().
# =========================================================

INDEX_PROBLEMS = None


@app.route("/api/health", methods=["GET"])
def health():

    database_ok, database_detail = ping_database()

    storage_backend = config.storage_backend()

    payload = {
        "status": "ok" if database_ok else "degraded",
        "backend": "ok",
        "database": {
            "connected": database_ok,
            "detail": database_detail,
            "name": config.MONGODB_DB_NAME,
            "host": config.safe_mongo_host(),
        },
        "storage": {
            "backend": storage_backend,
            # "shared" is the property that actually matters for
            # multi-device use: local storage works, but only on the
            # one machine holding the files.
            "shared_across_devices": storage_backend == "cloudinary",
        },
        "weather": {
            "configured": bool(config.OPENWEATHER_API_KEY),
        },
        # Problems creating the uniqueness indexes (None = not checked
        # yet in this process, [] = all in place). Never contains data.
        "indexes": INDEX_PROBLEMS,
    }

    # 503 when the database is unreachable so uptime checks and
    # scripts can rely on the status code alone, not just the body.
    return jsonify(payload), (200 if database_ok else 503)


# =========================================================
# WHO IS CALLING
#
# The login token's identity is the account's canonical (normalised)
# email - see verify_login(). Normalising again here also covers
# tokens issued before normalisation existed (e.g. one minted for
# "Ganga@Gmail.com"), so a still-valid old token keeps working and
# still resolves to the ONE account's wardrobe instead of an empty one.
# =========================================================

def current_user_email():
    return normalize_email(get_jwt_identity())


# =========================================================
# REGISTER
# =========================================================

@app.route("/api/register", methods=["POST"])
def register():

    data = request.json

    name = (data.get("name") or "").strip()
    email = normalize_email(data.get("email"))
    password = data.get("password")
    # Gender is MANDATORY now - never trust a value from the client
    # beyond reading it here; register_user() is the actual gate
    # that rejects anything that isn't exactly "Male" or "Female".
    gender = data.get("gender")

    if not name or not email or not password:

        return jsonify({
            "success": False,
            "message": "All fields required"
        }), 400

    result = register_user(
        name,
        email,
        password,
        gender
    )

    # A welcome message, sent on a BACKGROUND thread so the browser
    # gets its response immediately and a slow or broken mail server
    # can never turn a successful registration into a failed one.
    # Silently does nothing when SMTP is not configured.
    if result["success"] and config.SEND_WELCOME_EMAIL:
        email_service.send_welcome_email(name, email)

    status_code = (
        200
        if result["success"]
        else 400
    )

    return jsonify(result), status_code


# =========================================================
# LOGIN
# =========================================================

@app.route("/api/login", methods=["POST"])
def login():

    data = request.json or {}

    email = normalize_email(data.get("email"))
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({
            "success": False,
            "message": "Enter your email and password"
        }), 400

    result = verify_login(
        email,
        password
    )

    if result["success"]:

        # The ACCOUNT's canonical email, not the string as typed - so
        # the same account gets the same identity (and so the same
        # wardrobe) on every device, however the address was typed.
        token = create_access_token(
            identity=result["email"]
        )

        result["token"] = token

        # "Welcome back" - sent only on a SUCCESSFUL login, and only
        # to the address stored on the account, so a failed guess at
        # someone else's email can never trigger mail to them. Same
        # background thread and same silence-when-unconfigured as
        # registration above.
        if config.SEND_LOGIN_EMAIL:
            email_service.send_signin_email(
                result.get("name"), result.get("email") or email
            )

        return jsonify(result), 200

    else:

        return jsonify(result), 401


# =========================================================
# FORGOT PASSWORD
# =========================================================

@app.route("/api/password/forgot", methods=["POST"])
def forgot_password():
    data = request.json or {}
    email = normalize_email(data.get("email"))

    if not email:
        return jsonify({"success": False, "message": "Enter your email address"}), 400

    if not config.email_configured():
        return jsonify({
            "success": False,
            "message": "Password reset by email isn't set up on the server yet."
        }), 503

    result = create_password_reset_code(email)
    if result["status"] == "ok":
        email_service.send_password_reset_code(
            result.get("name"), email, result["code"], RESET_CODE_MINUTES
        )

    # Same answer whether or not the account exists.
    return jsonify({
        "success": True,
        "message": "If an account exists for this email, a 6-digit code has been sent. "
                   "Check your inbox (and spam)."
    }), 200


@app.route("/api/password/reset", methods=["POST"])
def reset_password():
    data = request.json or {}
    email = normalize_email(data.get("email"))
    code = (data.get("code") or "").strip()
    new_password = data.get("new_password") or ""

    if not email or not code:
        return jsonify({"success": False, "message": "Email and code are required"}), 400

    result = reset_password_with_code(email, code, new_password)
    return jsonify(result), (200 if result["success"] else 400)


# =========================================================
# ONE-TIME GENDER MIGRATION
#
# For accounts created before gender was mandatory. Requires a
# valid JWT (so this can only be called by the account itself, never
# by guessing an email) and only ever succeeds ONCE - see
# migrate_user_gender() in auth.py, which refuses outright if the
# account already has a gender on file. This is the ONLY route in
# the app that can ever write to a user's "gender" field after
# registration, and it can only move an account from "unset" to
# "set" - never change an existing value.
# =========================================================

@app.route("/api/user/gender/migrate", methods=["POST"])
@jwt_required()
def migrate_gender():

    user_email = current_user_email()

    data = request.json or {}

    gender = data.get("gender")

    result = migrate_user_gender(user_email, gender)

    status_code = 200 if result["success"] else 400

    return jsonify(result), status_code


# =========================================================
# DASHBOARD
# =========================================================

@app.route("/api/dashboard", methods=["GET"])
@jwt_required()
def dashboard():

    caller_email = current_user_email()

    return jsonify({
        "message": f"Welcome, {caller_email}"
    }), 200


# =========================================================
# ADD WARDROBE ITEM
# =========================================================

@app.route("/api/wardrobe/categories", methods=["GET"])
@jwt_required()
def wardrobe_categories():
    """The category list for THIS account's saved gender (one catalogue)."""
    gender = category_catalog.normalize_gender(get_user_gender(current_user_email()))
    if not gender:
        return jsonify({
            "success": False,
            "message": "Your account has no gender set - choose Men or Women in Profile.",
        }), 409
    return jsonify({
        "success": True,
        "gender": gender,
        "sections": category_catalog.categories_for(gender),
    }), 200


# =========================================================
# STYLE INSPIRATION - reference pictures for the chosen occasion,
# for the account's own gender only. Pictures only: no source links,
# and never mixed into the user's outfits.
# =========================================================

@app.route("/api/inspiration", methods=["GET"])
@jwt_required()
def style_inspiration():
    gender = category_catalog.normalize_gender(get_user_gender(current_user_email()))
    occasion = resolve_occasion_query(request.args.get("occasion", "casual"))
    images = inspiration_library.for_account(gender, occasion)
    return jsonify({
        "success": True,
        "occasion": occasion,
        "label": outfit_presentation.occasion_label(occasion),
        "images": images,
    }), 200


@app.route("/api/inspiration/image/<image_id>", methods=["GET"])
@jwt_required()
def inspiration_image(image_id):
    gender = category_catalog.normalize_gender(get_user_gender(current_user_email()))
    path = inspiration_library.local_file(image_id, gender)
    if not path:
        return jsonify({"success": False, "message": "Not found"}), 404
    return send_from_directory(os.path.dirname(path), os.path.basename(path))


@app.route("/api/wardrobe/capabilities", methods=["GET"])
@jwt_required()
def wardrobe_capabilities():
    """
    Tells the Add Item form what the AI can do on THIS machine, so it
    never offers "Auto-detect" when the western + ethnic classifier has
    not been trained yet (the older model only knows Indian ethnic wear).
    """
    return jsonify({
        "success": True,
        "auto_category": garment_classifier.is_available(),
        "auto_colour": True,
        "storage": config.storage_backend(),
    }), 200


ALLOWED_IMAGE_TYPES = {"jpeg", "png", "webp", "gif", "bmp", "mpo"}
MAX_UPLOAD_BYTES = 15 * 1024 * 1024


def validate_upload_image(file_storage):
    """
    Returns (ok, message). Checks the upload really is a readable image
    BEFORE anything is saved or sent to Cloudinary.
    """
    from PIL import Image, UnidentifiedImageError

    if file_storage is None:
        return False, "No image was attached - please choose a photo."
    data = file_storage.read()
    file_storage.stream.seek(0)
    if not data:
        return False, "The image file is empty - please choose another photo."
    if len(data) > MAX_UPLOAD_BYTES:
        return False, "That image is too large (over 15 MB) - please crop it or choose a smaller one."
    try:
        import io
        with Image.open(io.BytesIO(data)) as img:
            img.verify()
            fmt = (img.format or "").lower()
    except (UnidentifiedImageError, OSError, ValueError):
        return False, "That file isn't an image we can read (use JPG, PNG or WEBP)."
    if fmt not in ALLOWED_IMAGE_TYPES:
        return False, f"{fmt.upper() or 'This'} images aren't supported - please use JPG, PNG or WEBP."
    return True, "ok"


def safe_upload_filename(original_name):
    """
    Always a non-empty, unique file name. secure_filename() returns ""
    for names made only of non-Latin characters, which used to make the
    upload try to save onto the user's FOLDER and crash; two photos both
    called "image.jpg" also overwrote each other.
    """
    name = secure_filename(original_name or "") or "item.jpg"
    stem, ext = os.path.splitext(name)
    return f"{uuid.uuid4().hex[:10]}_{stem[:40] or 'item'}{ext.lower() or '.jpg'}"


@app.route("/api/wardrobe/add", methods=["POST"])
@jwt_required()
def add_wardrobe_item():
    try:
        return _add_wardrobe_item()
    except Exception as error:  # noqa: BLE001 - always answer in JSON
        print("Upload crashed:\n" + traceback.format_exc())
        return jsonify({
            "success": False,
            "message": "Upload failed: the server hit an error while saving this "
                       f"item ({type(error).__name__}). Details are in the backend terminal.",
        }), 500


def _add_wardrobe_item():

    user_email = current_user_email()

    # Used below to keep the AI's saree/lehenga auto-detection from
    # overriding a Male account's category - see get_user_gender().
    account_gender = get_user_gender(user_email)

    # The account's saved gender (Atlas, never the browser) decides
    # which categories exist for this wardrobe.
    if not category_catalog.normalize_gender(account_gender):
        return jsonify({
            "success": False,
            "message": "Please set your account to Men or Women in Profile before adding clothes.",
        }), 409

    manual_category = request.form.get("category")

    # Did the user actually PICK this category, or is it just the
    # dropdown's default sitting there untouched?
    #
    # This distinction decides whether the model is allowed to
    # overrule it. Someone uploading twenty sarees without touching
    # the selector wants the AI to name them - refusing there would
    # make the app's best feature useless. Someone who deliberately
    # chose "Jeans" has told us something the model cannot know, and
    # overwriting that is what produced "my jeans became leggings".
    #
    # Sent by Wardrobe.js, which knows whether the select was
    # interacted with. Absent (an older frontend, or a direct API
    # call) is treated as "not explicitly chosen", preserving the
    # previous behaviour rather than silently tightening it.
    category_explicitly_chosen = (
        request.form.get("category_explicit", "").strip().lower() == "true"
    )

    # Occasion is now an OPTIONAL manual override, not something the
    # user has to pick when uploading - the whole point of this app
    # is that the detected category (below) already implies which
    # occasions the item fits, automatically. See
    # backend.outfit_recommendation.effective_occasions().
    occasion = request.form.get(
        "occasion",
        ""
    ).strip()

    image = request.files.get("image")

    # -----------------------------------------------------
    # Validate image
    # -----------------------------------------------------

    ok, problem = validate_upload_image(image)
    if not ok:
        return jsonify({"success": False, "message": problem}), 400

    folder_name, folder_path = get_user_folder(user_email)
    os.makedirs(folder_path, exist_ok=True)

    filename = safe_upload_filename(image.filename)
    path = os.path.join(folder_path, filename)
    image.save(path)

    # -----------------------------------------------------
    # Clean the photo: garment only, on white (image_pipeline).
    # Everything after this - classifier, colour, storage - works on
    # the processed image. The untouched original is kept alongside.
    # -----------------------------------------------------
    original_path = path
    garment_px = None
    processing = {"background_removed": False, "engine": None, "warnings": []}
    try:
        cleaned = image_pipeline.process_clothing_photo(path)
    except image_pipeline.ImageRejected as error:
        return jsonify({"success": False, "message": str(error)}), 400
    except Exception as error:  # never block an upload on this step
        print(f"Background removal failed for {filename}: {error}")
        cleaned = None
    if cleaned is not None:
        processed_name = os.path.splitext(filename)[0] + "_clean.jpg"
        processed_path = os.path.join(folder_path, processed_name)
        cleaned["image"].save(processed_path, "JPEG", quality=92)
        path, filename = processed_path, processed_name
        processing = {
            "background_removed": cleaned["background_removed"],
            "engine": cleaned["engine"],
            "warnings": cleaned["warnings"],
        }
        if cleaned["background_removed"]:
            garment_px = image_pipeline.garment_pixels(cleaned["image"], cleaned["mask"])
        print(f"Image cleaned for {filename}: {processing}")

    # The permanent (cloud) upload now happens AFTER category and
    # colour are settled - previously a photo was pushed to Cloudinary
    # first and then left there orphaned whenever the item was rejected.


    # AUTOMATIC CATEGORY DETECTION
    #
    # Skipped entirely for accessories - the classifier has
    # no accessory classes, so it would just force a bogus
    # clothing label onto a bag/watch/belt/jewelry photo.
    #
    # For everything else, the raw prediction is only trusted
    # when it confidently lands on saree or lehenga - the two
    # ethnic categories Wardrobe-AI still auto-detects. Any other
    # prediction (the model guessing a Western shirt is some kind
    # of kurta, for instance) is discarded and the user's manual
    # category is used instead.
    #
    # Also gated on account_gender via is_allowed_for_account(),
    # which blocks in BOTH directions: a confident prediction is
    # discarded whenever the predicted category is gendered opposite
    # to the account's (Male account -> Saree/Lehenga/Blouse/etc
    # blocked; Female account -> Sherwani/Dhoti Pants/etc blocked).
    # A unisex prediction (e.g. "shirt", not in ETHNIC_AUTO_CATEGORIES
    # anyway) or an account with no gender set is never blocked.
    # -----------------------------------------------------

    detected_category = None
    category_confidence = None

    # A prediction the model is NOT entitled to apply on its own (see
    # garment_taxonomy.model_may_override) - offered back to the user
    # to confirm or reject instead of being written over their choice.
    suggested_category = None
    suggestion_confidence = None
    suggestion_reason = None

    # -----------------------------------------------------
    # NEW: western + ethnic garment classifier (see
    # garment_classifier.py). Used whenever the user did NOT pick a
    # category themselves - which is now the default ("Auto-detect").
    # It knows jeans, t-shirts, tops, dresses... as well as sarees,
    # lehengas and kurtas, so it replaces the ethnic-only model below.
    # -----------------------------------------------------
    user_picked = bool(manual_category) and category_explicitly_chosen

    if not user_picked and garment_classifier.is_available():

        try:
            prediction = garment_classifier.predict(path, account_gender)
        except Exception as e:
            prediction = None
            print(f"Garment classifier failed for {filename}: {e}")

        if prediction:
            print(
                f"Garment classifier: {filename} -> {prediction['category']} "
                f"({prediction['confidence']:.2f}); top: {prediction['top']}"
            )
            # The model decides only when its class means exactly one
            # category for this gender and it is reliable and confident
            # (category_catalog.classifier_decision). Otherwise the user
            # picks from that family - nothing is saved yet.
            decision = category_catalog.classifier_decision(
                prediction, account_gender, GARMENT_CONFIDENCE_THRESHOLD
            )
            if decision.get("category"):
                detected_category = decision["category"]
                category_confidence = prediction["confidence"]
            else:
                return jsonify({
                    "success": False,
                    "needs_category": True,
                    "message": decision["reason"] + ".",
                    "options": decision["choose"],
                    "guess": decision["guess"],
                }), 422

    if (
        detected_category is None
        and not garment_classifier.is_available()
        and manual_category not in ACCESSORY_CATEGORIES
    ):

        try:

            category_result = predict_category(path)

            raw_category = category_result["category"].lower().strip()
            raw_confidence = category_result["confidence"]

            print(
                f"Raw model prediction for {filename}: "
                f"{raw_category} "
                f"(confidence: {raw_confidence:.2f})"
            )

            candidate_label = ETHNIC_AUTO_CATEGORIES.get(raw_category)

            confident = raw_confidence >= ETHNIC_DETECTION_CONFIDENCE_THRESHOLD

            gender_ok = candidate_label and is_allowed_for_account(
                candidate_label, account_gender
            )

            if candidate_label and confident and gender_ok:

                # The model has never seen a pair of jeans, a skirt or
                # a crop top - it only knows its 15 ethnic classes, so
                # for anything else it returns the nearest one of
                # those (jeans -> leggings_and_salwars, skirt ->
                # petticoat, crop top -> blouse). Letting that
                # overwrite the user's own choice is what made the app
                # rename people's clothes. It may refine within a
                # family; across families it can only suggest.
                allowed, reason = model_may_override(
                    manual_category if category_explicitly_chosen else None,
                    candidate_label,
                )

                if allowed and raw_category in UNRELIABLE_AUTO_LABELS:
                    allowed = False
                    reason = (
                        "the model often gives this label to western "
                        "clothes (jeans, crop tops, skirts), so it is only "
                        "a suggestion"
                    )

                if allowed:

                    detected_category = candidate_label
                    category_confidence = raw_confidence

                    print(
                        f"Auto-detected category for {filename}: "
                        f"{detected_category} "
                        f"(confidence: {category_confidence:.2f}) - {reason}"
                    )

                else:

                    suggested_category = candidate_label
                    suggestion_confidence = raw_confidence
                    suggestion_reason = reason

                    print(
                        f"Model suggested {candidate_label} for {filename} "
                        f"(confidence: {raw_confidence:.2f}) but kept the "
                        f"user's '{manual_category}': {reason}"
                    )

        except Exception as e:

            print(
                f"Category detection failed for "
                f"{filename}: {e}"
            )


    # -----------------------------------------------------
    # Color - manual entry always wins when provided. When the
    # user leaves it blank, the color is auto-detected from the
    # photo itself instead of blocking the upload (see
    # backend.color_detection.detect_dominant_color). This never
    # overrides a color the user actually typed - it only fills in
    # the gap when they didn't.
    # -----------------------------------------------------

    manual_color = request.form.get("color", "").strip()

    color_auto_detected = False

    # One analysis pass gives the dominant colour AND any secondary
    # colours/pattern (see color_detection.detect_colors). The stored
    # "color" field keeps exactly its old meaning - a single name that
    # colour-harmony scoring understands - while the richer reading
    # travels alongside it.
    # With the background removed, only the garment's own pixels are
    # used - the white canvas can't be mistaken for part of the item.
    color_analysis = (
        detect_colors_from_pixels(garment_px) if garment_px else detect_colors(path)
    )

    if manual_color:
        final_color = manual_color
    else:
        detected = (color_analysis or {}).get("primary")

        if detected:
            final_color = detected
            color_auto_detected = True
        else:
            final_color = ""

    if not final_color:
        return jsonify({
            "success": False,
            "message":
                "Couldn't detect a colour from this photo - please "
                "type the colour and upload again."
        }), 400

    # -----------------------------------------------------
    # Optional accessory material (e.g. leather, gold, metal)
    # -----------------------------------------------------

    material = request.form.get("material", "").strip()

    # -----------------------------------------------------
    # Optional manual "styling" tag (Casual vs Wedding/Festive) -
    # only meaningful for Saree/Lehenga/Kurta-type items, see
    # Wardrobe.js STYLING_CATEGORIES and wardrobe.add_item().
    # -----------------------------------------------------

    styling = request.form.get("styling", "").strip()

    # -----------------------------------------------------
    # Choose category
    #
    # Automatic detection gets priority for clothing.
    # Manual category is always used for accessories, and
    # is the fallback if clothing detection fails.
    # -----------------------------------------------------

    final_category = (
        detected_category
        if detected_category
        else manual_category
    )

    if not final_category:
        return jsonify({
            "success": False,
            "message":
                "Couldn't recognise this item automatically - please "
                "choose its category from the list and upload again."
        }), 400

    # HARD RULE: the category must belong to this account's gender
    # (backend/category_catalog.py). Never saved otherwise.
    if not category_catalog.is_valid_for(final_category, account_gender):
        wardrobe_word = "men's" if category_catalog.normalize_gender(account_gender) == "male" else "women's"
        return jsonify({
            "success": False,
            "message": f"\"{final_category}\" isn't one of the {wardrobe_word} wardrobe categories - "
                       "please choose a category from the list.",
        }), 400
    final_category = category_catalog.canonical_for_gender(final_category, account_gender)
    if suggested_category and category_catalog.is_valid_for(suggested_category, account_gender):
        suggested_category = category_catalog.canonical_for_gender(suggested_category, account_gender)
        if suggested_category == final_category:
            suggested_category = None
    else:
        suggested_category = None
    # -----------------------------------------------------
    # Store wardrobe item
    # -----------------------------------------------------

    # The structured description of this item (role, style, season and
    # weather suitability, colours, pattern). Everything in it is
    # either the user's own input, measured from the photo, or true of
    # the category by definition - see item_attributes for what is
    # deliberately left blank rather than guessed.
    if config.storage_backend() == "cloudinary":
        try:
            image_url = storage.upload_local_file(path, user_email, kind="wardrobe")
        except storage.StorageError as error:
            print(f"Image upload failed for {filename}: {error}")
            # The real reason (e.g. "File size too large", "Invalid
            # Signature", a network error) is shown instead of a generic
            # "Upload failed", with anything that looks like a key or id
            # masked. Nothing is saved to Atlas when this happens.
            import re as _re
            reason = _re.sub(r"[A-Za-z0-9]{12,}", "***", str(error).split(" to Cloudinary: ")[-1])[:160]
            return jsonify({
                "success": False,
                "message": "Upload failed: the image could not be stored in the "
                           f"cloud (Cloudinary said: {reason}). Nothing was saved - please try again.",
            }), 502
        # The untouched original is kept too (so a bad cut-out can be
        # undone later). Optional and never fatal.
        original_url = None
        if original_path != path and os.environ.get("KEEP_ORIGINAL_PHOTOS", "true").lower() != "false":
            try:
                original_url = storage.upload_local_file(original_path, user_email, kind="originals")
            except storage.StorageError as error:
                print(f"Original photo not kept for {filename}: {error}")
    else:
        # Only when Cloudinary is not configured at all (config.py
        # already warns at startup that images then stay on this Mac).
        image_url = f"/api/uploads/{folder_name}/{filename}"
        original_url = (
            f"/api/uploads/{folder_name}/{os.path.basename(original_path)}"
            if original_path != path else None
        )

    attributes = describe_item(
        final_category,
        colors=color_analysis,
        styling=styling,
        material=material,
        manual_occasion=occasion,
    )
    if isinstance(attributes, dict):
        attributes["image_processing"] = dict(processing, original_image=original_url)

    item_id = add_item(
        user_email,
        final_category,
        final_color,
        image_url,
        occasion,
        material,
        styling,
        attributes,
        gender=category_catalog.normalize_gender(account_gender),
    )


    # -----------------------------------------------------
    # Response
    # -----------------------------------------------------

    return jsonify({

        "success": True,

        "item_id": item_id,

        "category": final_category,

        "color": final_color,

        "color_auto_detected": color_auto_detected,

        "occasion": occasion,

        # What occasion(s) this item is ACTUALLY eligible for, worked
        # out automatically from final_category (plus the manual
        # override above, if any) - this is what the frontend shows
        # right after upload so the user can see what got detected
        # without having picked anything themselves.
        "suitable_occasions": sorted(
            effective_occasions(final_category, occasion)
        ),

        "material": material,

        "styling": styling,

        "image": image_url,

        # Background removal outcome, shown after upload.
        "background_removed": processing["background_removed"],

        "image_warnings": processing["warnings"],

        # What the model thought, when it was not entitled to act on
        # it by itself. The frontend shows this as "the AI thinks this
        # might be X - keep yours, or switch?" so a genuinely useful
        # correction is one click away, while a wrong guess costs the
        # user nothing. Absent when the model agreed, stayed quiet, or
        # was allowed to decide.
        "suggested_category": suggested_category,

        "suggestion_confidence": (
            round(suggestion_confidence, 2)
            if suggestion_confidence is not None else None
        ),

        "suggestion_reason": suggestion_reason,

        "needs_confirmation": bool(suggested_category),

        # What was detected about this item, for the upload
        # confirmation view. Null/empty fields mean "we could not
        # tell", never "none" - see item_attributes.
        "attributes": attributes,

        # How confident the model was in a category it DID apply -
        # surfaced so the UI can be honest about an uncertain
        # auto-detection rather than presenting every one as fact.
        "category_confidence": (
            round(category_confidence, 2)
            if category_confidence is not None else None
        )

    }), 200


# =========================================================
# SERVE USER WARDROBE IMAGE
#
# Only for images stored on THIS machine - anything uploaded since
# images moved to Cloudinary is served from there instead.
#
# This route used to be completely open, which was a real hole: the
# folder name is derived from the email ("ganga@gmail.com" ->
# "ganga_digital_wardrobe"), so anyone who could guess an email could
# read that person's wardrobe photos without logging in. Every other
# route took its user from the token; this one took a folder name
# from the URL and trusted it.
#
# It now requires a valid token and checks the folder belongs to the
# caller. Since an <img> tag cannot send an Authorization header, the
# token may also arrive as ?token= (see JWT_TOKEN_LOCATION above);
# the frontend's assetUrl() appends it.
# =========================================================

@app.route(
    "/api/uploads/<folder_name>/<filename>"
)
@jwt_required()
def serve_image(
    folder_name,
    filename
):

    user_email = current_user_email()

    own_folder, _ = get_user_folder(user_email)

    # A subfolder (profile pictures live under "<folder>/profile") is
    # still this user's, so the check is a prefix match rather than
    # equality - but only on a path separator, so "ganga_x" can never
    # pass as a prefix of "ganga_x_other".
    if folder_name != own_folder and not folder_name.startswith(own_folder + "/"):

        return jsonify({
            "success": False,
            "message": "Not found"
        }), 404

    # Defence in depth: a folder name containing ".." or a separator
    # could otherwise walk out of the uploads directory entirely. The
    # ownership check above already blocks this, but a traversal
    # attempt should never depend on one check alone.
    if ".." in folder_name or folder_name.startswith("/"):

        return jsonify({
            "success": False,
            "message": "Not found"
        }), 404

    return send_from_directory(
        os.path.join(
            BASE_UPLOAD_FOLDER,
            folder_name
        ),
        filename
    )


# =========================================================
# VIEW USER WARDROBE
# =========================================================

@app.route(
    "/api/wardrobe",
    methods=["GET"]
)
@jwt_required()
def view_wardrobe():

    user_email = current_user_email()

    items = get_user_wardrobe(
        user_email
    )

    # Attach each item's automatically-inferred occasion eligibility
    # so the wardrobe grid can show it without the frontend needing
    # to duplicate any of this logic itself.
    for item in items:
        item["suitable_occasions"] = sorted(
            effective_occasions(item.get("category"), item.get("occasion"))
        )

    # Display name ("Black Bootcut Jeans"), wardrobe tab (Tops,
    # Bottoms, Sarees...) and style label for the redesigned grid.
    items = [outfit_presentation.present_item(item) for item in items]

    return jsonify({
        "success": True,
        "items": items
    }), 200


# =========================================================
# DELETE WARDROBE ITEM
# =========================================================

@app.route(
    "/api/wardrobe/<item_id>",
    methods=["DELETE"]
)
@jwt_required()
def remove_wardrobe_item(item_id):

    user_email = current_user_email()

    # delete_item now checks ownership itself (see wardrobe.py) -
    # previously this matched on _id alone, which meant any
    # logged-in user could delete ANY other user's item just by
    # guessing/enumerating an item_id.
    deleted = delete_item(item_id, user_email)

    if not deleted:
        return jsonify({
            "success": False,
            "message": "Item not found or not yours"
        }), 404

    return jsonify({
        "success": True
    }), 200


# =========================================================
# UPDATE WARDROBE ITEM
# =========================================================

@app.route(
    "/api/wardrobe/<item_id>",
    methods=["PUT"]
)
@jwt_required()
def update_wardrobe_item(item_id):

    user_email = current_user_email()

    data = request.json or {}

    # Editing a category is held to the same rule as uploading one.
    new_category = (data.get("category") or "").strip()
    if new_category:
        account_gender = get_user_gender(user_email)
        if not category_catalog.is_valid_for(new_category, account_gender):
            return jsonify({
                "success": False,
                "message": f"\"{new_category}\" isn't a category for this wardrobe.",
            }), 400
        data = dict(data, category=category_catalog.canonical_for_gender(new_category, account_gender))

    updated = update_item(
        item_id,
        user_email,
        {
            "category": data.get("category"),
            "color": data.get("color"),
            "occasion": data.get("occasion"),
            "material": data.get("material"),
            "favorite": data.get("favorite"),
            "styling": data.get("styling")
        }
    )

    if not updated:

        return jsonify({
            "success": False,
            "message": "Item not found, not yours, or nothing to update"
        }), 404

    return jsonify({
        "success": True
    }), 200


# =========================================================
# AI SIMILARITY SEARCH
# =========================================================

@app.route(
    "/api/ai/similar",
    methods=["POST"]
)
@jwt_required()
def find_similar_clothes():
    """
    Find Similar = two answers for one photo:

      1. wardrobe_results - pieces the user ALREADY owns that look like
         it (needs TensorFlow; skipped quietly on a machine without it).
      2. shopping - live store links (Myntra, AJIO, Amazon, Flipkart,
         Meesho, Google Shopping, plus Google Lens by picture) built
         from the detected category/colour and the account's gender.
         Plain URLs, so they work on every account and every device.

    The old DeepFashion / IndoFashion picture grids are gone: those
    images exist only in dataset/ on one laptop, so they showed as
    broken images everywhere else. dataset_results / indofashion_results
    are still returned (empty) so an older frontend doesn't crash.
    """
    from backend import shopping_links

    user_email = current_user_email()
    account_gender = get_user_gender(user_email)

    image = request.files.get("image")
    if not image:
        return jsonify({"success": False, "message": "No image provided"}), 400

    temp_folder = os.path.join(BASE_UPLOAD_FOLDER, "ai_queries")
    os.makedirs(temp_folder, exist_ok=True)
    filename = f"{uuid.uuid4().hex}_{secure_filename(image.filename) or 'query.jpg'}"
    image_path = os.path.join(temp_folder, filename)
    image.save(image_path)

    warnings = []
    try:
        # ---- Clean the photo (same pipeline as uploads) ------------
        analysis_path = image_path
        garment_px = None
        try:
            cleaned = image_pipeline.process_clothing_photo(image_path)
            if cleaned is not None:
                analysis_path = os.path.splitext(image_path)[0] + "_clean.jpg"
                cleaned["image"].save(analysis_path, "JPEG", quality=90)
                if cleaned["background_removed"]:
                    garment_px = image_pipeline.garment_pixels(cleaned["image"], cleaned["mask"])
        except image_pipeline.ImageRejected as error:
            return jsonify({"success": False, "message": str(error)}), 400
        except Exception as error:  # noqa: BLE001 - never block the search
            print(f"Similar search: photo cleaning skipped ({error})")

        # ---- What is it? -------------------------------------------
        detected_category = None
        category_confidence = None
        if garment_classifier.is_available():
            try:
                prediction = garment_classifier.predict(analysis_path, account_gender)
                if prediction:
                    decision = category_catalog.classifier_decision(
                        prediction, account_gender, GARMENT_CONFIDENCE_THRESHOLD
                    )
                    detected_category = decision.get("category") or decision.get("guess")
                    category_confidence = prediction.get("confidence")
            except Exception as error:  # noqa: BLE001
                print(f"Similar search: classifier skipped ({error})")
        if not detected_category:
            warnings.append("category_unknown")

        # ---- Which colour? -----------------------------------------
        color_analysis = None
        try:
            color_analysis = (
                detect_colors_from_pixels(garment_px) if garment_px
                else detect_colors(analysis_path)
            )
        except Exception as error:  # noqa: BLE001
            print(f"Similar search: colour skipped ({error})")
        from backend.color_detection import display_name as color_display_name
        detected_color = color_display_name((color_analysis or {}).get("primary")) or None
        patterned = bool((color_analysis or {}).get("is_patterned"))

        # ---- Public copy of the photo for Google Lens --------------
        public_image_url = None
        if config.storage_backend() == "cloudinary":
            try:
                public_image_url = storage.upload_local_file(
                    analysis_path, user_email, kind="shop_queries"
                )
            except Exception as error:  # noqa: BLE001
                print(f"Similar search: Lens upload skipped ({error})")

        shopping = shopping_links.shopping_payload(
            category=detected_category,
            color=detected_color,
            gender=account_gender,
            patterned=patterned,
            image_url=public_image_url,
        )
        shopping["category_confidence"] = category_confidence

        # ---- Already in your wardrobe? -----------------------------
        wardrobe_results = []
        if SIMILARITY_AVAILABLE:
            try:
                from backend.clothing_similarity import find_similar_in_wardrobe
                # Both the photo as uploaded and its cleaned version:
                # an item re-uploaded from the wardrobe then matches
                # whichever form was stored, and comes back as 100%.
                query_versions = [image_path]
                if analysis_path != image_path:
                    query_versions.append(analysis_path)
                wardrobe_results = find_similar_in_wardrobe(
                    query_versions, get_user_wardrobe(user_email), top_k=5
                )
            except Exception as error:  # noqa: BLE001
                print(f"Similar search: wardrobe match skipped ({error})")
                warnings.append("wardrobe_match_failed")
        else:
            warnings.append("wardrobe_match_unavailable")

        return jsonify({
            "success": True,
            "wardrobe_results": wardrobe_results,
            "shopping": shopping,
            "warnings": warnings,
            # kept for older frontends - always empty now (see docstring)
            "dataset_results": [],
            "indofashion_results": [],
            "category_results": {
                "category": detected_category,
                "confidence": category_confidence,
            },
        }), 200

    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        return jsonify({"success": False, "message": f"Search failed: {e}"}), 500

    finally:
        for path in {image_path, os.path.splitext(image_path)[0] + "_clean.jpg"}:
            try:
                os.remove(path)
            except OSError:
                pass


@app.route(
    "/api/shop/links",
    methods=["GET"]
)
@jwt_required()
def shop_links_for_query():
    """
    Re-builds the store links when the user corrects the category or
    colour, or types their own search - no photo upload needed.
    Query params: q (free text, wins if given), category, color.
    """
    from backend import shopping_links

    account_gender = get_user_gender(current_user_email())
    payload = shopping_links.shopping_payload(
        category=request.args.get("category") or None,
        color=request.args.get("color") or None,
        gender=account_gender,
        patterned=request.args.get("printed") in ("1", "true", "yes"),
        image_url=request.args.get("image_url") or None,
        query=request.args.get("q") or None,
        min_price=request.args.get("min_price") or None,
        max_price=request.args.get("max_price") or None,
    )
    return jsonify({"success": True, "shopping": payload}), 200


# =========================================================
# DEEPFASHION IMAGE SERVING
# =========================================================

DATASET_FOLDER = os.path.join(
    os.path.dirname(
        os.path.abspath(__file__)
    ),
    "..",
    "dataset",
    "deepfashion"
)


@app.route(
    "/api/dataset/<path:filename>"
)
def serve_dataset_image(filename):

    return send_from_directory(
        DATASET_FOLDER,
        filename
    )


# =========================================================
# INDOFASHION IMAGE SERVING
# =========================================================

INDOFASHION_FOLDER = os.path.join(
    os.path.dirname(
        os.path.abspath(__file__)
    ),
    "..",
    "dataset",
    "indofashion",
    "processed"
)


@app.route(
    "/api/indofashion/<path:filename>"
)
def serve_indofashion_image(filename):

    return send_from_directory(
        INDOFASHION_FOLDER,
        filename
    )


# =========================================================
# STYLE & TRENDS (Outfit Studio) + OUTFIT CALENDAR - see style_routes.py
# =========================================================
from backend.style_routes import style_bp  # noqa: E402
from backend.style_studio import saved as _saved_looks  # noqa: E402

app.register_blueprint(style_bp)


# =========================================================
# RUN FLASK
# =========================================================
# =========================================================
# OUTFIT RECOMMENDATION
# =========================================================

@app.route(
    "/api/ai/recommend",
    methods=["GET"]
)
@jwt_required()
def recommend_outfit():

    user_email = current_user_email()

    account_gender = get_user_gender(user_email)

    try:

        # Get user's wardrobe
        wardrobe_items = get_user_wardrobe(
            user_email
        )

        # Get requested occasion
        occasion = request.args.get(
            "occasion",
            "casual"
        )

        # Optional city -> weather nudges the ranking, but is
        # never required. An explicit ?city= always wins; otherwise,
        # UNLESS the caller explicitly opted out with
        # ?use_weather=false (see OutfitRecommendation.js's "Consider
        # today's weather" checkbox), fall back to the user's saved
        # default city (Profile page) so weather applies
        # automatically once someone has set one - they shouldn't
        # have to retype their city every visit. Any weather-lookup
        # failure (no API key configured, bad city name, network
        # issue) just means recommendations come back without a
        # weather boost, not a broken request.
        city = request.args.get("city")
        used_saved_city = False

        use_weather = request.args.get("use_weather", "true").lower() != "false"

        if not city and use_weather:
            profile = get_user_profile(user_email)
            saved_city = (profile or {}).get("city")
            if saved_city:
                city = saved_city
                used_saved_city = True

        # Optional activity tag (see outfit_recommendation.
        # CANONICAL_ACTIVITIES) - purely additive, never required and
        # never filters anything out on its own; an unrecognized or
        # missing value is simply ignored.
        activity = request.args.get("activity")

        weather = None
        weather_error = None

        if city:

            try:

                weather = get_weather(city)

            except Exception as e:

                weather_error = str(e)

                print(
                    f"Weather lookup skipped: {e}"
                )

        # Generate recommendations. account_gender is a
        # defense-in-depth filter (see
        # outfit_recommendation._filter_by_gender) on top of the
        # gender guards already applied at upload time - it's what
        # guarantees a Male account can never receive a Saree/
        # Lehenga/etc suggestion and vice versa, even for
        # legacy/migrated wardrobe items.
        # Wear history and likes/dislikes personalise the ranking.
        # A problem reading them must never break recommendations,
        # so fall back to "no history" instead.
        try:
            wear_history = outfit_feedback.get_wear_history(user_email)
            feedback = outfit_feedback.get_feedback(user_email)
        except Exception as history_error:
            print(f"Wear history/feedback skipped: {history_error}")
            wear_history, feedback = [], {}

        engine_notes = []

        recommendations = recommend_outfits(
            wardrobe_items,
            occasion=occasion,
            weather=weather,
            account_gender=account_gender,
            activity=activity,
            wear_history=wear_history,
            feedback=feedback,
            # Each outfit is shown under ONE occasion/activity only,
            # so casual, college, day out... don't repeat each other.
            exclusive=True,
            notes_out=engine_notes,
            limit=recommend_service.ENGINE_POOL
        )

        # CATEGORY TAB (Tops, Shoes, Sarees...): single-item
        # recommendations of exactly that category, ranked for the
        # occasion - never the outfit list relabelled.
        category_tab = (request.args.get("category") or "All").strip()
        canonical_occasion = resolve_occasion_query(occasion)
        label = outfit_presentation.occasion_label(canonical_occasion)

        if category_tab in item_recommender.GROUPS:
            item_notes = []
            items = item_recommender.recommend_items(
                wardrobe_items, canonical_occasion, category_tab,
                account_gender=account_gender, weather=weather,
                colour=request.args.get("colour"), style=request.args.get("style"),
                wear_history=wear_history, notes=item_notes,
                debug=request.args.get("debug") == "1",
            )
            return jsonify({
                "success": True,
                "mode": "items",
                "category": category_tab,
                "heading": f"{category_tab} for {label}",
                "recommendations": items,
                "notes": item_notes,
                "outfit_mode": outfit_builder_mode(canonical_occasion),
                "weather": weather,
                "weather_error": weather_error,
                "used_saved_city": used_saved_city,
            }), 200

        # Colour/Style filters, then the FINAL VALIDATOR: every outfit
        # is re-checked against this user's stored wardrobe (exists,
        # has an image, right gender, complete, right occasion) before
        # it can reach the browser. Also adds titles and style tags.
        recommendations, engine_notes = recommend_service.finalize(
            recommendations,
            wardrobe_items,
            account_gender,
            resolve_occasion_query(occasion),
            colour=request.args.get("colour"),
            style=request.args.get("style"),
            notes=engine_notes,
            require_full=(category_tab == "Full Looks"),
        )

        # Honest "missing item" messaging (spec section 10) - tells
        # the user plainly when their wardrobe lacks a piece needed
        # to complete an outfit for this occasion, instead of just
        # silently returning fewer/zero recommendations. Never
        # fabricates wardrobe contents - see describe_missing_pieces.
        missing_notes = engine_notes + (
            describe_missing_pieces(
                wardrobe_items,
                occasion=occasion,
                account_gender=account_gender
            )
            if not recommendations else []
        )

        return jsonify({

            "success": True,

            "recommendations":
                recommendations,

            "notes": missing_notes,

            "mode": "looks" if category_tab == "Full Looks" else "outfits",
            "category": category_tab,
            "heading": (f"Complete Looks for {label}" if category_tab == "Full Looks"
                        else f"Outfits for {label}"),

            # "traditional" = complete ethnic outfits; "western" = top +
            # bottom / dress looks. Every look is from the user's wardrobe.
            "outfit_mode": outfit_builder_mode(resolve_occasion_query(occasion)),

            "weather": weather,

            "weather_error": weather_error,

            # Lets the frontend show "using your saved city, X" vs
            # an explicit one-off lookup, instead of guessing from
            # the query string it doesn't have direct access to.
            "used_saved_city": used_saved_city

        }), 200

    except Exception as e:

        print(
            f"Recommendation error: {e}"
        )

        return jsonify({

            "success": False,

            "message": str(e)

        }), 500


# =========================================================
# WEATHER LOOKUP
# =========================================================

@app.route(
    "/api/weather",
    methods=["GET"]
)
@jwt_required()
def weather_lookup():

    city = request.args.get("city")

    try:

        weather = get_weather(city)

        return jsonify({
            "success": True,
            "weather": weather
        }), 200

    except Exception as e:

        return jsonify({
            "success": False,
            "message": str(e)
        }), 400


# =========================================================
# TRIP PLANNER
# =========================================================

@app.route(
    "/api/trips",
    methods=["POST"]
)
@jwt_required()
def create_trip():

    user_email = current_user_email()

    account_gender = get_user_gender(user_email)

    data = request.json or {}

    destination = data.get("destination", "").strip()
    start_date = data.get("start_date")
    end_date = data.get("end_date")
    occasion = data.get("occasion", "casual")
    activity = data.get("activity")

    # Weather for the destination is optional - a lookup failure
    # (no API key configured, unknown city, etc) should never block
    # the trip plan itself. Two separate lookups:
    #   - `weather`: a single current-weather reading, shown as the
    #     one-line summary in the sidebar and used as the fallback
    #     for any day the forecast doesn't cover.
    #   - `weather_by_date`: the actual per-day forecast (see
    #     backend.weather.get_weather_forecast) - this is what lets
    #     each day of the trip get its OWN weather-appropriate
    #     outfit instead of every day sharing one reading. Only
    #     covers ~5 days out (OpenWeatherMap's free tier); days
    #     beyond that fall back inside plan_trip() itself.
    weather = None
    weather_error = None
    weather_by_date = None
    forecast_error = None

    if destination:

        try:

            weather = get_weather(destination)

        except Exception as e:

            weather_error = str(e)

        try:

            forecast = get_weather_forecast(destination)
            weather_by_date = forecast.get("by_date") or None

        except Exception as e:

            forecast_error = str(e)

    if not destination or not start_date or not end_date:

        return jsonify({
            "success": False,
            "message":
                "destination, start_date and end_date are required"
        }), 400

    try:

        wardrobe_items = get_user_wardrobe(
            user_email
        )

        trip_plan = plan_trip(
            wardrobe_items,
            destination,
            start_date,
            end_date,
            occasion=occasion,
            weather=weather,
            weather_by_date=weather_by_date,
            account_gender=account_gender,
            activity=activity
        )

    except ValueError as e:

        return jsonify({
            "success": False,
            "message": str(e)
        }), 400

    except Exception as e:

        print(f"Trip planning error: {e}")

        return jsonify({
            "success": False,
            "message": str(e)
        }), 500

    trip_id = save_trip(
        user_email,
        trip_plan
    )

    # Named looks for the trip (Sightseeing, Evening Dinner...), each
    # weather-aware and never repeating the main pieces. Added after
    # saving so the stored trip stays small.
    try:
        trip_plan["looks"] = recommend_service.trip_looks(
            wardrobe_items, account_gender, weather
        )
    except Exception as e:
        print(f"Trip looks skipped: {e}")
        trip_plan["looks"] = []

    return jsonify({

        "success": True,

        "trip_id": trip_id,

        "trip": trip_plan,

        "weather": weather,

        "weather_error": weather_error,

        "forecast_error": forecast_error

    }), 200


@app.route(
    "/api/trips",
    methods=["GET"]
)
@jwt_required()
def list_trips():

    user_email = current_user_email()

    trips = get_user_trips(user_email)

    return jsonify({
        "success": True,
        "trips": trips
    }), 200


# =========================================================
# USER PROFILE
#
# All three routes below use current_user_email() as the ONLY source
# of which account is being read/changed - never an email/id taken
# from the request body or URL - so an account can only ever view,
# edit, or delete ITSELF, never another user's profile.
# =========================================================

@app.route("/api/user/profile", methods=["GET"])
@jwt_required()
def get_profile():

    user_email = current_user_email()

    profile = get_user_profile(user_email)

    if not profile:
        return jsonify({
            "success": False,
            "message": "Account not found"
        }), 404

    return jsonify({
        "success": True,
        "profile": profile
    }), 200


@app.route("/api/user/profile", methods=["PUT"])
@jwt_required()
def edit_profile():

    user_email = current_user_email()

    data = request.json or {}

    result = update_user_profile(
        user_email,
        name=data.get("name"),
        phone=data.get("phone"),
        city=data.get("city"),
    )

    status_code = 200 if result["success"] else 400

    if result["success"]:
        result["profile"] = get_user_profile(user_email)

    return jsonify(result), status_code


@app.route("/api/user/profile/picture", methods=["POST"])
@jwt_required()
def upload_profile_picture():

    user_email = current_user_email()

    image = request.files.get("image")

    if not image:
        return jsonify({
            "success": False,
            "message": "No image provided"
        }), 400

    if not (image.content_type or "").startswith("image/"):
        return jsonify({
            "success": False,
            "message": "Please upload an image file."
        }), 400

    folder_name, folder_path = get_user_folder(user_email)

    # Always saved under the same fixed name (just keeping whatever
    # extension was uploaded) rather than the original filename, so
    # re-uploading a new profile picture cleanly REPLACES the old one
    # instead of piling up "photo.jpg", "photo (1).jpg", etc. First,
    # remove any previous profile_picture.* file under a DIFFERENT
    # extension - otherwise switching from a .png to a .jpg would
    # leave the old .png sitting there unused on disk forever.
    extension = os.path.splitext(
        secure_filename(image.filename or "")
    )[1] or ".jpg"

    for existing_name in os.listdir(folder_path):
        if os.path.splitext(existing_name)[0] == "profile_picture":
            os.remove(os.path.join(folder_path, existing_name))

    filename = f"profile_picture{extension}"

    local_path = os.path.join(folder_path, filename)

    image.save(local_path)

    # Same reasoning as the wardrobe upload: with Cloudinary
    # configured the stored URL must be one that loads from any
    # computer, otherwise this user's profile picture would appear
    # broken as soon as they logged in somewhere else.
    if config.storage_backend() == "cloudinary":

        try:
            picture_url = storage.upload_local_file(
                local_path,
                user_email,
                kind="profile",
            )

        except storage.StorageError as error:

            print(f"Profile picture upload failed: {error}")

            return jsonify({
                "success": False,
                "message":
                    "Couldn't upload your picture to cloud storage. Please "
                    "check your internet connection and try again."
            }), 502

    else:
        picture_url = f"/api/uploads/{folder_name}/{filename}"

    set_profile_picture(user_email, picture_url)

    return jsonify({
        "success": True,
        "profile_picture": picture_url
    }), 200


# =========================================================
# OUTFIT WEAR HISTORY + LIKE / DISLIKE
# =========================================================

@app.route("/api/outfits/wear", methods=["POST"])
@jwt_required()
def wear_outfit():
    user_email = current_user_email()
    data = request.json or {}
    entry = outfit_feedback.log_wear(
        user_email, data.get("item_ids"), data.get("occasion")
    )
    if not entry:
        return jsonify({"success": False, "message": "No valid items in this outfit"}), 400
    return jsonify({
        "success": True,
        "message": "Saved - these pieces will be suggested less for the next few days.",
        "outfit_key": entry["outfit_key"]
    }), 200


@app.route("/api/outfits/feedback", methods=["POST"])
@jwt_required()
def outfit_feedback_route():
    user_email = current_user_email()
    data = request.json or {}
    value = data.get("value")
    if value not in ("like", "dislike", None):
        return jsonify({"success": False, "message": "value must be like, dislike or null"}), 400
    key = outfit_feedback.set_feedback(user_email, data.get("item_ids"), value)
    if not key:
        return jsonify({"success": False, "message": "No valid items in this outfit"}), 400
    return jsonify({"success": True, "outfit_key": key, "value": value}), 200


@app.route("/api/outfits/history", methods=["GET"])
@jwt_required()
def outfit_history():
    user_email = current_user_email()
    history = outfit_feedback.get_wear_history(user_email)
    for entry in history:
        entry["worn_at"] = entry["worn_at"].isoformat() + "Z"
    return jsonify({"success": True, "history": history}), 200


# =========================================================
# VIRTUAL TRY-ON
#
# The model runs on a GPU elsewhere (see virtual_tryon.py for why and
# which model). These routes are the boring, important half: they
# check who is asking, keep one person's photographs away from
# everybody else's, and turn a 30-second GPU job into something a
# browser can wait for without appearing to hang.
#
# EVERY route here is @jwt_required() and every database call passes
# the caller's own email, taken from the token rather than from the
# request body. A try-on result is a picture of somebody's body; the
# identifier for one appears in a URL. Nothing here can be reached by
# guessing an id.
# =========================================================

def _tryon_usage_now(user_email):
    """
    The allowance as the page should show it, after giving back any
    attempt whose outcome never arrived and whose hold has expired.

    Reading the allowance never generates anything and never calls the
    provider - it is two small database operations - so the page can
    refresh the figure as often as it likes.
    """
    tryon_usage.release_stale_holds(user_email)

    return tryon_usage.snapshot(user_email)


@app.route("/api/tryon/capability", methods=["GET"])
@jwt_required()
def tryon_capability():
    """
    What the Try-On page can offer right now, so the interface can say
    something useful instead of letting the user fill in a form that
    was never going to work.
    """
    photo = tryon_store.get_photo(current_user_email())

    # One question for the orchestrator: which provider (if any) would
    # run a try-on now, and what should the user be told.
    summary = tryon_orchestrator.status_summary()
    engine = summary["engine"]
    available = summary["available"]

    return jsonify({
        "success": True,
        "available": available,
        # ready | fallback | unavailable | not_configured
        "status": summary["status"],
        "message": summary["message"],
        "reason": summary["reason"],
        # Setting NAMES only, and only when nothing is configured at all.
        # Values - tokens, Space ids, share links - never leave the
        # server, and neither do provider names.
        "missing_configuration": (
            virtual_tryon.missing_configuration()
            if summary["status"] == "not_configured" else []
        ),
        "has_photo": bool(photo),
        "photo_url": (photo or {}).get("image_url"),
        "max_upload_mb": config.TRYON_MAX_UPLOAD_MB,
        # Today's remaining try-ons for THIS account. The backend is
        # the only authority on this - the page displays it, it does
        # not decide it.
        "usage": _tryon_usage_now(current_user_email()),
        # One garment per try-on, or a layered outfit (top + bottom +
        # jacket) built one pass at a time - whichever the provider
        # can actually do.
        "max_garments": engine.max_passes() if engine else 1,
        "supports_full_outfit": bool(engine and engine.supports_layering),
        "photo_guidance": [
            "Stand facing the camera, with your whole body (or at least "
            "down to your knees) in frame.",
            "Use good, even light - a bright window behind you makes it harder.",
            "Keep arms relaxed and away from the clothes you want to replace.",
            "One person in the photo, with a plain background if you can.",
        ],
    }), 200


@app.route("/api/tryon/garments", methods=["GET"])
@jwt_required()
def tryon_garments():
    """
    The caller's OWN wardrobe, each item labelled with whether it can
    be tried on and, if not, why.

    Owner comes from the JWT. Items whose category belongs to the other
    gender (per category_catalog) are left out, so a men's account
    never sees women's garments here and vice versa.
    """
    user_email = current_user_email()
    gender = category_catalog.normalize_gender(get_user_gender(user_email))

    # Support is judged against the provider that would actually run.
    engine = tryon_orchestrator.active()

    garments = []

    for item in get_user_wardrobe(user_email):

        category = item.get("category", "")
        genders = category_catalog.genders_of(category)

        if gender and genders and gender not in genders:
            continue

        support = virtual_tryon.garment_support_for(category, engine)
        presented = outfit_presentation.present_item(dict(item))

        garments.append({
            "_id": str(item.get("_id")),
            "category": category,
            "display_name": presented.get("display_name") or category,
            "color": item.get("color", ""),
            "image_path": virtual_tryon.item_image(item),
            "tryon": {
                "supported": support["supported"],
                "slot": support["slot"],
                "shown_beside": virtual_tryon.is_accessory_like(category),
                "reason": support["reason"],
            },
        })

    return jsonify({"success": True, "items": garments}), 200


@app.route("/api/tryon/photo", methods=["GET"])
@jwt_required()
def get_tryon_photo():

    photo = tryon_store.get_photo(current_user_email())

    return jsonify({
        "success": True,
        "photo_url": (photo or {}).get("image_url"),
        "width": (photo or {}).get("width"),
        "height": (photo or {}).get("height"),
    }), 200


def _is_different_image(previous, details, new_url):
    """
    Whether `previous` refers to different stored bytes from the image
    just saved - i.e. whether deleting it would be safe.

    Compares storage identity rather than the URL alone, because
    Cloudinary and local storage identify an image differently: one by
    public_id, the other by filesystem path.
    """
    details = details or {}

    if previous.get("public_id") or details.get("public_id"):
        return previous.get("public_id") != details.get("public_id")

    if previous.get("local_path") or details.get("local_path"):
        return previous.get("local_path") != details.get("local_path")

    return previous.get("image_url") != new_url


@app.route("/api/tryon/photo", methods=["POST"])
@jwt_required()
def upload_tryon_photo():
    """
    Stores the photo the user will be dressed in. One per account:
    uploading a new one replaces and deletes the old.
    """
    user_email = current_user_email()

    image = request.files.get("image")

    if not image:
        return jsonify({"success": False, "message": "No image provided"}), 400

    if not (image.content_type or "").startswith("image/"):
        return jsonify({
            "success": False,
            "message": "Please upload an image file - a JPEG or PNG photo.",
        }), 400

    image.stream.seek(0)
    image_bytes = image.stream.read()
    image.stream.seek(0)

    if len(image_bytes) > config.TRYON_MAX_UPLOAD_MB * 1024 * 1024:
        return jsonify({
            "success": False,
            "message":
                f"That photo is larger than the {config.TRYON_MAX_UPLOAD_MB} MB "
                "limit. Please choose a smaller copy.",
            "problems": [
                f"That photo is larger than the {config.TRYON_MAX_UPLOAD_MB} MB "
                "limit. Please choose a smaller copy."
            ],
        }), 413

    # Checked BEFORE anything is stored, so an unusable photo never
    # reaches the database or costs an upload.
    problems = virtual_tryon.check_person_photo(image_bytes)

    # Advice, not grounds for refusal: a dim or slightly soft photo is
    # still a usable photo, and refusing it would be the "photograph
    # yourself against a white wall" demand this app exists to avoid.
    advice = virtual_tryon.person_photo_advice(image_bytes)

    if problems:
        return jsonify({
            "success": False,
            "message": " ".join(problems),
            "problems": problems,
        }), 400

    width = height = None

    try:
        from PIL import Image
        width, height = Image.open(io.BytesIO(image_bytes)).size
    except Exception:
        pass

    try:
        url, details = storage.save_image(image, user_email, kind="tryon-person")
    except storage.StorageError as error:
        print(f"Try-on photo upload failed: {error}")
        return jsonify({
            "success": False,
            "message":
                "Couldn't save your photo. Please check your connection and "
                "try again.",
        }), 502

    _, previous = tryon_store.set_photo(
        user_email, url, details, width=width, height=height
    )

    # Clean up the photo this one replaced - but ONLY if it is
    # actually a different image.
    #
    # With local storage, an upload keeps its original filename, so
    # re-uploading "me.jpg" writes over the previous "me.jpg". The
    # previous record then points at the very file that was just
    # written, and deleting it would destroy the new photo while
    # leaving a database row insisting it exists. The user would see a
    # broken image and every try-on would fail with "your photo could
    # not be loaded".
    if previous and _is_different_image(previous, details, url):
        storage.delete_image(previous)

    return jsonify({
        "success": True,
        "photo_url": url,
        # Shown beside the photo, not as an error - the photo was
        # accepted either way.
        "advice": advice,
    }), 200


@app.route("/api/tryon/photo", methods=["DELETE"])
@jwt_required()
def delete_tryon_photo():

    removed = tryon_store.delete_photo(current_user_email())

    if not removed:
        return jsonify({"success": False, "message": "No photo on file"}), 404

    storage.delete_image(removed)

    return jsonify({"success": True}), 200


def _wardrobe_items_by_ids(user_email, item_ids):
    """
    The caller's OWN wardrobe items matching these ids, in the order
    the ids were given.

    Ownership is structural rather than checked: this only ever looks
    inside get_user_wardrobe(user_email), so an id belonging to
    somebody else simply does not match anything. Ids that match
    nothing are returned separately so the route can say which item
    went missing rather than silently trying on fewer clothes than
    the user asked for.
    """
    wanted = [str(identifier) for identifier in item_ids]

    owned = {
        str(item.get("_id")): item
        for item in get_user_wardrobe(user_email)
    }

    found = [owned[key] for key in wanted if key in owned]
    missing = [key for key in wanted if key not in owned]

    return found, missing


def _person_photo_bytes(user_email, photo=None):
    """
    The person photo as bytes, wherever storage put it.

    `photo` is the snapshot taken when the try-on was started (see
    start_tryon); only jobs created before that existed fall back to
    the account's current photo.
    """
    if not (photo and (photo.get("image_url") or photo.get("local_path"))):
        photo = tryon_store.get_photo(user_email)

    if not photo:
        raise virtual_tryon.PhotoUnsuitable(
            "Upload a photo of yourself first."
        )

    url = photo.get("image_url") or ""

    if storage.is_remote_url(url):
        path = storage.local_copy_of(url)
    else:
        path = photo.get("local_path")

    if not path or not os.path.isfile(path):
        raise virtual_tryon.PhotoUnsuitable(
            "Your photo could not be loaded. Please upload it again."
        )

    with open(path, "rb") as handle:
        return handle.read()


def _run_tryon_job(job_id, user_email, items, usage_day=None, person_photo=None):
    """
    The actual generation, on a background thread.

    Runs off the request thread because one pass takes 20-60 seconds
    and a full outfit takes two: an HTTP request held open that long
    dies in proxies and looks like a frozen application. Progress and
    the result go into MongoDB, which the browser polls - and which
    means a restart mid-generation surfaces as an honest "this was
    interrupted" rather than a spinner that never stops.

    Nothing in here may raise. A thread that dies silently leaves a
    job stuck in RUNNING forever, so every failure ends in
    mark_failed with a sentence written for the user.
    """
    # "success" (a stored image exists) is the ONLY outcome that spends
    # the attempt; anything else gives it back in the finally block.
    outcome_kind = "failed"

    try:
        person_bytes = _person_photo_bytes(user_email, person_photo)

        def report(step, total, message):
            tryon_store.mark_running(job_id, user_email, step, total, message)

        tryon_store.mark_running(job_id, user_email, 0, 0, "Starting")

        image_bytes, outcome = virtual_tryon.generate_outfit(
            person_bytes, items, on_progress=report
        )

        tryon_store.mark_running(
            job_id, user_email,
            outcome.get("passes", 1), outcome.get("passes", 1),
            "Saving your try-on",
        )

        url, details = storage.save_bytes(
            image_bytes, user_email,
            kind="tryon-result",
            filename_hint=f"tryon_{job_id}.png",
        )

        tryon_store.mark_done(job_id, user_email, url, details, outcome)

        outcome_kind = "success"

    except virtual_tryon.PhotoUnsuitable as error:
        # The input cannot be used, which is as confirmed as it gets:
        # nothing was sent to any provider.
        outcome_kind = "confirmed"
        tryon_store.mark_failed(job_id, user_email, str(error),
                                code=virtual_tryon.UNSUPPORTED_INPUT,
                                charged=False, outcome=outcome_kind)

    except virtual_tryon.TryOnUnavailable as error:
        # str() is the user-safe sentence; .detail is for us and never
        # reaches the browser. Whatever the provider state - quota,
        # cold start, timeout, broken connection - the user received no
        # image, so the attempt is NOT spent.
        print(f"Try-on unavailable for job {job_id} ({error.state}): {error.detail}")
        outcome_kind = "failed"
        tryon_store.mark_failed(job_id, user_email, str(error), code=error.state,
                                charged=False, outcome=outcome_kind)

    except storage.StorageError as error:
        # Our own fault - the image was made but we lost it, so the user
        # is not charged.
        print(f"Try-on storage failed for job {job_id}: {error}")
        outcome_kind = "failed"
        tryon_store.mark_failed(
            job_id, user_email,
            "The try-on worked but the image couldn't be saved. Please try "
            "again - this didn't use one of your daily try-ons.",
            charged=False, outcome=outcome_kind,
        )

    except Exception as error:  # noqa: BLE001 - a dead thread strands the job
        print(f"Try-on job {job_id} failed unexpectedly: {type(error).__name__}: {error}")
        outcome_kind = "failed"
        tryon_store.mark_failed(
            job_id, user_email,
            "Something went wrong generating your try-on. Please try again "
            "- this didn't use one of your daily try-ons.",
            charged=False, outcome=outcome_kind,
        )

    finally:
        # Only a stored, viewable image spends a try-on. Every other
        # ending gives the reserved attempt straight back, credited to
        # the day it was TAKEN. (The only case that reaches neither
        # branch is a backend killed mid-generation; its hold expires by
        # itself - see tryon_usage.release_stale_holds.)
        if outcome_kind == "success":
            tryon_usage.settle(user_email, job_id, usage_day)
        else:
            tryon_usage.release(user_email, job_id, usage_day)


@app.route("/api/tryon/generate", methods=["POST"])
@jwt_required()
def start_tryon():
    """
    Begins a try-on and returns a job id to poll.

    `item_ids` are wardrobe items - the SAME ids the recommendation
    endpoint already returns, which is what lets the "Virtual Try-On"
    button on a recommended outfit work without the user picking
    anything again.
    """
    user_email = current_user_email()

    data = request.get_json(silent=True) or {}

    item_ids = data.get("item_ids") or []

    if (
        not isinstance(item_ids, list)
        or not item_ids
        or not all(isinstance(value, str) and 0 < len(value) <= 64 for value in item_ids)
    ):
        return jsonify({
            "success": False,
            "message": "Choose at least one clothing item to try on.",
        }), 400

    if len(item_ids) > 6:
        return jsonify({
            "success": False,
            "message": "That's too many items for one try-on.",
        }), 400

    # The browser's own id for ONE submission. Answering a repeat with
    # the job it already started is what makes a double-click, or a
    # retry after the connection dropped mid-request, cost one attempt
    # instead of two. Checked before anything else so a replay never
    # reaches the provider at all.
    request_id = data.get("request_id")

    if request_id is not None and not (
        isinstance(request_id, str) and 0 < len(request_id) <= 64
    ):
        return jsonify({
            "success": False,
            "message": "That try-on request couldn't be identified.",
        }), 400

    existing = tryon_store.find_by_request_id(user_email, request_id)

    if existing:
        return jsonify({
            "success": True,
            "job_id": existing["job_id"],
            "total_steps": existing.get("total_steps", 0),
            "estimated_seconds": 0,
            "replayed": True,
            "usage": tryon_usage.snapshot(user_email),
            "not_applied": [],
        }), 202

    summary = tryon_orchestrator.status_summary()
    engine = summary["engine"]

    def _no_provider_response():
        not_configured = summary["status"] == "not_configured"
        return jsonify({
            "success": False,
            "code": "not_configured" if not_configured else "unavailable",
            "message": summary["message"],
            "reason": summary["reason"],
            "missing_configuration": (
                virtual_tryon.missing_configuration() if not_configured else []
            ),
        }), 503

    if summary["status"] == "not_configured":
        return _no_provider_response()

    if not tryon_store.get_photo(user_email):
        return jsonify({
            "success": False,
            "message": "Upload a photo of yourself first.",
        }), 400

    items, missing = _wardrobe_items_by_ids(user_email, item_ids)

    if missing:
        # Same answer whether the id never existed or belongs to
        # somebody else - which of the two is none of the caller's
        # business.
        return jsonify({
            "success": False,
            "message":
                "Some of those clothes are no longer in your wardrobe. "
                "Refresh and pick again.",
        }), 404

    gender = category_catalog.normalize_gender(get_user_gender(user_email))

    for item in items:
        genders = category_catalog.genders_of(item.get("category", ""))
        if gender and genders and gender not in genders:
            return jsonify({
                "success": False,
                "code": "unsupported_garment",
                "message":
                    f"'{item.get('category')}' isn't part of this account's "
                    "wardrobe categories, so it can't be tried on.",
            }), 400

    # Checked before a job is created, so an unsupported garment or an
    # impossible combination is answered immediately and nothing is
    # sent to the model.
    # Garments are judged against the provider that would run the job,
    # or the primary one while every provider is cooling down - so an
    # unsupported garment always gets its real answer, not "try later".
    planner = engine or tryon_orchestrator.primary()
    passes, not_applied, problems = virtual_tryon.plan_outfit(
        items, max_passes=planner.max_passes()
    )

    if problems:
        return jsonify({
            "success": False,
            "code": "unsupported_garment",
            "message": " ".join(problems),
        }), 400

    # Every configured provider is cooling down (quota, queue, asleep...).
    # Nothing is submitted and no job is created - no fake result.
    if engine is None:
        return _no_provider_response()

    # One try-on per account at a time. A second tab, the other laptop,
    # or a click that beat the disabled button would otherwise spend a
    # second attempt and a second run of a shared free GPU on the same
    # person. Refused before anything is reserved, and the running job's
    # id comes back so the page can simply follow that one instead.
    running = tryon_store.active_jobs(user_email)

    if len(running) >= config.TRYON_MAX_CONCURRENT_JOBS:
        return jsonify({
            "success": False,
            "code": "generation_in_progress",
            "message":
                "A try-on is already being created for your account. Wait "
                "for it to finish before starting another - this didn't use "
                "one of your daily attempts.",
            "job_id": running[0]["job_id"],
            "usage": tryon_usage.snapshot(user_email),
        }), 409

    # Hand back any attempt whose outcome never arrived and whose hold
    # has now expired, so somebody returning after a timeout isn't
    # short. Two small database operations; no provider call.
    tryon_usage.release_stale_holds(user_email)

    # The daily limit is taken HERE: after every validation, so a
    # rejected request costs nothing, and before the job exists, so
    # nothing is ever generated without an attempt behind it. The
    # check and the increment are one atomic database operation (see
    # tryon_usage.reserve), which is what stops two simultaneous
    # requests both squeezing past the last remaining attempt.
    #
    # The job id is made first so the attempt can be reserved AS A HOLD
    # against it - that is what lets this one attempt be confirmed,
    # returned, or expired later, instead of just being gone.
    job_id = tryon_store.new_job_id()

    granted, usage = tryon_usage.reserve(user_email, hold_id=job_id)

    if not granted:
        return jsonify({
            "success": False,
            "code": "daily_limit_reached",
            "message": tryon_usage.limit_message(usage),
            "usage": usage,
        }), 429

    # Freeze the person photo for this try-on now: replacing the photo
    # while it generates (on this or another device) must not change
    # which photo this result is made from.
    current_photo = tryon_store.get_photo(user_email) or {}
    person_photo = {
        "image_url": current_photo.get("image_url"),
        "local_path": current_photo.get("local_path"),
    }

    created = tryon_store.create_job(
        user_email,
        [str(item.get("_id")) for item in items],
        person_photo=person_photo,
        source=str(data.get("source") or "manual")[:40],
        occasion=str(data.get("occasion") or "")[:60],
        label=str(data.get("label") or "")[:120],
        job_id=job_id,
        usage_day=usage["day"],
        request_id=request_id,
    )

    if created != job_id:
        # The unique index refused this insert: the very same submission
        # created a job in a request that arrived at the same instant and
        # had not yet been stored when we looked. Nothing of ours is
        # running, so the attempt we just reserved goes straight back and
        # the caller is pointed at the job that won. This is the last
        # window a check-then-insert leaves open, and the database is
        # what closes it.
        tryon_usage.release(user_email, job_id, usage["day"])

        return jsonify({
            "success": True,
            "job_id": created,
            "total_steps": 0,
            "estimated_seconds": 0,
            "replayed": True,
            "usage": tryon_usage.snapshot(user_email),
            "not_applied": [],
        }), 202

    threading.Thread(
        target=_run_tryon_job,
        args=(job_id, user_email, items, usage["day"], person_photo),
        daemon=True,
        name=f"tryon-{job_id[:8]}",
    ).start()

    return jsonify({
        "success": True,
        "job_id": job_id,
        "total_steps": len(passes),
        # Sent up front so the interface can warn that a full outfit
        # takes two generations before the user starts waiting.
        "estimated_seconds": 80 * len(passes),
        "usage": usage,
        "not_applied": [
            {
                "item_id": str(entry["item"].get("_id", "")),
                "category": entry["item"].get("category", ""),
                "image_url": virtual_tryon.item_image(entry["item"]),
                "reason": entry["reason"],
            }
            for entry in not_applied
        ],
    }), 202


@app.route("/api/tryon/status/<job_id>", methods=["GET"])
@jwt_required()
def tryon_status(job_id):

    job = tryon_store.get_job(job_id, current_user_email())

    if not job:
        return jsonify({"success": False, "message": "No such try-on"}), 404

    return jsonify({
        "success": True,
        "job": tryon_store.public_view(job),
    }), 200


@app.route("/api/tryon/results", methods=["GET"])
@jwt_required()
def list_tryon_results():

    results = tryon_store.list_results(current_user_email())

    return jsonify({
        "success": True,
        "results": [tryon_store.public_view(job) for job in results],
    }), 200


@app.route("/api/tryon/result/<job_id>", methods=["DELETE"])
@jwt_required()
def delete_tryon_result(job_id):

    removed = tryon_store.delete_result(job_id, current_user_email())

    if not removed:
        return jsonify({"success": False, "message": "No such try-on"}), 404

    storage.delete_image(removed)

    return jsonify({"success": True}), 200


# =========================================================
# HOME PAGE - everything built from the user's real wardrobe
# =========================================================

@app.route("/api/home", methods=["GET"])
@jwt_required()
def home_page():
    user_email = current_user_email()
    account_gender = get_user_gender(user_email)
    wardrobe_items = get_user_wardrobe(user_email)
    profile = get_user_profile(user_email) or {}

    weather = None
    if profile.get("city"):
        try:
            weather = get_weather(profile["city"])
        except Exception as e:
            print(f"Home weather skipped: {e}")

    try:
        wear_history = outfit_feedback.get_wear_history(user_email)
        feedback = outfit_feedback.get_feedback(user_email)
    except Exception:
        wear_history, feedback = [], {}

    data = recommend_service.build_home(
        wardrobe_items, account_gender, profile, weather,
        wear_history, feedback,
    )
    for item in data["recent"] + data["favourites"]:
        item.pop("created_at", None)
    return jsonify({"success": True, **data}), 200


@app.route("/api/user/account", methods=["DELETE"])
@jwt_required()
def delete_account():

    user_email = current_user_email()

    deleted = delete_user_account(user_email)

    if not deleted:
        return jsonify({
            "success": False,
            "message": "Account not found"
        }), 404

    # Clean up everything else this account owned - wardrobe items,
    # saved trips, and the uploaded image files themselves (their
    # whole folder, in one go, rather than one file at a time) - so
    # deleting an account doesn't leave orphaned data behind that
    # nobody can ever see or reach again.
    delete_all_wardrobe_for_user(user_email)
    delete_all_trips_for_user(user_email)
    outfit_feedback.delete_all_for_user(user_email)
    _saved_looks.delete_all_for_user(user_email)

    # Photographs of a person's body must not outlive the account
    # they belonged to. The records go first, then the images
    # themselves - best effort on the images, because a Cloudinary
    # hiccup must not leave the account half-deleted.
    for leftover in tryon_store.delete_all_for_user(user_email):
        storage.delete_image(leftover)

    _, folder_path = get_user_folder(user_email)
    shutil.rmtree(folder_path, ignore_errors=True)

    return jsonify({
        "success": True
    }), 200


if __name__ == "__main__":

    # Uniqueness guarantees (one account per email, no duplicated
    # migrated items). Reported, never fatal: a database that already
    # holds duplicates still serves requests - see account_doctor.
    try:
        INDEX_PROBLEMS = ensure_indexes()
    except Exception as error:  # noqa: BLE001
        INDEX_PROBLEMS = [f"could not check indexes: {type(error).__name__}"]
    for problem in INDEX_PROBLEMS:
        print(f"WARNING: index not in place - {problem}")

    app.run(
        debug=True,
        port=5001
    )
