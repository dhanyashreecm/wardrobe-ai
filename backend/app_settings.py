"""
Small shared settings kept in the database, so every machine running the
backend (your Mac, the Windows PC, the cloud server the phone app uses)
sees the same value without editing each .env.

Used for the try-on GPU address: the Kaggle notebook gets a NEW https
address every time it starts. `python -m backend.kaggle_tryon start`
writes it here as well as into .env, and a server started with
TRYON_GPU_URL_FROM_DB=true reads it from here - so the phone app keeps
working after every GPU restart with nobody touching the server.
"""
import os
import time
from datetime import datetime

CACHE_SECONDS = 60
_cache = {}


def _collection():
    from backend.db import db
    return db["app_settings"]


def get(key, default=None):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    try:
        doc = _collection().find_one({"_id": key})
        value = (doc or {}).get("value", default)
    except Exception as error:  # noqa: BLE001 - a setting must never crash a request
        print(f"[settings] could not read {key}: {type(error).__name__}")
        value = hit[1] if hit else default
    _cache[key] = (time.time(), value)
    return value


def put(key, value):
    _collection().update_one({"_id": key},
                             {"$set": {"value": value, "updated_at": datetime.utcnow()}},
                             upsert=True)
    _cache[key] = (time.time(), value)


def gpu_url_from_db_enabled():
    return os.environ.get("TRYON_GPU_URL_FROM_DB", "").strip().lower() in ("1", "true", "yes")
