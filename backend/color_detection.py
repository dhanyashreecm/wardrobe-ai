"""
Automatic dominant-color detection for an uploaded wardrobe photo.

This is what makes the "color" field genuinely OPTIONAL: when the
user doesn't type a color themselves, this module looks at the
actual uploaded photo and picks the closest matching color NAME from
the same vocabulary color_theory.py already understands, so the
auto-detected value plugs straight into the existing color-harmony
scoring (color_theory.outfit_color_score / color_harmony) with no
extra work needed there.

Not a trained model - a simple, explainable heuristic:
  1. Downsample the image so this stays fast (this runs synchronously
     on every upload, so it needs to be near-instant).
  2. Work out what the BACKDROP itself looks like in THIS photo (by
     sampling the outer border of the frame, where these close-up
     product-style photos always show plain background rather than
     the garment).
  3. Split every pixel into two groups by simple k-means clustering
     (k=2) in RGB space, seeded from that backdrop color - NOT a
     fixed distance cutoff from the backdrop. A cutoff fails on a
     pale/light garment against a near-white backdrop (both are
     "bright", so neither is "far enough" from the other by raw
     distance); clustering instead groups pixels by how similar they
     are to EACH OTHER, so a consistently blue-tinted garment still
     separates cleanly from a consistently neutral backdrop even
     when both are light.
  4. Whichever of the two resulting groups is the one that ISN'T the
     backdrop is treated as the garment; its average RGB is matched
     to the closest reference color by simple distance - "closest",
     not "exact", since real fabric photos are never a single flat
     RGB value.
  5. Before that matching step, the garment color's SATURATION (HSV)
     decides which reference colors are even eligible: a genuinely
     tinted color (pale blue, dusty pink, sage green, ...) is only
     ever compared against the HUED references, never against
     black/white/grey/charcoal/silver - and vice versa. Plain
     Euclidean RGB distance gets this wrong for pale/light garments -
     e.g. a pale blue shirt (180, 205, 228) is numerically CLOSER to
     "silver" (192, 192, 197) than to "sky" (140, 195, 230), because
     RGB distance is dominated by how BRIGHT the two colors are, not
     by the fact that one is neutral and the other is unmistakably
     blue. Gating on saturation first fixes that: a color has to be
     about as colorless as a real silver/grey/white garment actually
     is before it's allowed to match one.
  6. Even after that gate, matching a tinted color against the
     remaining HUED references still can't use plain RGB distance -
     the same "distance is really brightness in disguise" problem
     would then match that same pale blue shirt to "lavender" (a
     light purple) instead of "sky", just because they happen to be
     similarly bright. So the hued comparison is done in HSV space
     instead, weighted so HUE (is this reddish? bluish? greenish?)
     dominates the match and saturation/value only break ties
     between references that already share a similar hue.

Manual entry always wins when the user provides one - see app.py's
add_wardrobe_item route, which only ever calls detect_dominant_color()
when the "color" form field was left blank. Uses Pillow (PIL), which
is already a dependency here via tensorflow.keras.utils.load_img -
no new package to install.
"""

import colorsys
from statistics import median

from PIL import Image

# Representative RGB anchor for a useful subset of the color WORDS
# color_theory._COLOR_TABLE already knows how to classify into a
# family/warmth/neutral bucket. Picking a name from THIS list
# guarantees whatever this module returns is something
# outfit_color_score() can immediately score, not some new unknown
# word neither module has ever seen.
_REFERENCE_COLORS = {
    "red": (196, 30, 40),
    "maroon": (115, 20, 30),
    "orange": (230, 126, 34),
    "peach": (255, 200, 165),
    "coral": (240, 128, 105),
    "yellow": (240, 210, 60),
    "mustard": (200, 165, 45),
    "gold": (212, 175, 55),
    "cream": (250, 240, 210),
    "green": (60, 140, 75),
    "olive": (110, 115, 55),
    "mint": (175, 225, 195),
    "teal": (25, 128, 128),
    "blue": (45, 95, 190),
    "navy": (25, 40, 85),
    "sky": (140, 195, 230),
    "denim": (70, 100, 140),
    "purple": (115, 65, 160),
    "lavender": (190, 170, 220),
    "pink": (235, 130, 170),
    "rose": (200, 100, 120),
    "salmon": (245, 145, 130),
    "magenta": (200, 40, 140),
    "brown": (110, 70, 45),
    "tan": (200, 170, 130),
    "beige": (222, 208, 180),
    "black": (30, 30, 30),
    "white": (240, 240, 240),
    "grey": (130, 130, 130),
    "charcoal": (60, 60, 65),
    "silver": (192, 192, 197),
}


# A cluster has to be at least this fraction of the whole
# (downsampled) photo before it's trusted as "the garment" - below
# this, it's more likely a handful of stray/shadow/noise pixels than
# an actual garment (e.g. a flat single-color test photo, where
# clustering degenerates to one real cluster and an empty one), so
# the whole-image average is used instead. See detect_dominant_color.
_MIN_GARMENT_FRACTION = 0.05

# k-means iterations - the two clusters settle well before this on
# images this small (80x80), so this is a safety cap, not a tuned
# minimum.
_KMEANS_ITERATIONS = 8

# The reference colors that represent "no real hue" - a garment only
# gets matched against these when its own color is about this
# colorless too (see _SATURATION_GATE_THRESHOLD below). Every other
# name in _REFERENCE_COLORS is a "hued" color.
_NEUTRAL_COLOR_NAMES = {"black", "white", "grey", "charcoal", "silver"}

# HSV saturation (0-1) a garment color must reach before it's treated
# as genuinely tinted rather than neutral. The neutral reference
# swatches above all sit well under 0.1 (silver ~0.03, charcoal
# ~0.08, black/white/grey are perfectly flat at 0). A real pale
# color - pale blue, dusty pink, sage, and so on - reliably clears
# 0.15 even after a camera's white balance softens it, while normal
# sensor/compression noise on an actually-neutral garment usually
# doesn't. This is a heuristic cutoff, not a physical constant - it
# can be tuned if a specific photo comes out wrong.
_SATURATION_GATE_THRESHOLD = 0.15


def _sample_backdrop_color(image):
    """
    The median RGB along the OUTER BORDER of the (already
    downsampled) photo - the actual backdrop color for this specific
    photo, not an assumed fixed color. These are close-up,
    product-style photos of one garment roughly centered in the
    frame (the crop tool in Wardrobe.js already encourages this), so
    the border is reliably backdrop rather than garment. Median
    (not mean) so a corner shadow or a sliver of the garment poking
    into the border doesn't skew the estimate.
    """
    width, height = image.size

    border_pixels = []

    for x in range(width):
        border_pixels.append(image.getpixel((x, 0)))
        border_pixels.append(image.getpixel((x, height - 1)))

    for y in range(height):
        border_pixels.append(image.getpixel((0, y)))
        border_pixels.append(image.getpixel((width - 1, y)))

    return (
        median(pixel[0] for pixel in border_pixels),
        median(pixel[1] for pixel in border_pixels),
        median(pixel[2] for pixel in border_pixels),
    )


def _squared_distance(rgb_a, rgb_b):
    return sum(
        (channel_a - channel_b) ** 2
        for channel_a, channel_b in zip(rgb_a, rgb_b)
    )


def _average_rgb(pixels):
    red_total = sum(pixel[0] for pixel in pixels)
    green_total = sum(pixel[1] for pixel in pixels)
    blue_total = sum(pixel[2] for pixel in pixels)

    count = len(pixels)

    return (
        red_total / count,
        green_total / count,
        blue_total / count,
    )


def _split_backdrop_from_garment(pixels, backdrop_rgb):
    """
    Separates `pixels` into (garment_rgb, garment_count) via a small
    from-scratch k-means (k=2) in RGB space, seeded from the photo's
    own backdrop color - see the module docstring for why this beats
    a fixed distance-from-backdrop cutoff.

    One centroid starts at the backdrop color itself; the other
    starts at whichever pixel is FARTHEST from it - a reasonable
    first guess for "the most garment-like pixel available". Each
    round, every pixel joins whichever centroid it's currently
    closer to, then both centroids are recomputed as the average of
    their members; this settles into two stable groups well within
    the iteration cap on an image this small.

    Returns the average RGB of whichever final cluster ISN'T the one
    left closest to the original backdrop estimate, plus how many
    pixels ended up in it - the caller decides whether that count is
    big enough to trust as a real garment rather than a few stray
    pixels.
    """

    centroid_backdrop = backdrop_rgb

    centroid_garment = max(
        pixels,
        key=lambda pixel: _squared_distance(pixel, backdrop_rgb)
    )

    backdrop_group = pixels
    garment_group = []

    for _ in range(_KMEANS_ITERATIONS):

        backdrop_group = []
        garment_group = []

        for pixel in pixels:

            if (
                _squared_distance(pixel, centroid_backdrop)
                <= _squared_distance(pixel, centroid_garment)
            ):
                backdrop_group.append(pixel)
            else:
                garment_group.append(pixel)

        # Degenerate case - everything collapsed into one group
        # (e.g. a perfectly flat-color test photo). Stop here rather
        # than averaging an empty list.
        if not backdrop_group or not garment_group:
            break

        centroid_backdrop = _average_rgb(backdrop_group)
        centroid_garment = _average_rgb(garment_group)

    # Whichever final group is farther from the ORIGINAL backdrop
    # sample is treated as the garment - not simply "whichever group
    # is smaller", since a garment photographed large/close-up can
    # easily outnumber a thin sliver of visible backdrop.
    group_a, centroid_a = backdrop_group, centroid_backdrop
    group_b, centroid_b = garment_group, centroid_garment

    if not group_b or (
        group_a
        and _squared_distance(centroid_a, backdrop_rgb)
        > _squared_distance(centroid_b, backdrop_rgb)
    ):
        garment_pixels, garment_centroid = group_a, centroid_a
    else:
        garment_pixels, garment_centroid = group_b, centroid_b

    return garment_centroid, len(garment_pixels)


# How heavily HUE counts relative to saturation/value when matching
# a genuinely tinted color to the nearest HUED reference (see
# _hsv_weighted_distance). Hue is what actually tells two tinted
# colors apart (blue vs purple, red vs orange); saturation/value
# mainly break ties between references that share a similar hue
# (e.g. "sky" vs "denim" are both blue-ish, but at very different
# brightness/intensity) - so hue gets several times their weight
# rather than being just one more equal-weighted channel.
_HUE_WEIGHT = 3.0
_SATURATION_WEIGHT = 1.0
_VALUE_WEIGHT = 1.0


def _hsv_weighted_distance(rgb_a, rgb_b):
    """
    Distance between two colors in HSV space, NOT plain RGB space -
    used only once a color has already been gated as "genuinely
    tinted" (see _nearest_reference_color). Plain RGB distance
    conflates brightness with hue, which is exactly what makes a
    pale, light color drift toward whatever reference happens to
    share its brightness rather than the one that actually shares
    its hue (a pale blue is numerically closer, in raw RGB, to a
    muted "denim" or even a light "lavender" than to "sky" - despite
    "sky" being the obviously-correct match by hue). Weighting hue
    heavily and treating it as circular (0 degrees and 360 degrees
    are the same color) fixes that.
    """
    hue_a, saturation_a, value_a = colorsys.rgb_to_hsv(
        rgb_a[0] / 255.0, rgb_a[1] / 255.0, rgb_a[2] / 255.0
    )
    hue_b, saturation_b, value_b = colorsys.rgb_to_hsv(
        rgb_b[0] / 255.0, rgb_b[1] / 255.0, rgb_b[2] / 255.0
    )

    hue_distance = abs(hue_a - hue_b)
    hue_distance = min(hue_distance, 1.0 - hue_distance)

    return (
        (_HUE_WEIGHT * hue_distance) ** 2
        + (_SATURATION_WEIGHT * (saturation_a - saturation_b)) ** 2
        + (_VALUE_WEIGHT * (value_a - value_b)) ** 2
    )


def _nearest_reference_color(rgb):
    """
    Closest reference color - but the garment color's HSV saturation
    decides both which references are even in the running, and which
    distance measure is used to pick among them:

      - Low saturation (about as colorless as the neutral swatches
        themselves): compared against black/white/grey/charcoal/
        silver only, by plain RGB distance - fine here, since these
        references only differ by brightness anyway.
      - Real saturation: compared against every OTHER (hued)
        reference, by HSV-weighted distance (_hsv_weighted_distance)
        so the match is driven by hue, not incidental brightness.
        Using plain RGB distance here is what previously matched a
        pale blue shirt to "silver" (too close in brightness to
        every neutral) and, once neutrals were excluded, still would
        have matched it to "lavender" (too close in brightness to a
        light purple) instead of "sky" - both are the same underlying
        mistake: RGB distance is really a brightness comparison in
        disguise, not a color comparison.
    """
    red, green, blue = rgb

    _, saturation, _ = colorsys.rgb_to_hsv(
        red / 255.0, green / 255.0, blue / 255.0
    )

    if saturation < _SATURATION_GATE_THRESHOLD:
        candidates = {
            name: reference_rgb
            for name, reference_rgb in _REFERENCE_COLORS.items()
            if name in _NEUTRAL_COLOR_NAMES
        }
        distance_fn = _squared_distance
    else:
        candidates = {
            name: reference_rgb
            for name, reference_rgb in _REFERENCE_COLORS.items()
            if name not in _NEUTRAL_COLOR_NAMES
        }
        distance_fn = _hsv_weighted_distance

    best_name = None
    best_distance = None

    for name, reference_rgb in candidates.items():

        distance = distance_fn(rgb, reference_rgb)

        if best_distance is None or distance < best_distance:
            best_name = name
            best_distance = distance

    return best_name


def detect_dominant_color(image_path):
    """
    Returns a color NAME (one color_theory.py already recognizes)
    that's the closest match to the uploaded photo's dominant color,
    or None if the image couldn't be opened/analyzed at all -
    callers should treat None as "auto-detection unavailable" (leave
    color blank / ask the user to type one) rather than guessing.
    """

    try:
        image = Image.open(image_path).convert("RGB")
    except Exception as e:
        print(f"Color detection skipped - could not read image: {e}")
        return None

    # Small enough to be fast, still plenty of pixels for a stable
    # average.
    image = image.resize((80, 80))

    pixels = list(image.getdata())

    backdrop_rgb = _sample_backdrop_color(image)

    garment_rgb, garment_count = _split_backdrop_from_garment(
        pixels, backdrop_rgb
    )

    # A garment cluster too small to trust (a flat single-color
    # photo, or a photo where garment and backdrop are close enough
    # that clustering couldn't meaningfully separate them) falls
    # back to the whole photo's average instead.
    if garment_count < len(pixels) * _MIN_GARMENT_FRACTION:
        garment_rgb = _average_rgb(pixels)

    return _nearest_reference_color(garment_rgb)
