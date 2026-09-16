from pathlib import Path
from PIL import Image
import numpy as np

# Dataset paths
DATASET = Path("dataset/deepfashion")
IMAGE_DIR = DATASET / "images"
MASK_DIR = DATASET / "masks"


def main():
    # Find all images
    images = sorted(IMAGE_DIR.glob("*.jpg"))
    masks = sorted(MASK_DIR.glob("*.png"))

    print("=" * 50)
    print("DEEPFASHION DATASET INSPECTION")
    print("=" * 50)

    print(f"Images found : {len(images)}")
    print(f"Masks found  : {len(masks)}")

    # Check matching image-mask pairs
    image_names = {image.stem for image in images}
    mask_names = {mask.stem for mask in masks}

    matched = image_names & mask_names
    missing_masks = image_names - mask_names
    missing_images = mask_names - image_names

    print(f"Matched pairs: {len(matched)}")
    print(f"Images without masks: {len(missing_masks)}")
    print(f"Masks without images: {len(missing_images)}")

    # Inspect one sample
    if images:
        image_path = images[0]
        mask_path = MASK_DIR / f"{image_path.stem}.png"

        print("\n--- SAMPLE ---")
        print(f"Image: {image_path.name}")
        print(f"Mask : {mask_path.name}")

        image = Image.open(image_path)
        mask = Image.open(mask_path)

        print(f"Image mode: {image.mode}")
        print(f"Image size: {image.size}")

        print(f"Mask mode : {mask.mode}")
        print(f"Mask size : {mask.size}")

        mask_array = np.array(mask)

        print(f"Mask values: {np.unique(mask_array)}")
        print(f"Mask min   : {mask_array.min()}")
        print(f"Mask max   : {mask_array.max()}")

    print("\nInspection complete.")


if __name__ == "__main__":
    main()