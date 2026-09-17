from backend.db import db
from datetime import datetime

trips_collection = db["trips"]


def save_trip(user_email, trip_plan):

    doc = {
        "user_email": user_email,
        "destination": trip_plan["destination"],
        "start_date": trip_plan["start_date"],
        "end_date": trip_plan["end_date"],
        "duration_days": trip_plan["duration_days"],
        "schedule": trip_plan["schedule"],
        "packing_list": trip_plan["packing_list"],
        "created_at": datetime.utcnow()
    }

    result = trips_collection.insert_one(doc)

    return str(result.inserted_id)


def get_user_trips(user_email):

    trips = list(
        trips_collection
        .find({"user_email": user_email})
        .sort("created_at", -1)
    )

    for trip in trips:
        trip["_id"] = str(trip["_id"])

    return trips
