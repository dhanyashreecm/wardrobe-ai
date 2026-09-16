from pathlib import Path
import json
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent.parent

DATASET_DIR = BASE_DIR / "dataset" / "indofashion"
OUTPUT_DIR = DATASET_DIR / "processed"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SPLITS = ["train", "val", "test"]


def process_split(split):
    json_file = DATASET_DIR / f"{split}_data.json"

    if not json_file.exists():
        print(f"Missing: {json_file}")
        return

    processed_count = 0
    skipped_count = 0

    print(f"\nProcessing {split}...")

    with open(json_file, "r") as f:

        for line in f:
            try:
                item = json.loads(line)

                image_path = DATASET_DIR / item["image_path"]
                category = item["class_label"]

                if not image_path.exists():
                    skipped_count += 1
                    continue

                # Create category folder
                category_dir = OUTPUT_DIR / category
                category_dir.mkdir(parents=True, exist_ok=True)

                output_path = category_dir / image_path.name

                # Skip if already processed
                if output_path.exists():
                    processed_count += 1
                    continue

                # Open and convert image
                img = Image.open(image_path).convert("RGB")

                # Save processed image
                img.save(output_path, quality=95)

                processed_count += 1

                if processed_count % 1000 == 0:
                    print(
                        f"{split}: {processed_count} processed"
                    )

            except Exception as e:
                skipped_count += 1
                print(
                    f"Error processing {line[:100]}: {e}"
                )

    print(f"\n{split} completed.")
    print(f"Processed: {processed_count}")
    print(f"Skipped: {skipped_count}")


if __name__ == "__main__":

    print("====================================")
    print("IndoFashion Preprocessing")
    print("====================================")

    for split in SPLITS:
        process_split(split)

    print("\nPreprocessing completed.")
    print(f"Output folder: {OUTPUT_DIR}")
