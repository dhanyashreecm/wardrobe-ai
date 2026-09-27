"""
Re-check the category of wardrobe items already uploaded, using the
new western + ethnic classifier (backend/garment_classifier.py).

    python -m backend.reclassify_wardrobe you@example.com          # preview only
    python -m backend.reclassify_wardrobe you@example.com --apply  # save changes

Preview first: it prints "old -> new (confidence)" for every item it
would change and changes nothing until you add --apply. Accessories
(bags, watches, jewellery...) are left alone, and only confident
predictions are applied.
"""
import os
import sys
import tempfile
import urllib.request

from backend import garment_classifier
from backend.auth import get_user_gender
from backend.item_attributes import describe_item
from backend.wardrobe import wardrobe_collection

MIN_CONFIDENCE = 0.45
BASE_DIR = garment_classifier.BASE_DIR
COLOR_KEYS = {"primary_color", "secondary_colors", "pattern", "color_confidence"}
SKIP = {"Bag", "Watch", "Belt", "Jewelry", "Earrings", "Neck Chain",
        "Finger Ring", "Hand Cuff", "Head Accessory"}


def local_image(image_path):
    """Returns (path, is_temporary) for a Cloudinary URL or a local upload."""
    if image_path.startswith("http"):
        suffix = os.path.splitext(image_path.split("?")[0])[1] or ".jpg"
        handle, temp = tempfile.mkstemp(suffix=suffix)
        os.close(handle)
        urllib.request.urlretrieve(image_path, temp)
        return temp, True
    if image_path.startswith("/api/uploads/"):
        relative = image_path[len("/api/uploads/"):]
        for base in (BASE_DIR / "backend" / "uploads", BASE_DIR / "uploads"):
            candidate = base / relative
            if candidate.exists():
                return str(candidate), False
    return None, False


def main():
    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    apply = "--apply" in sys.argv
    if not args:
        print(__doc__)
        return
    if not garment_classifier.is_available():
        print("Train the classifier first:  python -m backend.train_garment_classifier")
        return

    email = args[0]
    gender = get_user_gender(email)
    items = list(wardrobe_collection.find({"user_email": email}))
    print(f"{len(items)} items for {email} ({gender or 'no gender'})\n")

    changed = 0
    for item in items:
        old = item.get("category") or ""
        if old in SKIP:
            continue
        path, temporary = local_image(item.get("image_path") or "")
        if not path:
            print(f"  ? {old:20} image not found, skipped")
            continue
        try:
            result = garment_classifier.predict(path, gender)
        finally:
            if temporary:
                os.remove(path)
        if not result:
            continue
        new, confidence = result["category"], result["confidence"]
        if new == old:
            print(f"  = {old:20} (confirmed, {confidence:.0%})")
            continue
        if confidence < MIN_CONFIDENCE:
            print(f"  ~ {old:20} -> {new} ({confidence:.0%}) not sure enough, kept")
            continue

        print(f"  * {old:20} -> {new} ({confidence:.0%})")
        changed += 1
        if apply:
            new_attrs = describe_item(
                new, styling=item.get("styling"), material=item.get("material"),
                manual_occasion=item.get("occasion"),
            )
            attrs = dict(item.get("attributes") or {})
            attrs.update({k: v for k, v in new_attrs.items() if k not in COLOR_KEYS})
            wardrobe_collection.update_one(
                {"_id": item["_id"]},
                {"$set": {"category": new, "attributes": attrs,
                          "category_confidence": round(confidence, 2),
                          "category_source": "garment_classifier"}},
            )

    if apply:
        print(f"\nUpdated {changed} item(s).")
    else:
        print(f"\n{changed} item(s) would change. Run again with --apply to save.")


if __name__ == "__main__":
    main()
