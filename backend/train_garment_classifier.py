"""
Train the western + ethnic garment classifier (backend/garment_classifier.py).

Run ONCE on the Mac, from the project root, with ai_env active:

    python -m backend.train_garment_classifier

Takes roughly 5-10 minutes on an M1. It prints the accuracy on photos
it did NOT train on, then saves backend/data/garment_classifier.npz.
Restart the backend afterwards to start using it.

Data used (both already in the project):
  * dataset/kaggle_fashion  - Myntra product photos + styles.csv labels
  * dataset/indofashion     - IndoFashion photos, one folder per class
"""

import csv
import json
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

from backend.garment_classifier import (
    BASE_DIR, MODEL_FILE, extract_features, prepare_image,
)

MAX_PER_CATEGORY = 900
BATCH = 64
SEED = 42
FEATURE_CACHE = BASE_DIR / "dataset" / "garment_features_cache.npz"

KAGGLE_DIR = BASE_DIR / "dataset" / "kaggle_fashion"
INDO_DIR = BASE_DIR / "dataset" / "indofashion"

# Myntra articleType -> app category ("Kurtas" is split by gender below)
KAGGLE_MAP = {
    "Tshirts": "T-Shirt", "Sweatshirts": "T-Shirt",
    "Tops": "Top", "Tunics": "Kurta (Women)", "Kurtis": "Kurta (Women)",
    "Shirts": "Shirt",
    "Jeans": "Denims",
    "Trousers": "Pant", "Track Pants": "Pant", "Capris": "Pant",
    "Lounge Pants": "Pant",
    "Shorts": "Shorts",
    "Skirts": "Skirt",
    "Dresses": "Dress",
    "Jackets": "Jacket", "Blazers": "Jacket", "Sweaters": "Jacket",
    "Sarees": "Saree",
    "Leggings": "Leggings & Salwars", "Salwar": "Leggings & Salwars",
    "Churidar": "Leggings & Salwars", "Patiala": "Leggings & Salwars",
    "Salwar and Dupatta": "Leggings & Salwars",
    "Dupatta": "Dupatta", "Stoles": "Dupatta",
    "Casual Shoes": "Footwear", "Sports Shoes": "Footwear",
    "Formal Shoes": "Footwear", "Heels": "Footwear", "Flats": "Footwear",
    "Sandals": "Footwear", "Flip Flops": "Footwear",
    "Handbags": "Bag", "Clutches": "Bag", "Backpacks": "Bag",
    "Watches": "Watch",
    "Belts": "Belt",
    "Earrings": "Earrings",
    "Necklace and Chains": "Neck Chain", "Pendant": "Neck Chain",
    "Ring": "Finger Ring",
    "Bangle": "Hand Cuff", "Bracelet": "Hand Cuff",
}

# IndoFashion folder name -> app category
INDO_MAP = {
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
    "women_kurta": "Kurta (Women)",
}

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def kaggle_samples():
    styles = KAGGLE_DIR / "styles.csv"
    images = KAGGLE_DIR / "images"
    if not styles.exists() or not images.exists():
        print("  ! Myntra dataset not found - skipping")
        return []
    samples = []
    with open(styles, newline="", encoding="utf-8", errors="ignore") as handle:
        for row in csv.DictReader(handle):
            article = (row.get("articleType") or "").strip()
            if article == "Kurtas":
                category = "Kurta (Men)" if row.get("gender") in ("Men", "Boys") else "Kurta (Women)"
            else:
                category = KAGGLE_MAP.get(article)
            if not category:
                continue
            path = images / f"{row['id']}.jpg"
            if path.exists():
                samples.append((path, category))
    return samples


def indo_samples():
    root = INDO_DIR / "processed"
    if not root.exists():
        root = INDO_DIR
    if not root.exists():
        print("  ! IndoFashion images not found - skipping")
        return []
    samples = []
    for folder in root.rglob("*"):
        if folder.is_dir() and folder.name in INDO_MAP:
            category = INDO_MAP[folder.name]
            for path in folder.iterdir():
                if path.suffix.lower() in IMAGE_SUFFIXES:
                    samples.append((path, category))
    return samples


def balanced(samples):
    """At most MAX_PER_CATEGORY per category, mixing both datasets."""
    random.seed(SEED)
    by_category = defaultdict(list)
    for path, category in samples:
        by_category[category].append(path)
    chosen = []
    for category, paths in sorted(by_category.items()):
        random.shuffle(paths)
        chosen += [(path, category) for path in paths[:MAX_PER_CATEGORY]]
    return chosen


def featurise(samples):
    features, labels = [], []
    start = time.time()
    for index in range(0, len(samples), BATCH):
        arrays, batch_labels = [], []
        for path, category in samples[index:index + BATCH]:
            try:
                with Image.open(path) as img:
                    arrays.append(prepare_image(img))
                batch_labels.append(category)
            except Exception:
                continue
        if arrays:
            features.append(extract_features(arrays))
            labels += batch_labels
        done = min(index + BATCH, len(samples))
        rate = done / max(time.time() - start, 1e-6)
        print(f"\r  features: {done}/{len(samples)}  ({rate:.0f} img/s)", end="")
        sys.stdout.flush()
    print()
    return np.vstack(features), np.array(labels)


def main():
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import classification_report
    from sklearn.model_selection import train_test_split

    print("Collecting labelled photos...")
    samples = kaggle_samples() + indo_samples()
    samples = balanced(samples)
    counts = Counter(category for _, category in samples)
    print(f"  {len(samples)} photos, {len(counts)} categories")
    for category, count in sorted(counts.items()):
        print(f"    {category:20} {count}")

    if FEATURE_CACHE.exists() and "--fresh" not in sys.argv:
        cached = np.load(FEATURE_CACHE, allow_pickle=False)
        X, y = cached["X"], cached["y"]
        print(f"Using cached features ({len(y)} photos). Pass --fresh to rebuild.")
    else:
        print("Extracting MobileNetV2 features (the slow part)...")
        X, y = featurise(samples)
        np.savez_compressed(FEATURE_CACHE, X=X, y=y)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.15, random_state=SEED, stratify=y
    )

    print("Training the classifier...")
    clf = LogisticRegression(max_iter=3000, C=2.0, class_weight="balanced")
    clf.fit(X_train, y_train)

    accuracy = float(clf.score(X_test, y_test))
    print(f"\nAccuracy on {len(y_test)} unseen photos: {accuracy:.1%}\n")
    report = classification_report(y_test, clf.predict(X_test), digits=2)
    print(report)

    # Final model: train on everything.
    clf.fit(X, y)
    MODEL_FILE.parent.mkdir(parents=True, exist_ok=True)
    np.savez(MODEL_FILE, coef=clf.coef_.astype("float32"),
             intercept=clf.intercept_.astype("float32"),
             classes=np.array(clf.classes_))
    MODEL_FILE.with_suffix(".json").write_text(json.dumps({
        "test_accuracy": accuracy,
        "photos": int(len(y)),
        "categories": {k: int(v) for k, v in Counter(y.tolist()).items()},
        "report": report,
    }, indent=2))
    print(f"Saved {MODEL_FILE.relative_to(BASE_DIR)}")
    print("Restart the backend to start using it.")


if __name__ == "__main__":
    main()
