from pathlib import Path
import numpy as np
import tensorflow as tf
from tensorflow.keras.applications import MobileNetV2
from tensorflow.keras.applications.mobilenet_v2 import preprocess_input
from tensorflow.keras.preprocessing import image

DATASET_DIR = Path("dataset/deepfashion/processed")
OUTPUT_FILE = Path("dataset/deepfashion/features.npy")

IMG_SIZE = (224, 224)
BATCH_SIZE = 32

print("=" * 50)
print("DEEPFASHION FEATURE EXTRACTION")
print("=" * 50)

image_paths = sorted(DATASET_DIR.glob("*.jpg"))

print(f"Images found: {len(image_paths)}")

if not image_paths:
    raise RuntimeError("No processed images found.")

model = MobileNetV2(
    weights="imagenet",
    include_top=False,
    pooling="avg",
    input_shape=(224, 224, 3)
)

print("Model loaded.")

def load_image(path):
    img = image.load_img(path, target_size=IMG_SIZE)
    arr = image.img_to_array(img)
    arr = np.expand_dims(arr, axis=0)
    return preprocess_input(arr)

features = []
valid_paths = []

for start in range(0, len(image_paths), BATCH_SIZE):
    batch_paths = image_paths[start:start + BATCH_SIZE]

    batch = []
    current_paths = []

    for path in batch_paths:
        try:
            batch.append(load_image(path)[0])
            current_paths.append(str(path))
        except Exception as e:
            print(f"Skipping {path.name}: {e}")

    if not batch:
        continue

    batch = np.array(batch, dtype=np.float32)
    batch_features = model.predict(batch, verbose=0)

    features.append(batch_features)
    valid_paths.extend(current_paths)

    processed = min(start + BATCH_SIZE, len(image_paths))
    if processed % 320 == 0 or processed == len(image_paths):
        print(f"Processed: {processed}/{len(image_paths)}")

features = np.vstack(features)

OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

np.save(OUTPUT_FILE, features)
np.save(
    OUTPUT_FILE.with_name("feature_paths.npy"),
    np.array(valid_paths)
)

print("\nFeature extraction complete.")
print(f"Features shape: {features.shape}")
print(f"Saved features: {OUTPUT_FILE}")
print(f"Saved paths: {OUTPUT_FILE.with_name('feature_paths.npy')}")
