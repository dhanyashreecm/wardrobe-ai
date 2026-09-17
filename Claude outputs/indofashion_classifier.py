import json
from pathlib import Path

import numpy as np
import tensorflow as tf
from tensorflow.keras.utils import load_img, img_to_array


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

MODEL_PATH = (
    BASE_DIR
    / "dataset"
    / "indofashion"
    / "indofashion_deep.keras"
)

CLASS_NAMES_PATH = (
    BASE_DIR
    / "dataset"
    / "indofashion"
    / "class_names.json"
)


# ============================================================
# LOAD MODEL
# ============================================================

print("Loading IndoFashion deep model...")

model = tf.keras.models.load_model(
    MODEL_PATH,
    compile=False
)

print("IndoFashion deep model loaded successfully.")


# ============================================================
# LOAD CLASS NAMES
# ============================================================

with open(CLASS_NAMES_PATH, "r") as f:
    class_names = json.load(f)

if isinstance(class_names, dict):
    class_names = [
        class_names[str(i)]
        for i in range(len(class_names))
    ]

print("IndoFashion classes loaded:")
for i, name in enumerate(class_names):
    print(f"{i}: {name}")


# ============================================================
# IMAGE PREPROCESSING
# ============================================================

def preprocess_image(image_path):

    img = load_img(
        image_path,
        target_size=(224, 224)
    )

    img_array = img_to_array(img)

    img_array = np.expand_dims(
        img_array,
        axis=0
    )

    return img_array


# ============================================================
# PREDICT CATEGORY
# ============================================================

def predict_category(image_path, top_k=3):
    """
    Run the IndoFashion model and return its raw top prediction
    across all of its trained classes, plus the next few runner-up
    guesses for context/debugging.

    This model was only ever trained on Indian ethnic wear, so it
    has no idea what a shirt, t-shirt, pant or Western dress looks
    like - it will always force-fit those into whichever ethnic
    class looks closest. Because of that, the caller (app.py)
    should NOT blindly trust every prediction as-is: it should only
    act on this when it lands on a class it actually wants to
    auto-detect (currently just saree/lehenga) and the confidence
    is high enough, and fall back to the user's manual category
    selection otherwise. Filtering/allow-listing intentionally
    happens there, not here, so this function always reports what
    the model actually thinks.
    """

    img_array = preprocess_image(image_path)

    probabilities = model.predict(
        img_array,
        verbose=0
    )[0]

    ranked_indices = sorted(
        range(len(class_names)),
        key=lambda i: probabilities[i],
        reverse=True
    )

    top_indices = ranked_indices[:top_k]

    top_predictions = []

    for index in top_indices:

        top_predictions.append({
            "category": class_names[int(index)],
            "confidence": float(probabilities[index])
        })

    best_index = int(top_indices[0])

    return {
        "category": class_names[best_index],
        "confidence": float(probabilities[best_index]),
        "top_predictions": top_predictions
    }
