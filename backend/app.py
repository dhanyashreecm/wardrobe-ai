from backend.outfit_recommendation import recommend_outfits
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    jwt_required,
    get_jwt_identity
)
from backend.auth import register_user, verify_login
from backend.wardrobe import add_item, get_user_wardrobe, delete_item
from backend.clothing_similarity import find_similar
from backend.indofashion_similarity import find_similar_indofashion
from backend.indofashion_classifier import predict_category

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

    if not name or not email or not password:

        return jsonify({
            "success": False,
            "message": "All fields required"
        }), 400

    result = register_user(
        name,
        email,
        password
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

    manual_category = request.form.get("category")

    manual_color = request.form.get("color")

    occasion = request.form.get(
        "occasion",
        "casual"
    )

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
    # -----------------------------------------------------

    detected_category = None
    category_confidence = None

    try:

        category_result = predict_category(path)

        detected_category = category_result["category"]
        category_confidence = category_result["confidence"]

        print(
            f"Detected category for {filename}: "
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
    # Choose category
    #
    # Automatic detection gets priority.
    # Manual category is used only if detection fails.
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
        occasion
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

    delete_item(item_id)

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

        # Generate recommendations
        recommendations = recommend_outfits(
            wardrobe_items,
            occasion=occasion
        )

        return jsonify({

            "success": True,

            "recommendations":
                recommendations

        }), 200

    except Exception as e:

        print(
            f"Recommendation error: {e}"
        )

        return jsonify({

            "success": False,

            "message": str(e)

        }), 500
if __name__ == "__main__":

    app.run(
        debug=True,
        port=5001
    )
