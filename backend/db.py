from pymongo import MongoClient

client = MongoClient("mongodb://localhost:27017/")
db = client["wardrobe_db"]
users_collection = db["users"]