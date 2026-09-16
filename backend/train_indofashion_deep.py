import os
import json
import tensorflow as tf
from tensorflow.keras import layers, models
from tensorflow.keras.applications import MobileNetV2
from tensorflow.keras.applications.mobilenet_v2 import preprocess_input


# ============================================================
# SETTINGS
# ============================================================

DATASET_DIR = "dataset/indofashion/processed"
MODEL_FILE = "dataset/indofashion/indofashion_deep.keras"
CLASS_FILE = "dataset/indofashion/class_names.json"

IMG_SIZE = (224, 224)
BATCH_SIZE = 32
SEED = 42

INITIAL_EPOCHS = 5
FINE_TUNE_EPOCHS = 5


# ============================================================
# LOAD DATASET
# ============================================================

print("=" * 60)
print("LOADING INDOfASHION DATASET")
print("=" * 60)

train_ds = tf.keras.utils.image_dataset_from_directory(
    DATASET_DIR,
    validation_split=0.20,
    subset="training",
    seed=SEED,
    image_size=IMG_SIZE,
    batch_size=BATCH_SIZE,
    label_mode="int"
)

validation_ds = tf.keras.utils.image_dataset_from_directory(
    DATASET_DIR,
    validation_split=0.20,
    subset="validation",
    seed=SEED,
    image_size=IMG_SIZE,
    batch_size=BATCH_SIZE,
    label_mode="int"
)

class_names = train_ds.class_names
num_classes = len(class_names)

print()
print("Classes:")
for i, name in enumerate(class_names):
    print(f"{i}: {name}")

print()
print("Number of classes:", num_classes)


# ============================================================
# SAVE CLASS NAMES
# ============================================================

with open(CLASS_FILE, "w") as f:
    json.dump(class_names, f, indent=2)

print()
print("Class names saved to:")
print(CLASS_FILE)


# ============================================================
# PERFORMANCE
# ============================================================

AUTOTUNE = tf.data.AUTOTUNE

train_ds = train_ds.prefetch(AUTOTUNE)
validation_ds = validation_ds.prefetch(AUTOTUNE)


# ============================================================
# DATA AUGMENTATION
# ============================================================

data_augmentation = tf.keras.Sequential([
    layers.RandomFlip("horizontal"),
    layers.RandomRotation(0.05),
    layers.RandomZoom(0.10),
])


# ============================================================
# BASE MODEL
# ============================================================

print()
print("=" * 60)
print("LOADING MOBILENETV2")
print("=" * 60)

base_model = MobileNetV2(
    weights="imagenet",
    include_top=False,
    input_shape=(224, 224, 3)
)

base_model.trainable = False


# ============================================================
# BUILD MODEL
# ============================================================

inputs = layers.Input(shape=(224, 224, 3))

x = data_augmentation(inputs)
x = preprocess_input(x)

x = base_model(
    x,
    training=False
)

x = layers.GlobalAveragePooling2D()(x)

x = layers.Dropout(0.30)(x)

outputs = layers.Dense(
    num_classes,
    activation="softmax"
)(x)

model = models.Model(
    inputs,
    outputs
)


# ============================================================
# INITIAL TRAINING
# ============================================================

print()
print("=" * 60)
print("INITIAL TRAINING")
print("=" * 60)

model.compile(
    optimizer=tf.keras.optimizers.Adam(
        learning_rate=0.001
    ),
    loss="sparse_categorical_crossentropy",
    metrics=["accuracy"]
)

model.summary()

history_initial = model.fit(
    train_ds,
    validation_data=validation_ds,
    epochs=INITIAL_EPOCHS
)


# ============================================================
# FINE TUNING
# ============================================================

print()
print("=" * 60)
print("FINE-TUNING MOBILENETV2")
print("=" * 60)

base_model.trainable = True

# Freeze the earlier layers.
# Fine-tune only the upper layers.
fine_tune_from = 100

for layer in base_model.layers[:fine_tune_from]:
    layer.trainable = False

model.compile(
    optimizer=tf.keras.optimizers.Adam(
        learning_rate=1e-5
    ),
    loss="sparse_categorical_crossentropy",
    metrics=["accuracy"]
)

history_fine = model.fit(
    train_ds,
    validation_data=validation_ds,
    epochs=FINE_TUNE_EPOCHS
)


# ============================================================
# SAVE MODEL
# ============================================================

print()
print("=" * 60)
print("SAVING MODEL")
print("=" * 60)

model.save(MODEL_FILE)

print("Model saved to:")
print(MODEL_FILE)

print()
print("FINAL VALIDATION")

loss, accuracy = model.evaluate(
    validation_ds,
    verbose=1
)

print()
print(f"Validation accuracy: {accuracy * 100:.2f}%")

print()
print("=" * 60)
print("TRAINING COMPLETE")
print("=" * 60)
