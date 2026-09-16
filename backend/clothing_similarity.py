from pathlib import Path
import numpy as np
import tensorflow as tf

from tensorflow.keras.applications import MobileNetV2
from tensorflow.keras.applications.mobilenet_v2 import preprocess_input
from tensorflow.keras.preprocessing import image


# ============================================================
# BASE DIRECTORY
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

IMG_SIZE = (224, 224)


# ============================================================
# DATASET PATHS
# ============================================================

DEEPFASHION_FEATURES = (
    BASE_DIR
    / "dataset"
    / "deepfashion"
    / "features.npy"
)

DEEPFASHION_PATHS = (
    BASE_DIR
    / "dataset"
    / "deepfashion"
    / "feature_paths.npy"
)


INDOFASHION_FEATURES = (
    BASE_DIR
    / "dataset"
    / "indofashion"
    / "features.npy"
)

INDOFASHION_PATHS = (
    BASE_DIR
    / "dataset"
    / "indofashion"
    / "feature_paths.npy"
)


# ============================================================
# LOAD DEEPFASHION
# ============================================================

print("Loading DeepFashion features...")

deepfashion_features = np.load(
    DEEPFASHION_FEATURES
)

deepfashion_paths = np.load(
    DEEPFASHION_PATHS,
    allow_pickle=True
)

print(
    "DeepFashion features:",
    deepfashion_features.shape
)

print(
    "DeepFashion paths:",
    len(deepfashion_paths)
)


# ============================================================
# NORMALIZE DEEPFASHION FEATURES
# ============================================================

deepfashion_features = (
    deepfashion_features
    / (
        np.linalg.norm(
            deepfashion_features,
            axis=1,
            keepdims=True
        )
        + 1e-10
    )
)


# ============================================================
# LOAD INDOFASHION
# ============================================================

print("Loading IndoFashion features...")

indofashion_features = np.load(
    INDOFASHION_FEATURES
)

indofashion_paths = np.load(
    INDOFASHION_PATHS,
    allow_pickle=True
)

print(
    "IndoFashion features:",
    indofashion_features.shape
)

print(
    "IndoFashion paths:",
    len(indofashion_paths)
)


# ============================================================
# NORMALIZE INDOFASHION FEATURES
# ============================================================

indofashion_features = (
    indofashion_features
    / (
        np.linalg.norm(
            indofashion_features,
            axis=1,
            keepdims=True
        )
        + 1e-10
    )
)


# ============================================================
# LOAD ONE MOBILENETV2 MODEL
# ============================================================

print("Loading MobileNetV2 model...")

model = MobileNetV2(
    weights="imagenet",
    include_top=False,
    pooling="avg",
    input_shape=(224, 224, 3)
)

print("Combined similarity model ready.")


# ============================================================
# FEATURE EXTRACTION
# ============================================================

def extract_feature(image_path):

    img = image.load_img(
        image_path,
        target_size=IMG_SIZE
    )

    arr = image.img_to_array(
        img
    )

    arr = np.expand_dims(
        arr,
        axis=0
    )

    arr = preprocess_input(
        arr
    )

    feature = model.predict(
        arr,
        verbose=0
    )[0]

    feature = feature / (
        np.linalg.norm(feature)
        + 1e-10
    )

    return feature


# ============================================================
# DEEPFASHION CATEGORY
# ============================================================

def get_deepfashion_category(path):

    """
    DeepFashion feature paths currently look like:

        dataset/deepfashion/processed/1000_031.jpg

    DeepFashion does not have category folders in the
    feature paths, so category cannot reliably be extracted
    from the path.
    """

    return None


# ============================================================
# INDOFASHION CATEGORY
# ============================================================

def get_indofashion_category(path):

    """
    IndoFashion paths look like:

        .../processed/blouse/10791.jpeg
    """

    path = str(path)

    parts = (
        path
        .replace("\\", "/")
        .split("/")
    )

    try:

        processed_index = parts.index(
            "processed"
        )

        category = parts[
            processed_index + 1
        ]

        return category

    except (ValueError, IndexError):

        return None


# ============================================================
# COMBINED DATASET SIMILARITY
# ============================================================

def find_similar(
    image_path,
    top_k=5,
    category=None
):

    """
    Search BOTH DeepFashion and IndoFashion.

    If category is provided:

    - IndoFashion is filtered by its known category.
    - DeepFashion is still searched because it has no
      category information in the current feature files.

    Results from both datasets are merged and ranked
    according to visual similarity.
    """

    # --------------------------------------------------------
    # Extract query feature
    # --------------------------------------------------------

    query_feature = extract_feature(
        image_path
    )


    # --------------------------------------------------------
    # DEEPFASHION SEARCH
    # --------------------------------------------------------

    deep_similarities = (
        deepfashion_features
        @ query_feature
    )


    deep_results = []

    deep_top_k = min(
        top_k,
        len(deep_similarities)
    )

    deep_indices = np.argsort(
        deep_similarities
    )[::-1][:deep_top_k]


    for index in deep_indices:

        deep_results.append({

            "image": str(
                deepfashion_paths[
                    index
                ]
            ),

            "similarity": float(
                deep_similarities[
                    index
                ]
            ),

            "dataset": "deepfashion",

            "category": get_deepfashion_category(
                deepfashion_paths[
                    index
                ]
            )

        })


    # --------------------------------------------------------
    # INDOFASHION SEARCH
    # --------------------------------------------------------

    # Always search the complete IndoFashion dataset.
    # Category prediction is kept separate from similarity search.

    candidate_indices = list(
        range(
            len(indofashion_paths)
        )
    )

    candidate_indices = np.array(
        candidate_indices,
        dtype=int
    )


    indo_candidate_features = (
        indofashion_features[
            candidate_indices
        ]
    )


    indo_similarities = (
        indo_candidate_features
        @ query_feature
    )


    indo_top_k = min(
        top_k,
        len(indo_similarities)
    )


    indo_positions = np.argsort(
        indo_similarities
    )[::-1][:indo_top_k]


    indo_results = []


    for position in indo_positions:

        original_index = (
            candidate_indices[
                position
            ]
        )

        indo_results.append({

            "image": str(
                indofashion_paths[
                    original_index
                ]
            ),

            "similarity": float(
                indo_similarities[
                    position
                ]
            ),

            "dataset": "indofashion",

            "category": (
                get_indofashion_category(
                    indofashion_paths[
                        original_index
                    ]
                )
            )

        })


    # ========================================================
    # COMBINE BOTH DATASETS
    # ========================================================

    combined_results = (
        deep_results
        + indo_results
    )


    # --------------------------------------------------------
    # Sort by similarity
    # --------------------------------------------------------

    combined_results.sort(
        key=lambda x: x["similarity"],
        reverse=True
    )


    # --------------------------------------------------------
    # Return final top K
    # --------------------------------------------------------

    return combined_results[
        :top_k
    ]


# ============================================================
# COMPARE AGAINST USER'S WARDROBE
# ============================================================

def find_similar_in_wardrobe(
    query_image_path,
    wardrobe_items,
    top_k=5
):

    """
    Compare the uploaded image against images
    already stored in the user's wardrobe.
    """

    query_feature = extract_feature(
        query_image_path
    )

    results = []


    for item in wardrobe_items:

        image_url = item.get(
            "image_path"
        )

        if not image_url:
            continue


        # ----------------------------------------------------
        # Convert API URL to local path
        # ----------------------------------------------------

        if image_url.startswith(
            "/api/uploads/"
        ):

            relative_path = (
                image_url.replace(
                    "/api/uploads/",
                    "",
                    1
                )
            )

            wardrobe_image_path = (
                BASE_DIR
                / "backend"
                / "uploads"
                / relative_path
            )

        else:

            wardrobe_image_path = Path(
                image_url
            )

            if not wardrobe_image_path.is_absolute():

                wardrobe_image_path = (
                    BASE_DIR
                    / "backend"
                    / wardrobe_image_path
                )


        # ----------------------------------------------------
        # Check image
        # ----------------------------------------------------

        if not wardrobe_image_path.exists():

            print(
                "Wardrobe image not found:",
                wardrobe_image_path
            )

            continue


        # ----------------------------------------------------
        # Extract feature
        # ----------------------------------------------------

        try:

            wardrobe_feature = (
                extract_feature(
                    str(
                        wardrobe_image_path
                    )
                )
            )


            similarity = float(
                np.dot(
                    query_feature,
                    wardrobe_feature
                )
            )


            results.append({

                "item_id": item.get(
                    "_id"
                ),

                "image": image_url,

                "category": item.get(
                    "category"
                ),

                "color": item.get(
                    "color"
                ),

                "occasion": item.get(
                    "occasion"
                ),

                "similarity": similarity

            })


        except Exception as e:

            print(
                "Could not process wardrobe "
                f"image {wardrobe_image_path}: {e}"
            )


    # --------------------------------------------------------
    # Sort
    # --------------------------------------------------------

    results.sort(
        key=lambda x: x["similarity"],
        reverse=True
    )


    return results[
        :top_k
    ]
