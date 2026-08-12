from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from auth import register_user, verify_login

app = Flask(__name__)
CORS(app)
app.config["JWT_SECRET_KEY"] = "change-this-secret-key-later"
jwt = JWTManager(app)

@app.route("/api/register", methods=["POST"])
def register():
    data = request.json
    name = data.get("name")
    email = data.get("email")
    password = data.get("password")

    if not name or not email or not password:
        return jsonify({"success": False, "message": "All fields required"}), 400

    result = register_user(name, email, password)
    status_code = 200 if result["success"] else 400
    return jsonify(result), status_code

@app.route("/api/login", methods=["POST"])
def login():
    data = request.json
    email = data.get("email")
    password = data.get("password")

    result = verify_login(email, password)
    if result["success"]:
        token = create_access_token(identity=email)
        result["token"] = token
        return jsonify(result), 200
    else:
        return jsonify(result), 401

@app.route("/api/dashboard", methods=["GET"])
@jwt_required()
def dashboard():
    current_user_email = get_jwt_identity()
    return jsonify({"message": f"Welcome, {current_user_email}"}), 200

if __name__ == "__main__":
    app.run(debug=True, port=5001)
