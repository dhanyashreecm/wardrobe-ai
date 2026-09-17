"""
Explainable color-harmony scoring - NOT a fixed "these two colors
are allowed" rulebook, and NOT machine learning. The user's manual
color entry (free text - "navy", "dusty rose", "off white") is
never overwritten or reinterpreted; this module only ever READS it
to classify the color into a family/warmth/neutral bucket, the same
way a person would describe a color to a friend.

Design, per the spec this was built against:
  - Complementary, analogous, monochromatic, neutral-balancing, and
    triadic combinations are all recognized as GOOD, not just one
    fixed rule.
  - Occasion is NOT baked in here - a wedding tolerating richer
    color combinations than an interview is handled by the CALLER
    weighting this score differently per occasion (see
    outfit_recommendation.OCCASION_COLOR_TOLERANCE), not by this
    module changing its definition of "harmonious".
  - This is a heuristic scoring aid, not the sole basis for a
    recommendation - outfit_recommendation.py combines this with
    style compatibility and hard restrictions, and an outfit is
    never rejected on color alone.
"""

import re

# ------------------------------------------------------------
# COLOR LOOKUP TABLE
#
# Maps common color WORDS (as a person would actually type them
# into the existing free-text color field) to:
#   - family: one of the 12-hue color wheel families used for
#     complementary/analogous/triadic checks below
#   - warmth: "warm", "cool", or "neutral"
#   - neutral: True for colors that harmonize with nearly anything
#     (black/white/grey/beige/navy/denim etc - "neutral balancing")
#
# Not exhaustive - an unrecognized color word falls back to a
# reasonable neutral-ish default (see _lookup) rather than crashing
# or silently scoring zero.
# ------------------------------------------------------------

_COLOR_TABLE = {
    # reds
    "red": ("red", "warm", False), "crimson": ("red", "warm", False),
    "maroon": ("red", "warm", False), "burgundy": ("red", "warm", False),
    "wine": ("red", "warm", False), "brick": ("red", "warm", False),
    "rust": ("red-orange", "warm", False),
    # oranges
    "orange": ("orange", "warm", False), "coral": ("orange", "warm", False),
    "peach": ("orange", "warm", False), "tangerine": ("orange", "warm", False),
    "terracotta": ("orange", "warm", False),
    # yellows
    "yellow": ("yellow", "warm", False), "mustard": ("yellow", "warm", False),
    "gold": ("yellow", "warm", False), "amber": ("yellow", "warm", False),
    "cream": ("yellow", "warm", True), "ivory": ("yellow", "warm", True),
    # greens
    "green": ("green", "cool", False), "olive": ("green", "warm", False),
    "sage": ("green", "cool", True), "mint": ("green", "cool", False),
    "emerald": ("green", "cool", False), "forest": ("green", "cool", False),
    "khaki": ("green", "warm", True),
    # blues
    "blue": ("blue", "cool", False), "navy": ("blue", "cool", True),
    "denim": ("blue", "cool", True), "sky": ("blue", "cool", False),
    "cobalt": ("blue", "cool", False), "turquoise": ("blue-green", "cool", False),
    "teal": ("blue-green", "cool", False),
    # purples
    "purple": ("purple", "cool", False), "lavender": ("purple", "cool", False),
    "lilac": ("purple", "cool", False), "violet": ("purple", "cool", False),
    "plum": ("purple", "cool", False), "mauve": ("purple", "cool", True),
    # pinks
    "pink": ("pink", "warm", False), "rose": ("pink", "warm", False),
    "magenta": ("pink", "warm", False), "fuchsia": ("pink", "warm", False),
    "blush": ("pink", "warm", True), "salmon": ("pink", "warm", False),
    # neutrals
    "black": ("neutral", "neutral", True), "white": ("neutral", "neutral", True),
    "grey": ("neutral", "neutral", True), "gray": ("neutral", "neutral", True),
    "silver": ("neutral", "neutral", True), "charcoal": ("neutral", "neutral", True),
    "beige": ("neutral", "warm", True), "tan": ("neutral", "warm", True),
    "brown": ("neutral", "warm", True), "chocolate": ("neutral", "warm", True),
    "camel": ("neutral", "warm", True), "taupe": ("neutral", "warm", True),
    "nude": ("neutral", "warm", True),
}

# 12-hue wheel, in order, used for complementary/analogous/triadic
# angle checks - "distance" between two families is just their
# index difference around this ring.
_HUE_WHEEL = [
    "red", "red-orange", "orange", "yellow", "yellow-green", "green",
    "blue-green", "blue", "blue-purple", "purple", "pink", "red"
]


def _lookup(color_word):
    if not color_word:
        return None
    word = color_word.lower().strip()
    if word in _COLOR_TABLE:
        return _COLOR_TABLE[word]
    # Multi-word entries ("off white", "dusty rose") - try the last
    # word as a fallback (usually the base color), e.g. "dusty rose"
    # -> "rose".
    parts = word.split()
    for part in reversed(parts):
        if part in _COLOR_TABLE:
            return _COLOR_TABLE[part]
    return None


def classify_color(color_word):
    """
    Returns {"family", "warmth", "neutral", "recognized"} for a
    user-entered color string. An unrecognized word gets a safe,
    permissive default (neutral=True) rather than being penalized -
    color harmony should never punish a color it simply doesn't
    have a lookup entry for.
    """
    result = _lookup(color_word)
    if result is None:
        return {"family": None, "warmth": None, "neutral": True, "recognized": False}
    family, warmth, neutral = result
    return {"family": family, "warmth": warmth, "neutral": neutral, "recognized": True}


def _hue_distance(family_a, family_b):
    if family_a == family_b:
        return 0
    if family_a not in _HUE_WHEEL or family_b not in _HUE_WHEEL:
        return None
    i, j = _HUE_WHEEL.index(family_a), _HUE_WHEEL.index(family_b)
    diff = abs(i - j)
    return min(diff, len(_HUE_WHEEL) - diff)


def color_harmony(color_a, color_b):
    """
    Scores how well two color WORDS work together, 0-25, plus a
    short human-readable reason - this reason is what ends up in
    the outfit's "why this works" explanation the frontend shows.
    Recognizes several DIFFERENT kinds of good combination rather
    than one fixed rule, per the spec:
      - either color unrecognized -> small neutral default score
        (never penalized for a color we just don't have a lookup
        entry for)
      - neutral-balancing: either color is a neutral (black/white/
        grey/beige/navy/denim/...) -> pairs well with almost
        anything
      - monochromatic: same family -> pairs well
      - analogous: adjacent families on the 12-hue wheel -> pairs
        well
      - complementary: roughly opposite families (5-7 steps around
        the wheel) -> pairs well, bold
      - triadic: ~4 steps apart -> pairs reasonably
      - everything else: a modest baseline score, not a rejection -
        color alone never disqualifies an outfit (see
        outfit_recommendation.py, which treats this as ONE of
        several soft-scored factors, never a hard restriction)
    """
    a = classify_color(color_a)
    b = classify_color(color_b)

    if not a["recognized"] or not b["recognized"]:
        return 12, "color not fully recognized - neutral default"

    if a["neutral"] or b["neutral"]:
        return 25, "neutral balancing"

    if a["family"] == b["family"]:
        return 22, "monochromatic"

    distance = _hue_distance(a["family"], b["family"])

    if distance is None:
        return 12, "colors not directly comparable"

    if distance == 1:
        return 20, "analogous colors"

    if 5 <= distance <= 7:
        return 20, "complementary colors"

    if distance in (3, 4):
        return 16, "triadic-adjacent colors"

    if a["warmth"] == b["warmth"] and a["warmth"] != "neutral":
        return 14, "warm/cool coordination"

    return 8, "colors clash somewhat"


def outfit_color_score(items):
    """
    Average pairwise color_harmony() across every pair of items in
    an outfit (2 items -> 1 pair, 3 items -> 3 pairs, etc), scaled
    to a single 0-25 score for outfit_recommendation.py to combine
    with style/occasion/weather. A single-item outfit (a one-piece
    dress/saree alone) gets a flat neutral score, since there's
    nothing to compare it against.
    """
    colors = [
        (item.get("color") or "").strip()
        for item in items
        if item.get("color")
    ]

    if len(colors) < 2:
        return 18, ["single item - no color pairing to evaluate"]

    total = 0
    reasons = []
    pair_count = 0

    for i in range(len(colors)):
        for j in range(i + 1, len(colors)):
            score, reason = color_harmony(colors[i], colors[j])
            total += score
            reasons.append(f"{colors[i]} + {colors[j]}: {reason}")
            pair_count += 1

    return (round(total / pair_count, 1) if pair_count else 18), reasons
