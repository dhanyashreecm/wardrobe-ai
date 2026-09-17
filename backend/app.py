from backend.outfit_recommendation import recommend_outfits, effective_occasions, describe_missing_pieces
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    jwt_required,
    get_jwt_identity
)
from backend.auth import register_user, verify_login, get_user_gender, migrate_user_gender
from backend.wardrobe import add_item, get_user_wardrobe, delete_item, update_item
from backend.category_gender import is_allowed_for_account
from backend.clothing_similarity import find_similar
from backend.indofashion_similarity import find_similar_indofashion
from backend.indofashion_classifier import predict_category
from backend.weather import get_weather
from backend.trip_planner import plan_trip
from backend.trips import save_trip, get_user_trips

import os
from werkzeug.utils import secure_filename


# =========================================================
# FLASK APP
# =========================================================

app = Flask(__name__)

CORS(app)

app.config["JWT_SECRET_KEY"] = "change-this-secret-key-later"

jwt = JWTManager(app)


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
# =========================================================

BASE_UPLOAD_FOLDER = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "uploads"
)

os.makedirs(
    BASE_UPLOAD_FOLDER,
    exist_ok=True
)


# =========================================================
# USER WARDROBE FOLDER
# =========================================================

def get_user_folder(user_email):

    username = user_email.split("@")[0]

    folder_name = f"{username}_digital_wardrobe"

    folder_path = os.path.join(
        BASE_UPLOAD_FOLDER,
        folder_name
    )

    os.makedirs(
        folder_path,
        exist_ok=True
    )

    return folder_name, folder_path


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

    manual_color = request.form.get("color")

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
    # User folder
    # -----------------------------------------------------

    folder_name, folder_path = get_user_folder(
        user_email
    )


    # -----------------------------------------------------
    # Save image
    # -----------------------------------------------------

    filename = secure_filename(
        image.filename
    )

    path = os.path.join(
        folder_path,
        filename
    )

    image.save(path)


    # -----------------------------------------------------
    # Image URL
    # -----------------------------------------------------

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

            if (
                candidate_label
                and raw_confidence >= ETHNIC_DETECTION_CONFIDENCE_THRESHOLD
                and is_allowed_for_account(candidate_label, account_gender)
            ):

                detected_category = candidate_label
                category_confidence = raw_confidence

                print(
                    f"Auto-detected category for {filename}: "
                    f"{detected_category} "
                    f"(confidence: {category_confidence:.2f})"
                )

        except Exception as e:

            print(
                f"Category detection failed for "
                f"{filename}: {e}"
            )


    # -----------------------------------------------------
    # Color entered manually by the user
    # -----------------------------------------------------

    final_color = request.form.get("color", "").strip()

    if not final_color:
        return jsonify({
            "error": "Please enter a color."
        }), 400

    # -----------------------------------------------------
    # Optional accessory material (e.g. leather, gold, metal)
    # -----------------------------------------------------

    material = request.form.get("material", "").strip()

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
        material
    )


    # -----------------------------------------------------
    # Response
    # -----------------------------------------------------

    return jsonify({

        "success": True,

        "item_id": item_id,

        "category": final_category,

        "color": final_color,

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

        "image": image_url

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
            "favorite": data.get("favorite")
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
        # never required. Any failure (no API key configured,
        # bad city name, network issue) just means recommendations
        # come back without a weather boost, not a broken request.
        city = request.args.get("city")

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
            account_gender=account_gender
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

            "weather_error": weather_error

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

    # Weather for the destination is optional - a lookup failure
    # (no API key configured, unknown city, etc) should never
    # block the trip plan itself.
    weather = None
    weather_error = None

    if destination:

        try:

            weather = get_weather(destination)

        except Exception as e:

            weather_error = str(e)

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
            account_gender=account_gender
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

        "weather_error": weather_error

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


if __name__ == "__main__":

    app.run(
        debug=True,
        port=5001
    )
