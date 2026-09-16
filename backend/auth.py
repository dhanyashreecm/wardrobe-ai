import bcrypt
from datetime import datetime
from backend.db import users_collection

def register_user(name, email, password):
    existing = users_collection.find_one({"email": email})
    if existing:
        return {"success": False, "message": "Email already registered"}

    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())

    user = {
        "name": name,
        "email": email,
        "password_hash": hashed,
        "created_at": datetime.utcnow()
    }
    users_collection.insert_one(user)
    return {"success": True, "message": "Registration successful"}

def verify_login(email, password):
    user = users_collection.find_one({"email": email})
    if not user:
        return {"success": False, "message": "No account with this email"}

    if bcrypt.checkpw(password.encode("utf-8"), user["password_hash"]):
        return {"success": True, "name": user["name"], "email": user["email"]}
    else:
        return {"success": False, "message": "Incorrect password"}
