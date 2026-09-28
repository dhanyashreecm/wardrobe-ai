from pathlib import Path
import numpy as np
import tensorflow as tf

from tensorflow.keras.applications import MobileNetV2
from tensorflow.keras.applications.mobilenet_v2 import preprocess_input
from tensorflow.keras.preprocessing import image

# Only used to turn a cloud image URL back into a local file this
# module can read - see find_similar_in_wardrobe().
from backend import storage


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
# LOAD A DATASET'S FEATURES/PATHS, WITHOUT TAKING DOWN THE
# WHOLE APP IF THE FILES AREN'T THERE
#
# These .npy files are large generated artifacts (tens to
# hundreds of MB) that are deliberately gitignored (see
# dataset/ in .gitignore) - a fresh clone (e.g. a new
# collaborator's machine) will not have them until someone
# copies them over by hand. Before this fix, a missing file
# here crashed the entire Flask app at import time (this is
# the exact FileNotFoundError a second collaborator hit
# running `python -m backend.app` on a fresh clone) - meaning
# every feature of the app, not just "Similar Search", was
# unusable. Now a missing/corrupt dataset just disables THAT
# dataset's similarity search (with a clear one-time warning
# printed at startup) and the rest of the app runs normally.
# ============================================================

def _load_dataset(features_path, paths_path, label):

    try:

        features = np.load(features_path)
        paths = np.load(paths_path, allow_pickle=True)

    except (FileNotFoundError, OSError, ValueError) as e:

        print(
            f"WARNING: {label} similarity search is disabled - "
            f"could not load dataset features ({e}). This is "
            f"expected on a fresh clone: {features_path.name} and "
            f"{paths_path.name} are large generated files that are "
            "not stored in git. Everything else in the app will "
            "still work; ask a teammate who has already trained/"
            "extracted these files to share the dataset/ folder "
            "contents to enable this search."
        )

        return None, np.array([]), False

    print(f"{label} features:", features.shape)
    print(f"{label} paths:", len(paths))

    # Normalize once at load time so find_similar() can do a
    # plain dot product for cosine similarity.
    features = features / (
        np.linalg.norm(features, axis=1, keepdims=True) + 1e-10
    )

    return features, paths, True


print("Loading DeepFashion features...")

(
    deepfashion_features,
    deepfashion_paths,
    DEEPFASHION_AVAILABLE,
) = _load_dataset(
    DEEPFASHION_FEATURES, DEEPFASHION_PATHS, "DeepFashion"
)

print("Loading IndoFashion features...")

(
    indofashion_features,
    indofashion_paths,
    INDOFASHION_AVAILABLE,
) = _load_dataset(
    INDOFASHION_FEATURES, INDOFASHION_PATHS, "IndoFashion"
)

if not (DEEPFASHION_AVAILABLE or INDOFASHION_AVAILABLE):
    print(
        "WARNING: no dataset features are available at all - "
        "find_similar() will always return an empty list until "
        "at least one dataset's features.npy/feature_paths.npy "
        "is added."
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
    # Skipped entirely if this dataset's features weren't
    # available at startup (see _load_dataset above) - rather
    # than erroring on a None/empty features array.

    deep_results = []

    if DEEPFASHION_AVAILABLE:

        deep_similarities = (
            deepfashion_features
            @ query_feature
        )

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

    # Always search the complete IndoFashion dataset (when
    # available). Category prediction is kept separate from
    # similarity search.

    indo_results = []

    if INDOFASHION_AVAILABLE:

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
        #
        # Three shapes have to resolve to a readable FILE here,
        # because extract_feature() below opens a path, not a URL:
        #
        #   1. "https://res.cloudinary.com/..." - an item uploaded
        #      since images moved to shared cloud storage. Fetched
        #      once and cached on this machine (storage.local_copy_of).
        #      Without this branch every such item would fail the
        #      .exists() check below and silently drop out of the
        #      results, making "find similar in my wardrobe" look
        #      broken for anything uploaded after the move.
        #   2. "/api/uploads/..." - an older item still on this disk.
        #   3. a bare relative path - oldest records.
        # ----------------------------------------------------

        if image_url.startswith(("http://", "https://")):

            cached = storage.local_copy_of(image_url)

            if not cached:
                # Already logged by local_copy_of - skip this one item
                # rather than failing the whole search.
                continue

            wardrobe_image_path = Path(cached)

        elif image_url.startswith(
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
