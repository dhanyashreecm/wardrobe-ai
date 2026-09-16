from pathlib import Path
import numpy as np
import tensorflow as tf

from tensorflow.keras.applications import MobileNetV2
from tensorflow.keras.applications.mobilenet_v2 import preprocess_input
from tensorflow.keras.preprocessing import image


# =========================================================
# PATHS
# =========================================================

BASE_DIR = Path(__file__).resolve().parent.parent

DATASET_DIR = BASE_DIR / "dataset" / "indofashion"
PROCESSED_DIR = DATASET_DIR / "processed"

FEATURES_FILE = DATASET_DIR / "features.npy"
PATHS_FILE = DATASET_DIR / "feature_paths.npy"


# =========================================================
# SETTINGS
# =========================================================

IMG_SIZE = (224, 224)
BATCH_SIZE = 32


# =========================================================
# LOAD MODEL
# =========================================================

print("Loading MobileNetV2...")

model = MobileNetV2(
    weights="imagenet",
    include_top=False,
    pooling="avg",
    input_shape=(224, 224, 3)
)

print("Model loaded.")


# =========================================================
# FIND IMAGES
# =========================================================

image_paths = sorted(
    [
        p
        for p in PROCESSED_DIR.rglob("*")
        if p.suffix.lower() in [".jpg", ".jpeg", ".png"]
    ]
)

print()
print("Total IndoFashion images:", len(image_paths))


# =========================================================
# FEATURE EXTRACTION
# =========================================================

features = []
valid_paths = []

total = len(image_paths)

for start in range(0, total, BATCH_SIZE):

    batch_paths = image_paths[start:start + BATCH_SIZE]

    batch_images = []

    current_paths = []

    for img_path in batch_paths:

        try:

            img = image.load_img(
                img_path,
                target_size=IMG_SIZE
            )

            arr = image.img_to_array(img)

            batch_images.append(arr)
            current_paths.append(str(img_path))

        except Exception as e:

            print(
                f"Skipping {img_path}: {e}"
            )


    if not batch_images:
        continue


    batch = np.array(batch_images)

    batch = preprocess_input(batch)

    batch_features = model.predict(
        batch,
        verbose=0
    )

    # Normalize each feature vector
    batch_features = batch_features / (
        np.linalg.norm(
            batch_features,
            axis=1,
            keepdims=True
        ) + 1e-10
    )

    features.append(batch_features)
    valid_paths.extend(current_paths)


    processed = min(
        start + BATCH_SIZE,
        total
    )

    if processed % 1000 < BATCH_SIZE:

        print(
            f"Processed {processed}/{total}"
        )


# =========================================================
# SAVE
# =========================================================

print()
print("Combining features...")

features = np.vstack(features)

paths = np.array(valid_paths)


print("Feature shape:", features.shape)
print("Path count:", len(paths))


np.save(
    FEATURES_FILE,
    features
)

np.save(
    PATHS_FILE,
    paths
)


print()
print("====================================")
print("IndoFashion feature extraction done")
print("====================================")

print(
    "Features saved:",
    FEATURES_FILE
)

print(
    "Paths saved:",
    PATHS_FILE
)
