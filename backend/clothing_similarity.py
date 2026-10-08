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
#
# Two different questions, answered separately:
#
#   * "Is this the SAME photo as one of my items?" - a pixel
#     fingerprint (32x32 thumbnail). It survives resizing, JPEG
#     re-compression and Cloudinary's re-encoding, so an item
#     uploaded again comes back as exactly 100%.
#
#   * "Does it LOOK like one of my items?" - MobileNetV2 features
#     (cosine similarity). These never reach 1.0 for a re-encoded
#     copy, and the upload flow stores a background-removed version,
#     so on its own this put an exact re-upload at ~89%.
#
# Both the photo as uploaded AND its cleaned (background-removed)
# version are compared, against both the stored image and the
# untouched original kept at upload time; the best pairing wins.
# ============================================================

# "Same item" is decided by three independent checks; any one is
# enough (see find_similar_in_wardrobe):
#
#   1. Keypoint match (ORB + RANSAC). Finds the same visual details in
#      both pictures whatever the size, crop, white padding the upload
#      step added, or JPEG/Cloudinary re-encoding. On the real wardrobe
#      photos: the same item scored 57-745 inliers, different items 24
#      or less (one fluke of 45 - a skirt vs boots - which the
#      appearance guard below rejects).
#   2. Pixel thumbnail - catches plain, texture-less garments, where
#      keypoints are scarce, when the photo is otherwise unchanged.
#   3. Appearance features almost identical (MobileNetV2 cosine).
EXACT_MIN_KEYPOINT_INLIERS = 40
EXACT_KEYPOINT_MIN_FEATURE_SIMILARITY = 0.80
FINGERPRINT_SIZE = 32
EXACT_MAX_PIXEL_DIFFERENCE = 0.012
EXACT_PIXEL_MIN_FEATURE_SIMILARITY = 0.85
EXACT_FEATURE_SIMILARITY = 0.97
# Every rule above is colour-blind (keypoints work on grey, and the
# appearance features barely see hue), so the same T-shirt print in
# red/blue/green/black matched itself. The garment's centre colour must
# also agree: same-item pairs differed by <= 0.075 on the wardrobe
# photos, different colours of one design by >= 0.24.
EXACT_MAX_COLOUR_DIFFERENCE = 0.15


def image_fingerprint(image_path):
    """
    {"thumb": 32x32 RGB vector, "kp": (keypoints, descriptors)} for a
    photo, or None if it cannot be read.
    """
    from PIL import Image, ImageOps
    import cv2

    try:
        with Image.open(image_path) as img:
            img = ImageOps.exif_transpose(img).convert("RGB")
            thumb = img.resize((FINGERPRINT_SIZE, FINGERPRINT_SIZE), Image.LANCZOS)
            centre = np.asarray(img.resize((64, 64), Image.LANCZOS), dtype=np.float32)
            centre = np.median(centre[19:45, 19:45].reshape(-1, 3), axis=0) / 255.0
            gray = img.convert("L")
            gray.thumbnail((512, 512), Image.LANCZOS)
            keypoints, descriptors = _orb().detectAndCompute(np.asarray(gray), None)
    except Exception as error:  # noqa: BLE001
        print(f"Fingerprint skipped for {image_path}: {error}")
        return None
    return {
        "thumb": np.asarray(thumb, dtype=np.float32).flatten() / 255.0,
        "kp": (keypoints, descriptors),
        "centre": centre,
    }


_ORB = None


def _orb():
    global _ORB
    if _ORB is None:
        import cv2
        _ORB = cv2.ORB_create(nfeatures=1000)
    return _ORB


def keypoint_inliers(a, b):
    """Geometrically consistent keypoint matches between two fingerprints."""
    import cv2

    if a is None or b is None:
        return 0
    (ka, da), (kb, db) = a["kp"], b["kp"]
    if da is None or db is None or len(ka) < 8 or len(kb) < 8:
        return 0
    matches = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(da, db, k=2)
    good = [
        pair[0] for pair in matches
        if len(pair) == 2 and pair[0].distance < 0.75 * pair[1].distance
    ]
    if len(good) < 8:
        return 0
    src = np.float32([ka[m.queryIdx].pt for m in good])
    dst = np.float32([kb[m.trainIdx].pt for m in good])
    _, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
    return int(mask.sum()) if mask is not None else 0


def fingerprint_distance(a, b):
    """Mean absolute thumbnail difference (0 = identical), or None."""
    if a is None or b is None:
        return None
    return float(np.abs(a["thumb"] - b["thumb"]).mean())


def is_same_item(query_print, item_print, feature_similarity):
    """True when two photos show the same wardrobe item (see above)."""
    if query_print is None or item_print is None:
        return False
    colour_gap = float(np.abs(query_print["centre"] - item_print["centre"]).max())
    if colour_gap > EXACT_MAX_COLOUR_DIFFERENCE:
        return False
    if feature_similarity >= EXACT_FEATURE_SIMILARITY:
        return True
    distance = fingerprint_distance(query_print, item_print)
    if (
        distance is not None
        and distance <= EXACT_MAX_PIXEL_DIFFERENCE
        and feature_similarity >= EXACT_PIXEL_MIN_FEATURE_SIMILARITY
    ):
        return True
    return (
        feature_similarity >= EXACT_KEYPOINT_MIN_FEATURE_SIMILARITY
        and keypoint_inliers(query_print, item_print) >= EXACT_MIN_KEYPOINT_INLIERS
    )


def _local_path(image_url):
    """A readable file for a stored image reference, or None."""
    if not image_url:
        return None
    if image_url.startswith(("http://", "https://")):
        cached = storage.local_copy_of(image_url)
        return Path(cached) if cached else None
    if image_url.startswith("/api/uploads/"):
        path = BASE_DIR / "backend" / "uploads" / image_url.replace("/api/uploads/", "", 1)
    else:
        path = Path(image_url)
        if not path.is_absolute():
            path = BASE_DIR / "backend" / path
    return path if path.exists() else None


def _original_of(item):
    return (
        ((item.get("attributes") or {}).get("image_processing") or {})
        .get("original_image")
    )


def find_similar_in_wardrobe(
    query_image_path,
    wardrobe_items,
    top_k=5
):
    """
    Compare an uploaded photo against the user's wardrobe.

    query_image_path: one path, or a list of versions of the SAME photo
    (e.g. [as uploaded, background removed]).

    Each result carries "similarity" (0-1) and "exact_match" (True when
    it is the same picture as that wardrobe item - similarity is then
    exactly 1.0).
    """
    query_paths = (
        [query_image_path] if isinstance(query_image_path, (str, Path))
        else [p for p in query_image_path if p]
    )
    query_features = [extract_feature(str(p)) for p in query_paths]
    query_prints = [image_fingerprint(p) for p in query_paths]

    results = []

    for item in wardrobe_items:
        image_url = item.get("image_path")
        if not image_url:
            continue

        main_path = _local_path(image_url)
        if main_path is None:
            print("Wardrobe image not found:", image_url)
            continue

        try:
            item_feature = extract_feature(str(main_path))
            similarity = max(float(np.dot(q, item_feature)) for q in query_features)

            # Same item? Compare every version of the query photo with
            # the stored picture and the original photo kept at upload.
            item_prints = [image_fingerprint(main_path)]
            original_path = _local_path(_original_of(item))
            if original_path is not None:
                item_prints.append(image_fingerprint(original_path))

            exact = any(
                is_same_item(q, i, similarity)
                for q in query_prints for i in item_prints
            )

            results.append({
                "item_id": item.get("_id"),
                "image": image_url,
                "category": item.get("category"),
                "color": item.get("color"),
                "occasion": item.get("occasion"),
                "similarity": 1.0 if exact else min(similarity, 0.99),
                "exact_match": exact,
            })

        except Exception as e:  # noqa: BLE001
            print(f"Could not process wardrobe image {main_path}: {e}")

    results.sort(
        key=lambda x: (x["exact_match"], x["similarity"]),
        reverse=True
    )
    return results[:top_k]
