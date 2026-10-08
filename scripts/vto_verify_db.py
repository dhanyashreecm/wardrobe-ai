"""Prints today's Virtual Try-On usage rows and stored results for the two demo accounts,
read straight from MongoDB (Atlas) - not from the frontend."""
from backend.db import db
from backend import tryon_usage

ACCOUNTS = ["dhanyashree616+vtodemoa@gmail.com", "dhanyashree616+vtodemob@gmail.com"]
day = tryon_usage.today()
print(f"Database: {db.name}   day (IST): {day}\n")
for email in ACCOUNTS:
    row = db["tryon_usage"].find_one({"_id": f"{email}|{day}"}) or {}
    jobs = list(db["tryon_results"].find({"user_email": email}).sort("created_at", 1)) if "tryon_results" in db.list_collection_names() else []
    done = [j for j in jobs if j.get("status") == "done" and j.get("image_url")]
    print(f"{email}")
    print(f"  usage row _id   : {row.get('_id')}")
    print(f"  used (count)    : {row.get('used')}   holds in flight: {len(row.get('holds') or [])}")
    print(f"  jobs stored     : {len(jobs)}   done with image: {len(done)}   failed: {sum(j.get('status')=='failed' for j in jobs)}")
    for j in done:
        print(f"    {j.get('created_at')}  {j.get('image_url')}")
    print()
