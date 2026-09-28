"""
STYLE INSPIRATION - reference pictures shown next to (never instead of)
the user's own outfits.

Where the pictures live
-----------------------
Curated reference pictures (for example looks you saved from Pinterest)
go in the project folder, sorted by gender and occasion:

    inspiration_images/male/party/*.jpg
    inspiration_images/female/wedding/*.jpg   ... (see its README.md)

`python -m backend.build_inspiration` checks them (size, format),
uploads them to Cloudinary and records each one in the Atlas
collection "inspiration":

    {"_id", "gender", "occasion", "url" (Cloudinary https), "width", "height"}

Because both the pictures (Cloudinary) and the list (Atlas) are in the
cloud, every device signed in to this app shows the same inspiration -
nothing depends on this computer's disk.

What the browser gets
---------------------
Only {id, caption, url} for the account's OWN gender and the chosen
occasion. No source site, no link, no original URL.
"""

import json
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(PROJECT_ROOT, "backend", "data", "inspiration_manifest.json")
COLLECTION = "inspiration"
PER_OCCASION = 8

_cache = {"mtime": None, "images": []}


def _manifest():
    """Local copy of the list (written by build_inspiration) - fallback only."""
    try:
        mtime = os.path.getmtime(MANIFEST)
    except OSError:
        return []
    if _cache["mtime"] != mtime:
        with open(MANIFEST, encoding="utf-8") as handle:
            _cache["images"] = json.load(handle).get("images", [])
        _cache["mtime"] = mtime
    return _cache["images"]


def _from_atlas(gender, occasion):
    """The shared list in Atlas, or None if the database can't be read."""
    try:
        from backend.db import db
        cursor = db[COLLECTION].find(
            {"gender": gender, "occasion": occasion},
            {"_id": 1, "gender": 1, "occasion": 1, "url": 1, "caption": 1},
        ).sort("_id", 1).limit(PER_OCCASION)
        return [dict(doc, id=doc.pop("_id")) for doc in cursor]
    except Exception as error:  # database down: fall back, never break the page
        print(f"Inspiration: Atlas not readable ({type(error).__name__}), using local list.")
        return None


def _local_path(src):
    if not (src or "").startswith("project:"):
        return None
    path = os.path.realpath(os.path.join(PROJECT_ROOT, src[len("project:"):]))
    if not path.startswith(os.path.realpath(PROJECT_ROOT) + os.sep):
        return None  # never serve anything outside the project
    return path if os.path.isfile(path) else None


def _present(entry):
    url = entry.get("url") or entry.get("src") or ""
    if url.startswith("https://"):
        return {"id": entry["id"], "caption": entry.get("caption", ""), "url": url}
    if _local_path(url):  # --local-only development builds
        return {"id": entry["id"], "caption": entry.get("caption", ""),
                "url": f"/api/inspiration/image/{entry['id']}"}
    return None


def for_account(gender, occasion, images=None):
    """Pictures for this gender AND occasion only. No gender -> none."""
    if gender not in ("male", "female"):
        return []
    if images is None:
        images = _from_atlas(gender, occasion)
        if not images:
            images = _manifest()
    out = []
    for entry in images:
        if entry.get("gender") != gender or entry.get("occasion") != occasion:
            continue
        shown = _present(entry)
        if shown:
            out.append(shown)
        if len(out) == PER_OCCASION:
            break
    return out


def local_file(image_id, gender, images=None):
    """Path of a project-stored picture (dev builds), only for the matching gender."""
    for entry in (images if images is not None else _manifest()):
        if entry.get("id") == image_id:
            if entry.get("gender") != gender:
                return None
            return _local_path(entry.get("src") or entry.get("url"))
    return None
