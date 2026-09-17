"""
Retrain the IndoFashion classifier using the OFFICIAL train/val split
instead of a pooled-and-randomly-re-split folder, and evaluate the
result against the untouched official test set before you ever
switch the app over to it.

WHAT THIS CHANGES VS. THE EXISTING train_indofashion_deep.py
---------------------------------------------------------------
1. Official classes (everything in dataset/indofashion/test_data.json
   - the 15 real IndoFashion categories) are trained on
   train_data.json and validated on val_data.json, exactly as the
   dataset's authors intended. test_data.json is NEVER read by this
   script for training or validation - only evaluate_model() (in
   model_eval_utils.py) reads it, strictly for measuring accuracy
   afterwards. This directly targets the suspected root cause of
   unreliable saree/lehenga separation: the current script's random
   80/20 re-split of pooled images risks leaking test images into
   training, which can make a model look more accurate than it is
   while still confusing specific classes.

2. Locally-added classes that AREN'T part of official IndoFashion
   (currently just "shirt" - the dataset has no Western wear) keep
   using the existing processed/<class>/ folder, but with an
   explicit, reproducible train/val/holdout split instead of Keras's
   random validation_split. The holdout slice (see
   model_eval_utils.build_local_holdout) is carved out first and
   excluded from training here, so it's a genuine, never-trained-on
   test set for "shirt" too - not just for the official classes.

3. This warm-starts from your EXISTING trained model
   (dataset/indofashion/indofashion_deep.keras) rather than
   reinitializing from ImageNet weights. That's both faster on a
   MacBook Air M1 and keeps everything the current model already
   learned - "reuse existing feature extraction and trained models"
   as asked, rather than throwing it away. It then fine-tunes the
   WHOLE network end-to-end at a conservatively low learning rate.
   (This script deliberately does not try to guess which layers the
   original training script froze/unfroze by index - fine-tuning
   uniformly at a low LR is simpler and just as safe for a short
   continued-training run.)

4. Saves to a NEW file - dataset/indofashion/indofashion_deep_v2.keras
   - and NEVER touches or deletes indofashion_deep.keras. Nothing in
   this script deletes any existing file.

5. When training finishes, it evaluates BOTH the old and the new
   model with the exact same metric code (model_eval_utils.py) and
   prints them side by side. Whether v2 is actually better is
   something you read off that printed comparison - this script
   does not print any "accuracy improved!" message of its own, on
   purpose, since a claim like that should only ever come from
   looking at real numbers.

HARDWARE
--------
Written for a MacBook Air M1 / 8GB RAM: MobileNetV2 (~3.4M params,
the same backbone the existing model already uses - nothing bigger
is introduced), batch size 16, streamed with tf.data (images are
never all loaded into memory at once), no dataset .cache() (would
hold every image in RAM - skipped deliberately since the exact
dataset size on your machine isn't known ahead of time).

USAGE (run from the project root, inside your existing ai_env):

    python -m backend.train_indofashion_deep_v2

    # override defaults if you want to experiment:
    python -m backend.train_indofashion_deep_v2 --epochs 15 --batch-size 8

    # skip the end-of-run comparison (e.g. if you want to run
    # evaluate_indofashion_classifier.py yourself later instead):
    python -m backend.train_indofashion_deep_v2 --skip-comparison

This can take a while depending on how many images you have - it
prints progress per epoch as Keras normally does. Nothing here
touches your MongoDB data or the Flask app; app.py keeps using the
original model until you deliberately change MODEL_PATH in
backend/indofashion_classifier.py to point at the v2 file, which you
should only do after reading the comparison this script prints.
"""

import argparse
import json
import random

import numpy as np
import tensorflow as tf

from backend.model_eval_utils import (
    DATASET_DIR,
    DEFAULT_MODEL_PATH,
    IMAGE_SIZE,
    OFFICIAL_TRAIN_JSON,
    OFFICIAL_VAL_JSON,
    _LOCAL_IMAGES_CANDIDATES,
    _read_jsonl,
    _resolve_image_path,
    build_local_holdout,
    evaluate_model,
    load_class_names,
    official_classes,
    print_report,
)

# ============================================================
# HYPERPARAMETERS - deliberately modest, tuned for a MacBook Air
# M1 with 8GB RAM rather than for a GPU box. Change via CLI flags
# below instead of editing these if you just want to experiment.
# ============================================================

SEED = 42
BATCH_SIZE = 16
MAX_EPOCHS = 30
FINE_TUNE_LEARNING_RATE = 1e-5
EARLY_STOPPING_PATIENCE = 5
REDUCE_LR_PATIENCE = 2

# Of the local classes' NON-holdout images (holdout is carved out by
# model_eval_utils.build_local_holdout and never seen here), this
# fraction goes to validation and the rest to training.
LOCAL_VAL_FRACTION = 0.15

NEW_MODEL_PATH = DATASET_DIR / "indofashion_deep_v2.keras"


def _set_seeds():
    random.seed(SEED)
    np.random.seed(SEED)
    tf.random.set_seed(SEED)


# ============================================================
# BUILDING THE DATASET
#
# Both official and local-class images are collected as plain
# (path, label) lists first, then turned into ONE tf.data pipeline -
# this keeps the "how do I split this fairly and reproducibly"
# logic in plain Python (easy to read and to unit-test by eye) and
# leaves tf.data responsible only for the mechanical part: loading,
# resizing, batching, shuffling.
# ============================================================

def _official_split(class_names):
    valid_classes = official_classes(class_names)

    def collect(json_path):
        paths, labels = [], []
        missing = 0
        for record in _read_jsonl(json_path):
            label = record["class_label"]
            if label not in valid_classes:
                continue
            path = _resolve_image_path(record)
            if not path.exists():
                missing += 1
                continue
            paths.append(path)
            labels.append(label)
        if missing:
            print(f"  ({missing} images listed in {json_path.name} not found on disk, skipped)")
        return paths, labels

    train_paths, train_labels = collect(OFFICIAL_TRAIN_JSON)
    val_paths, val_labels = collect(OFFICIAL_VAL_JSON)

    return train_paths, train_labels, val_paths, val_labels


def _local_split(class_names):
    """
    Train/val split for locally-added classes (e.g. "shirt"),
    explicitly excluding whatever build_local_holdout() reserves for
    testing, split deterministically (sorted filenames + fixed seed)
    rather than relying on Keras's random validation_split.
    """

    holdout_paths, _ = build_local_holdout(class_names)
    holdout_set = {str(p) for p in holdout_paths}

    images_root = next((p for p in _LOCAL_IMAGES_CANDIDATES if p.exists()), None)
    valid_classes = official_classes(class_names)
    local_classes = [c for c in class_names if c not in valid_classes]

    train_paths, train_labels = [], []
    val_paths, val_labels = [], []

    if images_root is None or not local_classes:
        return train_paths, train_labels, val_paths, val_labels

    rng = random.Random(SEED)

    for class_name in local_classes:
        class_dir = images_root / class_name
        if not class_dir.exists():
            continue

        files = sorted(
            p for p in class_dir.iterdir()
            if p.suffix.lower() in (".jpg", ".jpeg", ".png")
        )
        trainable_files = [p for p in files if str(p) not in holdout_set]

        shuffled = trainable_files[:]
        rng.shuffle(shuffled)

        val_count = max(1, int(len(shuffled) * LOCAL_VAL_FRACTION)) if shuffled else 0
        class_val = shuffled[:val_count]
        class_train = shuffled[val_count:]

        train_paths.extend(class_train)
        train_labels.extend([class_name] * len(class_train))
        val_paths.extend(class_val)
        val_labels.extend([class_name] * len(class_val))

    return train_paths, train_labels, val_paths, val_labels


def _make_dataset(paths, labels, class_names, shuffle, batch_size):
    label_to_index = {name: i for i, name in enumerate(class_names)}
    indices = [label_to_index[label] for label in labels]

    path_strs = [str(p) for p in paths]

    def load_and_resize(path, label):
        raw = tf.io.read_file(path)
        image = tf.image.decode_image(raw, channels=3, expand_animations=False)
        # decode_image doesn't set a static shape, which tf.image.resize
        # needs inside a tf.data.map graph - set it explicitly first.
        image.set_shape([None, None, 3])
        image = tf.image.resize(image, IMAGE_SIZE)
        image.set_shape(IMAGE_SIZE + (3,))
        return image, label

    ds = tf.data.Dataset.from_tensor_slices((path_strs, indices))

    if shuffle:
        ds = ds.shuffle(buffer_size=max(len(path_strs), 1), seed=SEED)

    ds = ds.map(load_and_resize, num_parallel_calls=tf.data.AUTOTUNE)
    ds = ds.batch(batch_size)
    ds = ds.prefetch(tf.data.AUTOTUNE)

    return ds


def build_datasets(class_names, batch_size):
    print("Collecting official-class images (train_data.json / val_data.json)...")
    off_train_p, off_train_l, off_val_p, off_val_l = _official_split(class_names)
    print(f"  official train: {len(off_train_p)} images, official val: {len(off_val_p)} images")

    print("Collecting local-class images (e.g. shirt), excluding the held-out test slice...")
    loc_train_p, loc_train_l, loc_val_p, loc_val_l = _local_split(class_names)
    print(f"  local train: {len(loc_train_p)} images, local val: {len(loc_val_p)} images")

    train_paths = off_train_p + loc_train_p
    train_labels = off_train_l + loc_train_l
    val_paths = off_val_p + loc_val_p
    val_labels = off_val_l + loc_val_l

    if not train_paths:
        raise RuntimeError(
            "No training images were found at all. Check that "
            f"{OFFICIAL_TRAIN_JSON} exists and that DATASET_DIR in "
            "model_eval_utils.py points at the right folder."
        )

    train_ds = _make_dataset(train_paths, train_labels, class_names, shuffle=True, batch_size=batch_size)
    val_ds = _make_dataset(val_paths, val_labels, class_names, shuffle=False, batch_size=batch_size)

    return train_ds, val_ds, train_labels


def compute_class_weights(train_labels, class_names):
    from sklearn.utils.class_weight import compute_class_weight

    label_to_index = {name: i for i, name in enumerate(class_names)}
    present = sorted(set(train_labels))
    indices = np.array([label_to_index[label] for label in train_labels])

    weights = compute_class_weight(
        class_weight="balanced",
        classes=np.array([label_to_index[c] for c in present]),
        y=indices,
    )

    # Cap extreme ratios so one very small class can't dominate the
    # loss and destabilize training on top of an already-trained
    # model - a soft safety net, not a hard requirement.
    weights = np.clip(weights, 0.25, 4.0)

    return {label_to_index[c]: float(w) for c, w in zip(present, weights)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--epochs", type=int, default=MAX_EPOCHS)
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument("--lr", type=float, default=FINE_TUNE_LEARNING_RATE)
    parser.add_argument(
        "--skip-comparison", action="store_true",
        help="Don't run the old-vs-new evaluation comparison at the end."
    )
    args = parser.parse_args()

    _set_seeds()

    class_names = load_class_names()
    print(f"Classes ({len(class_names)}): {class_names}")

    train_ds, val_ds, train_labels = build_datasets(class_names, args.batch_size)
    class_weights = compute_class_weights(train_labels, class_names)
    print(f"Class weights: {class_weights}")

    if not DEFAULT_MODEL_PATH.exists():
        raise FileNotFoundError(
            f"Existing model not found at {DEFAULT_MODEL_PATH} - "
            "this script warm-starts from it and expects it to "
            "already exist. If you're intentionally training from "
            "scratch, that's a different script; this one is only "
            "for continuing/correcting an existing model."
        )

    print(f"Loading existing model to warm-start from: {DEFAULT_MODEL_PATH}")
    model = tf.keras.models.load_model(DEFAULT_MODEL_PATH, compile=False)

    if model.output_shape[-1] != len(class_names):
        raise RuntimeError(
            f"The existing model's output layer has "
            f"{model.output_shape[-1]} classes but class_names.json "
            f"lists {len(class_names)}. This script only fine-tunes "
            "an existing model with the SAME class list - it does "
            "not add/remove/relabel classes. Resolve that mismatch "
            "before retraining."
        )

    # Fine-tune the whole network end-to-end at a low learning rate,
    # rather than guessing which layers the original script had
    # frozen. Since we're warm-starting from an already-trained
    # model (not from raw ImageNet weights), a small uniform LR is
    # enough to correct it on the properly-split data without
    # wrecking what it already learned.
    model.trainable = True

    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=args.lr),
        loss=tf.keras.losses.SparseCategoricalCrossentropy(),
        metrics=["accuracy"],
    )

    callbacks = [
        tf.keras.callbacks.EarlyStopping(
            monitor="val_loss",
            patience=EARLY_STOPPING_PATIENCE,
            restore_best_weights=True,
        ),
        tf.keras.callbacks.ReduceLROnPlateau(
            monitor="val_loss",
            factor=0.5,
            patience=REDUCE_LR_PATIENCE,
            min_lr=1e-7,
        ),
    ]

    print(f"\nFine-tuning for up to {args.epochs} epochs (early stopping may end it sooner)...")
    model.fit(
        train_ds,
        validation_data=val_ds,
        epochs=args.epochs,
        class_weight=class_weights,
        callbacks=callbacks,
    )

    NEW_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    model.save(NEW_MODEL_PATH)
    print(f"\nSaved new model to {NEW_MODEL_PATH} (the original {DEFAULT_MODEL_PATH} was not modified).")

    if args.skip_comparison:
        return

    print("\nEvaluating BEFORE (current production model) vs AFTER (v2) on the same held-out data...")
    before = evaluate_model(DEFAULT_MODEL_PATH)
    after = evaluate_model(NEW_MODEL_PATH)

    print_report(before, title="BEFORE (current indofashion_deep.keras)")
    print_report(after, title="AFTER (new indofashion_deep_v2.keras)")

    print("\n=== SIDE-BY-SIDE ===")
    print(f"Overall accuracy: {before['accuracy']*100:.2f}% -> {after['accuracy']*100:.2f}%")

    for label in sorted(set(before["per_class"]) | set(after["per_class"])):
        b = before["per_class"].get(label, {}).get("f1")
        a = after["per_class"].get(label, {}).get("f1")
        if b is not None and a is not None:
            print(f"  {label:18s} F1: {b:.3f} -> {a:.3f}")

    print(
        "\nThis comparison is the actual evidence for whether v2 is "
        "better - decide from these numbers, not from this script's "
        "wording. If AFTER looks better, update MODEL_PATH in "
        "backend/indofashion_classifier.py to point at "
        f"{NEW_MODEL_PATH} yourself; this script does not do that "
        "automatically."
    )


if __name__ == "__main__":
    main()
