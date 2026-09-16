import os
import numpy as np

from collections import Counter
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report
import joblib


FEATURES_FILE = "dataset/indofashion/features.npy"
PATHS_FILE = "dataset/indofashion/feature_paths.npy"
MODEL_FILE = "dataset/indofashion/indofashion_classifier.joblib"


print("Loading IndoFashion features...")

X = np.load(FEATURES_FILE)
paths = np.load(PATHS_FILE, allow_pickle=True)

print("Features:", X.shape)
print("Paths:", len(paths))


# Extract category from folder name
y = np.array([
    os.path.basename(os.path.dirname(str(path)))
    for path in paths
])


print("\nCategories:")
for category, count in sorted(Counter(y).items()):
    print(f"{category}: {count}")


# Split dataset
X_train, X_test, y_train, y_test = train_test_split(
    X,
    y,
    test_size=0.20,
    random_state=42,
    stratify=y
)

print("\nTraining samples:", len(X_train))
print("Testing samples:", len(X_test))


print("\nTraining classifier...")

model = LogisticRegression(
    max_iter=1000,
    solver="lbfgs",
    multi_class="auto"
)

model.fit(X_train, y_train)


print("\nEvaluating classifier...")

predictions = model.predict(X_test)

accuracy = accuracy_score(y_test, predictions)

print("\nAccuracy:", accuracy)
print("\nClassification Report:")
print(classification_report(y_test, predictions))


print("\nSaving classifier...")

joblib.dump(model, MODEL_FILE)

print("Classifier saved to:")
print(MODEL_FILE)

print("\nDONE.")
