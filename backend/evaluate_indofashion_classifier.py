"""
Evaluate a saved IndoFashion model against real, never-trained-on
test data and print per-class precision/recall/F1 plus a confusion
matrix - including a specific saree/lehenga breakdown.

WHY THIS SCRIPT EXISTS
-----------------------
Up to now, this project has never actually measured the classifier's
per-class accuracy - only the overall training/validation accuracy
Keras prints during fit(), which (per model_eval_utils.py's
docstring) was computed on a random re-split of pooled images rather
than the official held-out test set. That number can look fine even
while specific classes - like saree vs. lehenga - are being confused
constantly. This script is how you find out, honestly, before
assuming a fix worked.

USAGE (run from the project root, inside your existing ai_env / the
virtualenv that already has tensorflow installed - this reuses your
existing environment, no new dependencies beyond scikit-learn, which
is a small, standard package):

    python -m backend.evaluate_indofashion_classifier

    # evaluate a different saved model, e.g. a v2 candidate:
    python -m backend.evaluate_indofashion_classifier --model dataset/indofashion/indofashion_deep_v2.keras

    # also save the full report (all numbers, not just what's printed)
    # as JSON:
    python -m backend.evaluate_indofashion_classifier --save-json dataset/indofashion/eval_reports/baseline.json

This DOES NOT modify, retrain, or delete anything - it only loads a
model (read-only) and runs it over images to see what it predicts.
"""

import argparse
import json
from pathlib import Path

from backend.model_eval_utils import (
    DEFAULT_MODEL_PATH,
    evaluate_model,
    print_report,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        default=str(DEFAULT_MODEL_PATH),
        help="Path to the .keras model to evaluate "
             f"(default: the model app.py currently serves, {DEFAULT_MODEL_PATH})",
    )
    parser.add_argument(
        "--save-json",
        default=None,
        help="Optional path to also write the full numeric report as JSON.",
    )
    args = parser.parse_args()

    result = evaluate_model(args.model)
    print_report(result, title="IndoFashion classifier evaluation")

    if args.save_json:
        out_path = Path(args.save_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(result, f, indent=2)
        print(f"\nFull report written to {out_path}")


if __name__ == "__main__":
    main()
