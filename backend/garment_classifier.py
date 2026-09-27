"""
AUTOMATIC GARMENT CATEGORY - western AND ethnic.

Why this exists
---------------
The original IndoFashion classifier knows only 15 Indian ethnic
classes. It has never seen jeans, a t-shirt or a crop top, so it
calls bootcut jeans "leggings & salwars" and a crop top "blouse".

This classifier covers every clothing category the app uses. It is
trained (see train_garment_classifier.py) on two labelled datasets
already in the project:

  * Myntra fashion dataset (dataset/kaggle_fashion) - 44k product
    photos: t-shirts, shirts, tops, jeans, trousers, shorts, skirts,
    dresses, jackets, kurtas, kurtis, sarees, leggings, dupattas,
    footwear, bags, watches, belts, jewellery...
  * IndoFashion (dataset/indofashion) - lehenga, blouse, gown,
    sherwani, dhoti pants, nehru jacket, palazzos, mojaris...

How it works (transfer learning)
--------------------------------
1. MobileNetV2 (pre-trained on ImageNet) turns a photo into a
   1280-number "feature vector" describing what it looks like.
2. A logistic-regression layer trained on our labelled photos maps
   that vector to a category (softmax over ~30 categories).

Every photo - training or user upload - goes through the SAME
preparation (prepare_image): placed on a square white canvas and
brought down to the Myntra photos' small size, so the model learns
the garment's shape, not the photo's resolution or background.
"""

import json
from pathlib import Path

import numpy as np
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent.parent
MODEL_FILE = BASE_DIR / "backend" / "data" / "garment_classifier.npz"

LOW_RES = 80          # Myntra images are 60x80
INPUT_SIZE = 224      # MobileNetV2 input

_feature_model = None
_head = None


def prepare_image(img):
    """PIL image -> 224x224 RGB array, normalised the same way for all photos."""
    img = img.convert("RGB")
    img.thumbnail((LOW_RES, LOW_RES), Image.BILINEAR)
    canvas = Image.new("RGB", (LOW_RES, LOW_RES), (255, 255, 255))
    canvas.paste(img, ((LOW_RES - img.width) // 2, (LOW_RES - img.height) // 2))
    canvas = canvas.resize((INPUT_SIZE, INPUT_SIZE), Image.BILINEAR)
    return np.asarray(canvas, dtype="float32")


def feature_model():
    """MobileNetV2 without its top layer (loaded once)."""
    global _feature_model
    if _feature_model is None:
        import tensorflow as tf
        _feature_model = tf.keras.applications.MobileNetV2(
            weights="imagenet", include_top=False, pooling="avg",
            input_shape=(INPUT_SIZE, INPUT_SIZE, 3),
        )
    return _feature_model


def extract_features(arrays):
    """List of prepared arrays -> L2-normalised feature matrix."""
    from tensorflow.keras.applications.mobilenet_v2 import preprocess_input
    batch = preprocess_input(np.stack(arrays))
    features = feature_model().predict(batch, verbose=0)
    norms = np.linalg.norm(features, axis=1, keepdims=True)
    return features / np.maximum(norms, 1e-8)


def is_available():
    return MODEL_FILE.exists()


def _load_head():
    global _head
    if _head is None:
        data = np.load(MODEL_FILE, allow_pickle=False)
        _head = {
            "W": data["coef"],
            "b": data["intercept"],
            "classes": [str(name) for name in data["classes"]],
        }
    return _head


def predict(image_path, account_gender=None, top_k=3):
    """
    Returns {"category", "confidence", "top": [(category, prob), ...]}
    or None if the trained model file doesn't exist yet.

    Categories not allowed for the account's gender (e.g. Kurta (Women)
    on a men's account) are skipped, so the best ALLOWED category wins.
    """
    if not is_available():
        return None

    from backend.category_gender import is_allowed_for_account

    head = _load_head()
    with Image.open(image_path) as img:
        features = extract_features([prepare_image(img)])

    logits = features @ head["W"].T + head["b"]
    logits = logits[0] - logits[0].max()
    probs = np.exp(logits) / np.exp(logits).sum()

    ranked = sorted(zip(head["classes"], probs), key=lambda pair: -pair[1])
    allowed = [
        (name, float(prob)) for name, prob in ranked
        if is_allowed_for_account(name, account_gender)
    ]
    if not allowed:
        return None

    # Renormalise over the allowed categories so confidence stays 0-1.
    total = sum(prob for _, prob in allowed)
    allowed = [(name, prob / total) for name, prob in allowed]

    return {
        "category": allowed[0][0],
        "confidence": allowed[0][1],
        "top": allowed[:top_k],
    }


def training_report():
    report = MODEL_FILE.with_suffix(".json")
    return json.loads(report.read_text()) if report.exists() else None
