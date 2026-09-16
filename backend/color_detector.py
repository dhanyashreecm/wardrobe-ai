import cv2
import numpy as np


def detect_dominant_color(image_path):
    """
    Detect the dominant clothing color from an image.

    Returns:
        A simple color name such as:
        red, orange, yellow, green, blue,
        purple, pink, brown, black, white, gray
    """

    image = cv2.imread(image_path)

    if image is None:
        raise ValueError(f"Could not read image: {image_path}")

    # Resize for faster processing
    image = cv2.resize(image, (300, 300))

    # Convert BGR -> HSV
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

    # Ignore very dark pixels and very bright background pixels
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]

    mask = (
        (saturation > 40) |
        (value < 80) |
        (value > 180)
    )

    pixels = hsv[mask]

    if len(pixels) == 0:
        pixels = hsv.reshape(-1, 3)

    hue = pixels[:, 0]
    sat = pixels[:, 1]
    val = pixels[:, 2]

    # Remove extreme low-information pixels
    useful = ~(
        ((sat < 30) & (val > 180)) |
        ((sat < 30) & (val < 40))
    )

    hue = hue[useful]
    sat = sat[useful]
    val = val[useful]

    if len(hue) == 0:
        hue = pixels[:, 0]
        sat = pixels[:, 1]
        val = pixels[:, 2]

    # ---------------------------------------------------------
    # Neutral colors
    # ---------------------------------------------------------

    average_saturation = float(np.mean(sat))
    average_value = float(np.mean(val))

    if average_value < 55:
        return "black"

    if average_saturation < 35 and average_value > 190:
        return "white"

    if average_saturation < 35:
        return "gray"

    # ---------------------------------------------------------
    # Main color based on HSV hue
    # ---------------------------------------------------------

    dominant_hue = float(np.median(hue))

    if dominant_hue < 10 or dominant_hue >= 170:
        return "red"

    elif dominant_hue < 20:
        return "orange"

    elif dominant_hue < 35:
        return "yellow"

    elif dominant_hue < 85:
        return "green"

    elif dominant_hue < 130:
        return "blue"

    elif dominant_hue < 155:
        return "purple"

    else:
        return "pink"


if __name__ == "__main__":

    import sys

    if len(sys.argv) != 2:
        print("Usage:")
        print("python3 backend/color_detector.py <image_path>")
        sys.exit(1)

    image_path = sys.argv[1]

    color = detect_dominant_color(image_path)

    print({
        "image": image_path,
        "dominant_color": color
    })
