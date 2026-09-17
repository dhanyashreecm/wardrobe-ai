"""
Shared evaluation logic for the IndoFashion classifier.

Both evaluate_indofashion_classifier.py (ad-hoc "how good is this
saved model, really?") and train_indofashion_deep_v2.py (which
prints an old-model-vs-new-model comparison at the end of training)
import from here, so there is exactly ONE place that defines what
"accuracy" means for this project - no risk of the two scripts
quietly measuring different things and giving numbers that can't be
compared.

WHY THIS EXISTS
----------------
The project's current training script (train_indofashion_deep.py)
builds its train/validation split by pooling every image into
processed/<class_label>/ and then asking Keras for a random 80/20
split (image_dataset_from_directory(..., validation_split=0.2)).
The official IndoFashion dataset already ships its own held-out
test_data.json, produced by the dataset's authors specifically so a
model's real accuracy can be checked on images it never trained on.
Pooling-and-re-splitting bypasses that: there is a real risk that
images which the official split reserved for testing ended up inside
the 80% used for training instead, which would make the model look
better than it actually is on paper.

This module always evaluates against the OFFICIAL test_data.json
(for the 15 official IndoFashion classes) plus a held-out slice of
any LOCAL classes this project added on top of the official dataset
(currently just "shirt" - IndoFashion has no Western wear at all).
That held-out slice is carved out deterministically (see
build_local_holdout()) and is never used for training, so it is a
genuine test set for those classes too.

Nothing here retrains, deletes, or overwrites anything. It only
reads images and a saved .keras model and reports what it sees.
"""

import json
import random
from pathlib import Path

import numpy as np
import tensorflow as tf
from tensorflow.keras.utils import load_img, img_to_array


# ============================================================
# PATHS - matches backend/indofashion_classifier.py exactly, so
# "the model currently serving the app" and "the model this script
# is evaluating" are guaranteed to be the same file unless you pass
# --model explicitly.
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent
DATASET_DIR = BASE_DIR / "dataset" / "indofashion"

DEFAULT_MODEL_PATH = DATASET_DIR / "indofashion_deep.keras"
CLASS_NAMES_PATH = DATASET_DIR / "class_names.json"

# Where the official dataset's JSONL metadata files live. If your
# copy of the dataset keeps these somewhere else, change this one
# constant rather than hunting through the rest of the script.
OFFICIAL_TEST_JSON = DATASET_DIR / "test_data.json"
OFFICIAL_TRAIN_JSON = DATASET_DIR / "train_data.json"
OFFICIAL_VAL_JSON = DATASET_DIR / "val_data.json"

# Locally-added classes (e.g. "shirt") live as plain image folders,
# same layout as preprocess_indofashion.py already writes:
# <LOCAL_IMAGES_ROOT>/<class_name>/*.jpg. The first of these that
# actually exists on disk is used.
_LOCAL_IMAGES_CANDIDATES = [
    DATASET_DIR / "processed",
    BASE_DIR / "dataset" / "processed",
]

IMAGE_SIZE = (224, 224)

# Fixed seed so "carve out a held-out slice of the local classes" and
# any shuffling in this module gives the same split every time it's
# run - required for the "reproducible" instruction. This does NOT
# need to match training's seed; it only needs to be consistent with
# itself across runs so the same images are always the held-out ones.
HOLDOUT_SEED = 1234
HOLDOUT_FRACTION = 0.15  # per local class, never trained on


# ============================================================
# CLASS NAMES
# ============================================================

def load_class_names():
    with open(CLASS_NAMES_PATH, "r") as f:
        class_names = json.load(f)

    if isinstance(class_names, dict):
        class_names = [class_names[str(i)] for i in range(len(class_names))]

    return class_names


def _official_classes(class_names):
    """
    Which of this project's classes actually appear in the official
    IndoFashion test_data.json. Anything else (currently: "shirt")
    is treated as a locally-added class instead - see
    build_local_holdout(). Computed from the real file rather than a
    hardcoded list, so this stays correct even if the official class
    set is ever different from what's assumed here.
    """

    if not OFFICIAL_TEST_JSON.exists():
        return set()

    seen = set()
    for record in _read_jsonl(OFFICIAL_TEST_JSON):
        seen.add(record["class_label"])

    return {c for c in class_names if c in seen}


def official_classes(class_names):
    """Public wrapper around _official_classes() for other scripts."""
    return _official_classes(class_names)


# ============================================================
# READING THE OFFICIAL JSONL FILES
# ============================================================

def _read_jsonl(path):
    """
    IndoFashion's official metadata files are JSON Lines (one JSON
    object per line). A couple of dataset mirrors ship a single JSON
    array instead, so this falls back to that if line-by-line
    parsing fails on the first line.
    """

    with open(path, "r") as f:
        first_line = f.readline()
        f.seek(0)

        try:
            parsed_first_line = json.loads(first_line)
            # A JSONL record is always an object; if the first line
            # parses as a JSON array instead (e.g. a single-line,
            # non-pretty-printed array file), this is the
            # whole-file-is-one-array case, not JSONL.
            is_jsonl = isinstance(parsed_first_line, dict)
        except json.JSONDecodeError:
            is_jsonl = False

        if is_jsonl:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)
        else:
            for record in json.load(f):
                yield record


def _resolve_image_path(record):
    """
    image_path in the official files is relative to the dataset
    root (the folder the json file itself lives in). Resolved here
    in one place so a layout difference only needs a fix here.
    """

    raw = record["image_path"]
    candidate = DATASET_DIR / raw

    if candidate.exists():
        return candidate

    # Some mirrors nest an extra "images/" prefix or drop it -
    # try both before giving up.
    alt = DATASET_DIR / Path(raw).name
    if alt.exists():
        return alt

    return candidate  # doesn't exist; caller reports this clearly


def build_official_test_set(class_names):
    """
    (image_paths, labels) for every image in the official
    test_data.json whose class is one this project actually trains
    for. Never touched during training - see the module docstring.
    """

    if not OFFICIAL_TEST_JSON.exists():
        return [], []

    official_classes = _official_classes(class_names)

    image_paths, labels = [], []
    missing = 0

    for record in _read_jsonl(OFFICIAL_TEST_JSON):
        label = record["class_label"]
        if label not in official_classes:
            continue

        path = _resolve_image_path(record)
        if not path.exists():
            missing += 1
            continue

        image_paths.append(path)
        labels.append(label)

    if missing:
        print(
            f"WARNING: {missing} image(s) listed in test_data.json "
            f"could not be found on disk under {DATASET_DIR} and "
            "were skipped. If this number is large, check "
            "DATASET_DIR / _resolve_image_path() at the top of "
            "model_eval_utils.py against your actual folder layout."
        )

    return image_paths, labels


def build_local_holdout(class_names):
    """
    (image_paths, labels) for a deterministic, never-trained-on
    slice of any class this project added on top of the official
    IndoFashion classes (currently just "shirt"). Chosen by sorting
    each class's filenames and taking a fixed-seed random sample of
    HOLDOUT_FRACTION of them - sorting first means the sample is the
    same every run regardless of filesystem listing order.

    train_indofashion_deep_v2.py MUST exclude these exact images
    from training (it calls this same function to know which ones
    to skip), or this stops being a real test set.
    """

    official_classes = _official_classes(class_names)
    local_classes = [c for c in class_names if c not in official_classes]

    if not local_classes:
        return [], []

    images_root = next(
        (p for p in _LOCAL_IMAGES_CANDIDATES if p.exists()),
        None
    )

    if images_root is None:
        print(
            "NOTE: no local processed-images folder found "
            f"(looked in: {[str(p) for p in _LOCAL_IMAGES_CANDIDATES]}) "
            f"- skipping evaluation of local-only classes {local_classes}. "
            "If your locally-added images (e.g. shirt) live somewhere "
            "else, update _LOCAL_IMAGES_CANDIDATES in "
            "model_eval_utils.py."
        )
        return [], []

    rng = random.Random(HOLDOUT_SEED)
    image_paths, labels = [], []

    for class_name in local_classes:
        class_dir = images_root / class_name
        if not class_dir.exists():
            print(f"NOTE: no folder for local class '{class_name}' under {images_root}")
            continue

        files = sorted(
            p for p in class_dir.iterdir()
            if p.suffix.lower() in (".jpg", ".jpeg", ".png")
        )

        if not files:
            continue

        holdout_count = max(1, int(len(files) * HOLDOUT_FRACTION))
        holdout_files = rng.sample(files, holdout_count)

        image_paths.extend(holdout_files)
        labels.extend([class_name] * len(holdout_files))

    return image_paths, labels


# ============================================================
# INFERENCE - identical preprocessing to
# backend/indofashion_classifier.py's preprocess_image(), on
# purpose: whatever this script measures must be the exact same
# pipeline the live app actually runs, not a close approximation.
# ============================================================

def preprocess_image(image_path):
    img = load_img(image_path, target_size=IMAGE_SIZE)
    img_array = img_to_array(img)
    return np.expand_dims(img_array, axis=0)


def predict_batch(model, image_paths, class_names, batch_size=16, verbose=True):
    """
    Runs the model over image_paths and returns a list of predicted
    class-name strings, same order as image_paths. Batched (not one
    image at a time) so this stays reasonably quick on a MacBook
    Air's CPU/Metal backend without needing a large batch size that
    would strain 8GB of RAM.
    """

    predictions = []
    total = len(image_paths)

    for start in range(0, total, batch_size):
        batch_paths = image_paths[start:start + batch_size]
        batch = np.vstack([preprocess_image(p) for p in batch_paths])

        probs = model.predict(batch, verbose=0)
        predicted_indices = np.argmax(probs, axis=1)
        predictions.extend(class_names[i] for i in predicted_indices)

        if verbose and (start // batch_size) % 10 == 0:
            print(f"  evaluated {min(start + batch_size, total)}/{total}")

    return predictions


# ============================================================
# METRICS
# ============================================================

def evaluate_model(model_path, verbose=True):
    """
    Loads model_path, runs it over the official test set plus the
    local-class holdout, and returns a dict:
      {
        "model_path": str,
        "n_images": int,
        "accuracy": float,
        "per_class": {class_name: {"precision", "recall", "f1", "support"}},
        "confusion_matrix": {"labels": [...], "matrix": [[...]]},
        "confused_pairs": [(true_class, predicted_class, count), ...]
      }
    Raises FileNotFoundError early with a clear message if the model
    or the dataset files can't be found, rather than failing deep
    inside a metrics call.
    """

    try:
        from sklearn.metrics import (
            classification_report,
            confusion_matrix as sk_confusion_matrix,
        )
    except ImportError as e:
        raise ImportError(
            "scikit-learn is required for evaluation metrics but "
            "isn't installed in this environment. Install it with:\n"
            "  pip install scikit-learn"
        ) from e

    model_path = Path(model_path)
    if not model_path.exists():
        raise FileNotFoundError(f"No model found at {model_path}")

    class_names = load_class_names()

    test_paths, test_labels = build_official_test_set(class_names)
    local_paths, local_labels = build_local_holdout(class_names)

    image_paths = test_paths + local_paths
    true_labels = test_labels + local_labels

    if not image_paths:
        raise FileNotFoundError(
            "No evaluation images were found at all (neither the "
            f"official test set at {OFFICIAL_TEST_JSON} nor a local "
            "holdout). Nothing to evaluate against - check "
            "DATASET_DIR at the top of model_eval_utils.py."
        )

    if verbose:
        print(f"Loading model: {model_path}")

    model = tf.keras.models.load_model(model_path, compile=False)

    if verbose:
        print(
            f"Evaluating on {len(image_paths)} images "
            f"({len(test_paths)} official test + {len(local_paths)} "
            "local holdout)..."
        )

    predicted_labels = predict_batch(model, image_paths, class_names, verbose=verbose)

    labels_present = sorted(set(true_labels) | set(predicted_labels))

    report = classification_report(
        true_labels, predicted_labels,
        labels=labels_present,
        output_dict=True,
        zero_division=0,
    )

    cm = sk_confusion_matrix(true_labels, predicted_labels, labels=labels_present)

    accuracy = report.pop("accuracy", None)
    if accuracy is None:
        # older sklearn versions put it differently; compute directly
        accuracy = sum(
            1 for t, p in zip(true_labels, predicted_labels) if t == p
        ) / len(true_labels)

    per_class = {
        label: {
            "precision": report[label]["precision"],
            "recall": report[label]["recall"],
            "f1": report[label]["f1-score"],
            "support": int(report[label]["support"]),
        }
        for label in labels_present
        if label in report
    }

    # Off-diagonal confusion pairs, sorted by how often they happen -
    # this is what directly answers "is saree being confused for
    # lehenga (or vice versa), and how much?"
    confused_pairs = []
    for i, true_label in enumerate(labels_present):
        for j, pred_label in enumerate(labels_present):
            if i != j and cm[i][j] > 0:
                confused_pairs.append((true_label, pred_label, int(cm[i][j])))
    confused_pairs.sort(key=lambda triple: triple[2], reverse=True)

    return {
        "model_path": str(model_path),
        "n_images": len(image_paths),
        "n_official_test": len(test_paths),
        "n_local_holdout": len(local_paths),
        "accuracy": float(accuracy),
        "per_class": per_class,
        "confusion_matrix": {
            "labels": labels_present,
            "matrix": cm.tolist(),
        },
        "confused_pairs": confused_pairs,
    }


def print_report(result, title=None):
    if title:
        print(f"\n=== {title} ===")

    print(f"Model: {result['model_path']}")
    print(
        f"Evaluated on {result['n_images']} images "
        f"({result['n_official_test']} official test + "
        f"{result['n_local_holdout']} local holdout)"
    )
    print(f"Overall accuracy: {result['accuracy'] * 100:.2f}%\n")

    print(f"{'class':22s} {'precision':>10s} {'recall':>10s} {'f1':>10s} {'support':>8s}")
    for label, m in sorted(result["per_class"].items()):
        print(
            f"{label:22s} {m['precision']:10.3f} {m['recall']:10.3f} "
            f"{m['f1']:10.3f} {m['support']:8d}"
        )

    print("\nMost-confused class pairs (true -> predicted : count):")
    if not result["confused_pairs"]:
        print("  (none - every prediction matched its true label)")
    for true_label, pred_label, count in result["confused_pairs"][:15]:
        print(f"  {true_label:18s} -> {pred_label:18s} : {count}")

    saree_lehenga = [
        (t, p, c) for t, p, c in result["confused_pairs"]
        if {t, p} == {"saree", "lehenga"}
    ]
    if saree_lehenga:
        print("\nSaree/Lehenga confusion specifically:")
        for t, p, c in saree_lehenga:
            print(f"  {t} misread as {p}: {c} time(s)")
    elif "saree" in result["per_class"] and "lehenga" in result["per_class"]:
        print("\nSaree/Lehenga confusion specifically: none found in this run.")
