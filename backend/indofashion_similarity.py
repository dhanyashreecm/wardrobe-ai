import os
import numpy as np
from tensorflow.keras.applications import MobileNetV2
from tensorflow.keras.applications.mobilenet_v2 import preprocess_input
from tensorflow.keras.preprocessing import image as keras_image


# ============================================================
# PATHS
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

FEATURES_PATH = os.path.join(
    BASE_DIR,
    "..",
    "dataset",
    "indofashion",
    "features.npy"
)

PATHS_PATH = os.path.join(
    BASE_DIR,
    "..",
    "dataset",
    "indofashion",
    "feature_paths.npy"
)


# ============================================================
# LOAD FEATURES
# ============================================================

print("Loading IndoFashion features...")

features = np.load(FEATURES_PATH)

feature_paths = np.load(
    PATHS_PATH,
    allow_pickle=True
)

print("IndoFashion features:", features.shape)
print("IndoFashion paths:", len(feature_paths))


# ============================================================
# NORMALIZE FEATURES
# ============================================================

features = features / (
    np.linalg.norm(
        features,
        axis=1,
        keepdims=True
    ) + 1e-10
)


# ============================================================
# EXTRACT CATEGORY FROM PATH
# ============================================================

def get_category_from_path(path):

    path = str(path)

    # Example:
    # .../processed/blouse/10791.jpeg

    parts = path.replace("\\", "/").split("/")

    try:
        processed_index = parts.index("processed")

        category = parts[
            processed_index + 1
        ]

        return category

    except (ValueError, IndexError):

        return None


# ============================================================
# CREATE CATEGORY INDEX
# ============================================================

category_indices = {}

for index, path in enumerate(feature_paths):

    category = get_category_from_path(path)

    if category is None:
        continue

    if category not in category_indices:

        category_indices[category] = []

    category_indices[category].append(index)


print("IndoFashion categories indexed:")

for category, indices in category_indices.items():

    print(
        f"{category}: {len(indices)} images"
    )


# ============================================================
# LOAD MOBILENETV2
# ============================================================

print("Loading MobileNetV2 model...")

model = MobileNetV2(
    weights="imagenet",
    include_top=False,
    pooling="avg",
    input_shape=(224, 224, 3)
)

print("IndoFashion similarity model ready.")


# ============================================================
# FEATURE EXTRACTION
# ============================================================

def extract_feature(image_path):

    img = keras_image.load_img(
        image_path,
        target_size=(224, 224)
    )

    img_array = keras_image.img_to_array(
        img
    )

    img_array = np.expand_dims(
        img_array,
        axis=0
    )

    img_array = preprocess_input(
        img_array
    )

    feature = model.predict(
        img_array,
        verbose=0
    )[0]

    feature = feature / (
        np.linalg.norm(feature)
        + 1e-10
    )

    return feature


# ============================================================
# CATEGORY-AWARE SIMILARITY
# ============================================================

def find_similar_indofashion(
    image_path,
    top_k=5,
    category=None
):

    query_feature = extract_feature(
        image_path
    )

    # --------------------------------------------------------
    # If category is provided, search only that category
    # --------------------------------------------------------

    if category is not None:

        category = category.lower()

        indices = category_indices.get(
            category,
            []
        )

        # If category doesn't exist,
        # fall back to all images.
        if not indices:

            indices = range(
                len(feature_paths)
            )

    else:

        indices = range(
            len(feature_paths)
        )


    indices = np.array(
        list(indices),
        dtype=int
    )


    # --------------------------------------------------------
    # Calculate similarities
    # --------------------------------------------------------

    candidate_features = features[
        indices
    ]

    similarities = np.dot(
        candidate_features,
        query_feature
    )


    # --------------------------------------------------------
    # Get top results
    # --------------------------------------------------------

    actual_top_k = min(
        top_k,
        len(similarities)
    )

    sorted_positions = np.argsort(
        similarities
    )[::-1][:actual_top_k]


    results = []

    for position in sorted_positions:

        original_index = indices[
            position
        ]

        results.append({

            "image": str(
                feature_paths[
                    original_index
                ]
            ),

            "similarity": float(
                similarities[
                    position
                ]
            ),

            "dataset": "indofashion",

            "category": get_category_from_path(
                feature_paths[
                    original_index
                ]
            )

        })


    return results
