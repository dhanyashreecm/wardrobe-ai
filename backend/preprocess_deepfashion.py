from pathlib import Path
from PIL import Image
import numpy as np

# Dataset paths
DATASET = Path("dataset/deepfashion")
IMAGE_DIR = DATASET / "images"
MASK_DIR = DATASET / "masks"

# Output directory
OUTPUT_DIR = DATASET / "processed"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def remove_background(image_path, mask_path, output_path):
    """
    Keep the segmented region from the original image
    and make the rest of the image black.
    """

    image = Image.open(image_path).convert("RGB")
    mask = Image.open(mask_path).convert("L")

    image_array = np.array(image)
    mask_array = np.array(mask)

    # Any non-zero mask pixel is treated as foreground
    foreground = mask_array > 0

    # Create black background
    result = np.zeros_like(image_array)

    # Keep only the foreground pixels
    result[foreground] = image_array[foreground]

    # Save result
    result_image = Image.fromarray(result)
    result_image.save(output_path)


def main():
    images = sorted(IMAGE_DIR.glob("*.jpg"))

    print("=" * 50)
    print("DEEPFASHION PREPROCESSING")
    print("=" * 50)

    print(f"Images found: {len(images)}")
    print(f"Output directory: {OUTPUT_DIR}")

    processed = 0
    skipped = 0

    for image_path in images:

        mask_path = MASK_DIR / f"{image_path.stem}.png"

        if not mask_path.exists():
            skipped += 1
            continue

        output_path = OUTPUT_DIR / image_path.name

        try:
            remove_background(
                image_path,
                mask_path,
                output_path
            )

            processed += 1

        except Exception as e:
            print(f"Error processing {image_path.name}: {e}")
            skipped += 1

    print("\nProcessing complete.")
    print(f"Processed: {processed}")
    print(f"Skipped:   {skipped}")


if __name__ == "__main__":
    main()