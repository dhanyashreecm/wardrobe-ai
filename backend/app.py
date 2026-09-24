from backend.outfit_recommendation import recommend_outfits, effective_occasions, describe_missing_pieces
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    jwt_required,
    get_jwt_identity
)
from backend.auth import (
    register_user,
    verify_login,
    get_user_gender,
    migrate_user_gender,
    get_user_profile,
    update_user_profile,
    set_profile_picture,
    delete_user_account,
)
from backend.wardrobe import (
    add_item,
    get_user_wardrobe,
    delete_item,
    update_item,
    delete_all_for_user as delete_all_wardrobe_for_user,
)
from backend.category_gender import is_allowed_for_account
from backend.garment_taxonomy import model_may_override
from backend.clothing_similarity import find_similar
from backend.indofashion_similarity import find_similar_indofashion
from backend.indofashion_classifier import predict_category
from backend.weather import get_weather, get_weather_forecast
from backend.trip_planner import plan_trip
from backend.trips import save_trip, get_user_trips, delete_all_for_user as delete_all_trips_for_user
from backend.color_detection import detect_dominant_color
from backend import config, storage
from backend.db import ping as ping_database

import os
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

jwt = JWTManager(app)


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
    }

    # 503 when the database is unreachable so uptime checks and
    # scripts can rely on the status code alone, not just the body.
    return jsonify(payload), (200 if database_ok else 503)


# =========================================================
# REGISTER
# =========================================================

@app.route("/api/register", methods=["POST"])
def register():

    data = request.json

    name = data.get("name")
    email = data.get("email")
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

    data = request.json

    email = data.get("email")
    password = data.get("password")

    result = verify_login(
        email,
        password
    )

    if result["success"]:

        token = create_access_token(
            identity=email
        )

        result["token"] = token

        return jsonify(result), 200

    else:

        return jsonify(result), 401


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

    user_email = get_jwt_identity()

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

    current_user_email = get_jwt_identity()

    return jsonify({
        "message": f"Welcome, {current_user_email}"
    }), 200


# =========================================================
# ADD WARDROBE ITEM
# =========================================================

@app.route("/api/wardrobe/add", methods=["POST"])
@jwt_required()
def add_wardrobe_item():

    user_email = get_jwt_identity()

    # Used below to keep the AI's saree/lehenga auto-detection from
    # overriding a Male account's category - see get_user_gender().
    account_gender = get_user_gender(user_email)

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

    if not image:

        return jsonify({
            "success": False,
            "message": "No image provided"
        }), 400


    # -----------------------------------------------------
    # Save image
    #
    # The file is written to this machine's disk FIRST, even when
    # Cloudinary is configured, because the AI steps below
    # (predict_category, detect_dominant_color) open a filesystem
    # path, not a URL - keeping a local copy is the smallest possible
    # change that leaves those modules untouched. The local copy is a
    # working file, not the permanent home: the permanent home is
    # whatever storage.save_image() returns.
    # -----------------------------------------------------

    folder_name, folder_path = get_user_folder(
        user_email
    )

    filename = secure_filename(
        image.filename
    )

    path = os.path.join(
        folder_path,
        filename
    )

    image.save(path)


    # -----------------------------------------------------
    # Permanent image URL
    #
    # With Cloudinary configured this is an https URL that loads on
    # ANY computer - which is what lets the same account see the same
    # wardrobe from a second laptop. Without it, this falls back to
    # the original "/api/uploads/..." path served by this machine
    # (see storage.py), so a single-machine setup still works.
    #
    # An upload failure is returned as an error rather than swallowed:
    # saving a wardrobe row whose image never reached storage would
    # leave a permanently broken item in the user's wardrobe.
    # -----------------------------------------------------

    if config.storage_backend() == "cloudinary":

        try:
            image_url = storage.upload_local_file(
                path,
                user_email,
                kind="wardrobe",
            )

        except storage.StorageError as error:

            print(f"Image upload failed for {filename}: {error}")

            return jsonify({
                "success": False,
                "message":
                    "Couldn't upload this image to cloud storage. Please "
                    "check your internet connection and try again."
            }), 502

    else:

        image_url = (
            f"/api/uploads/"
            f"{folder_name}/"
            f"{filename}"
        )


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

    if manual_category not in ACCESSORY_CATEGORIES:

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

    if manual_color:
        final_color = manual_color
    else:
        detected = detect_dominant_color(path)

        if detected:
            final_color = detected
            color_auto_detected = True
        else:
            final_color = ""

    if not final_color:
        return jsonify({
            "error":
                "Couldn't detect a color from this photo - please "
                "enter one."
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
    # -----------------------------------------------------
    # Store wardrobe item
    # -----------------------------------------------------

    item_id = add_item(
        user_email,
        final_category,
        final_color,
        image_url,
        occasion,
        material,
        styling
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
# =========================================================

@app.route(
    "/api/uploads/<folder_name>/<filename>"
)
def serve_image(
    folder_name,
    filename
):

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

    user_email = get_jwt_identity()

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

    user_email = get_jwt_identity()

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

    user_email = get_jwt_identity()

    data = request.json or {}

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

    from backend.clothing_similarity import (
        find_similar_in_wardrobe
    )

    user_email = get_jwt_identity()

    account_gender = get_user_gender(user_email)

    image = request.files.get("image")


    # -----------------------------------------------------
    # Validate image
    # -----------------------------------------------------

    if not image:

        return jsonify({
            "success": False,
            "message": "No image provided"
        }), 400


    # -----------------------------------------------------
    # Save query image
    # -----------------------------------------------------

    filename = secure_filename(
        image.filename
    )

    temp_folder = os.path.join(
        BASE_UPLOAD_FOLDER,
        "ai_queries"
    )

    os.makedirs(
        temp_folder,
        exist_ok=True
    )

    image_path = os.path.join(
        temp_folder,
        filename
    )

    image.save(image_path)


    # -----------------------------------------------------
    # AI PROCESSING
    # -----------------------------------------------------

    try:

        # -------------------------------------------------
        # USER'S OWN WARDROBE
        # -------------------------------------------------

        wardrobe_items = get_user_wardrobe(
            user_email
        )

        wardrobe_results = (
            find_similar_in_wardrobe(
                image_path,
                wardrobe_items,
                top_k=5
            )
        )


        # -------------------------------------------------
        # DEEPFASHION
        # -------------------------------------------------

        dataset_results = find_similar(
            image_path,
            top_k=5
        )


        # -------------------------------------------------
        # CLASSIFICATION
        # -------------------------------------------------

        category_results = predict_category(
            image_path
        )

        predicted_category = (
            category_results.get(
                "category"
            )
        )


        # -------------------------------------------------
        # INDOFASHION
        #
        # Filter by predicted category
        # -------------------------------------------------

        indofashion_results = (
            find_similar_indofashion(
                image_path,
                top_k=5,
                category=predicted_category
            )
        )


        # -------------------------------------------------
        # GENDER FILTERING
        #
        # wardrobe_results never needs this - it's already only the
        # signed-in user's own items. For the two external datasets:
        #   - IndoFashion results DO carry a real category (see
        #     get_indofashion_category/get_category_from_path), so
        #     they can genuinely be gender-filtered here.
        #   - DeepFashion results carry category=None - there is no
        #     way to recover a category (and therefore a gender)
        #     from DeepFashion's current feature paths at all (see
        #     get_deepfashion_category's docstring in
        #     clothing_similarity.py). This is a real, disclosed
        #     limitation: DeepFashion suggestions are NOT currently
        #     gender-filtered. is_allowed_for_account() already
        #     treats a None/unknown category as allowed, so this
        #     just documents why dataset_results passes through
        #     unfiltered rather than silently guessing.
        # -------------------------------------------------

        dataset_results = [
            item for item in dataset_results
            if is_allowed_for_account(item.get("category"), account_gender)
        ]

        indofashion_results = [
            item for item in indofashion_results
            if is_allowed_for_account(item.get("category"), account_gender)
        ]


        # -------------------------------------------------
        # RESPONSE
        # -------------------------------------------------

        return jsonify({

            "success": True,

            "wardrobe_results":
                wardrobe_results,

            "dataset_results":
                dataset_results,

            "indofashion_results":
                indofashion_results,

            "category_results":
                category_results

        }), 200


    # -----------------------------------------------------
    # ERROR
    # -----------------------------------------------------

    except Exception as e:

        print(
            f"Similarity search error: {e}"
        )

        return jsonify({

            "success": False,

            "message": str(e)

        }), 500


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

    user_email = get_jwt_identity()

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
        recommendations = recommend_outfits(
            wardrobe_items,
            occasion=occasion,
            weather=weather,
            account_gender=account_gender,
            activity=activity
        )

        # Honest "missing item" messaging (spec section 10) - tells
        # the user plainly when their wardrobe lacks a piece needed
        # to complete an outfit for this occasion, instead of just
        # silently returning fewer/zero recommendations. Never
        # fabricates wardrobe contents - see describe_missing_pieces.
        missing_notes = describe_missing_pieces(
            wardrobe_items,
            occasion=occasion,
            account_gender=account_gender
        )

        return jsonify({

            "success": True,

            "recommendations":
                recommendations,

            "notes": missing_notes,

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

    user_email = get_jwt_identity()

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

    user_email = get_jwt_identity()

    trips = get_user_trips(user_email)

    return jsonify({
        "success": True,
        "trips": trips
    }), 200


# =========================================================
# USER PROFILE
#
# All three routes below use get_jwt_identity() as the ONLY source
# of which account is being read/changed - never an email/id taken
# from the request body or URL - so an account can only ever view,
# edit, or delete ITSELF, never another user's profile.
# =========================================================

@app.route("/api/user/profile", methods=["GET"])
@jwt_required()
def get_profile():

    user_email = get_jwt_identity()

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

    user_email = get_jwt_identity()

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

    user_email = get_jwt_identity()

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


@app.route("/api/user/account", methods=["DELETE"])
@jwt_required()
def delete_account():

    user_email = get_jwt_identity()

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

    _, folder_path = get_user_folder(user_email)
    shutil.rmtree(folder_path, ignore_errors=True)

    return jsonify({
        "success": True
    }), 200


if __name__ == "__main__":

    app.run(
        debug=True,
        port=5001
    )
