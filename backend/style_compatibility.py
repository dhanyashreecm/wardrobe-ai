"""
Style-compatibility scoring - rule-based, not ML, and deliberately
conservative about which style tags it assigns. The spec this was
built against warns explicitly against "randomly assigned" style
labels, so this module only claims the styles it can actually infer
reliably from data it has: a garment's CATEGORY, and (for the
ethnic/festive categories where it matters most - Saree, Lehenga,
Kurta) the optional manual "styling" attribute added alongside color
this round (see wardrobe.py/app.py - "Casual" vs "Wedding/Festive").

Five styles, not the full eleven the spec lists as POSSIBLE
attributes (Streetwear, Minimalist, Romantic, Sporty, Trendy are
left out on purpose) - there's no reliable signal in a plain
category string to tell a "romantic" top from a "minimalist" one
without guessing, and guessing is exactly what was asked against.
This is an honest, narrower set that stays accurate:

    casual, smart_casual, formal, traditional, festive
"""

import re

CASUAL = "casual"
SMART_CASUAL = "smart_casual"
FORMAL = "formal"
TRADITIONAL = "traditional"
FESTIVE = "festive"

STYLE_LABELS = {
    CASUAL: "Casual",
    SMART_CASUAL: "Smart Casual",
    FORMAL: "Formal",
    TRADITIONAL: "Traditional",
    FESTIVE: "Festive",
}


def _normalize(category):
    if not category:
        return set()
    normalized = category.lower().strip()
    normalized = re.sub(r"[_\-&()]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    tokens = set(normalized.split(" ")) if normalized else set()

    # "T-Shirt" (the actual category label - see Wardrobe.js) splits
    # on its hyphen into separate "t"/"shirt" tokens above, which
    # would otherwise never match the merged "tshirt" token below and
    # silently fall through to the plain-"Shirt" default (SMART_CASUAL)
    # instead of being read as CASUAL - found via run_test7.py, which
    # asserted infer_style("T-Shirt") == CASUAL and failed. Folding
    # the split pair back into one "tshirt" token (and dropping the
    # bare "t", which is meaningless on its own) fixes this without
    # touching the shared _tokens()/marker-set logic in
    # outfit_recommendation.py or category_gender.py, which don't have
    # this ambiguity (both already match "shirt" for either T-Shirt or
    # Shirt and don't need to tell the two apart).
    if "t" in tokens and "shirt" in tokens:
        tokens.discard("t")
        tokens.discard("shirt")
        tokens.add("tshirt")

    return tokens


# Token -> style. Checked in this order; first match wins (a token
# set is checked against each style's token set below).
_STYLE_TOKENS = {
    CASUAL: {
        "tshirt", "tshirts", "jean", "jeans", "short", "shorts",
        "legging", "leggings", "salwar", "salwars", "crop", "tank",
    },
    FORMAL: {
        "blazer", "blazers", "suit", "suits",
    },
    TRADITIONAL: {
        "sherwani", "sherwanis", "dhoti", "nehru", "dupatta",
        "dupattas", "mojari", "mojaris", "petticoat", "petticoats",
        "anarkali",
    },
    # Checked LAST among the "always this style" categories -
    # saree/lehenga/gown/blouse default here but get refined by the
    # manual styling attribute in resolve_style() below.
    FESTIVE: {
        "lehenga", "lehengas", "saree", "sarees", "gown", "gowns",
        "blouse", "blouses",
    },
    # Everything else reasonable (Shirt, Pant, Trousers, Skirt,
    # Dress, Kurta, Palazzos, Chinos, Polo...) defaults to
    # smart_casual - the honest middle ground for a plain garment
    # with no further metadata, rather than guessing formal or
    # casual specifically.
}


def infer_style(category):
    tokens = _normalize(category)
    if not tokens:
        return SMART_CASUAL

    for style in (CASUAL, FORMAL, TRADITIONAL, FESTIVE):
        if tokens & _STYLE_TOKENS[style]:
            return style

    return SMART_CASUAL


def resolve_style(category, styling=None):
    """
    Like infer_style(), but applies the optional manual "styling"
    attribute (currently offered for Saree/Lehenga/Kurta-type items
    - see wardrobe.py) as an override: a Saree styled "Casual"
    reads as smart_casual/traditional-leaning, not festive, and a
    Kurta styled "Wedding/Festive" reads as festive rather than its
    smart_casual default. This is what actually implements the
    "Casual Saree vs Wedding Saree" distinction the AI model itself
    cannot make (it only ever outputs "saree") - the user's own
    styling choice is the source of truth here, exactly like color.
    """
    base = infer_style(category)
    styling = (styling or "").strip().lower()

    if not styling:
        return base

    if styling in ("casual",):
        # A casually-styled ethnic piece reads as smart_casual
        # rather than fully "casual" (a casual saree is still
        # more put-together than a t-shirt), and never LESS formal
        # than traditional if that's already its base.
        return SMART_CASUAL if base == FESTIVE else base

    if styling in ("wedding", "festive", "wedding/festive", "wedding-festive"):
        return FESTIVE

    return base


# ------------------------------------------------------------
# COMPATIBILITY
#
# Symmetric distance on a deliberately short "formality ladder" -
# casual and smart_casual are close, smart_casual and formal are
# close, traditional and festive are close, but casual and festive
# (a t-shirt next to a wedding lehenga) are far apart. This mirrors
# how outfits actually get judged: two adjacent formality levels
# read as a coherent, intentional outfit; two distant ones read as
# mismatched - without ever being a hard rejection (see
# outfit_recommendation.py: style is a SOFT score, only gender/
# occasion/ownership are hard restrictions).
# ------------------------------------------------------------

_LADDER = [CASUAL, SMART_CASUAL, FORMAL]
_ETHNIC_LADDER = [TRADITIONAL, FESTIVE]


def _ladder_distance(style_a, style_b):
    if style_a == style_b:
        return 0
    if style_a in _LADDER and style_b in _LADDER:
        return abs(_LADDER.index(style_a) - _LADDER.index(style_b))
    if style_a in _ETHNIC_LADDER and style_b in _ETHNIC_LADDER:
        return abs(_ETHNIC_LADDER.index(style_a) - _ETHNIC_LADDER.index(style_b))
    # One Western, one ethnic (e.g. smart_casual + traditional) -
    # a Kurta with Jeans is a real, common Indo-western combination,
    # so this is treated the same as a one-step formality gap (see
    # style_pair_score's distance==1 branch) rather than the harsher
    # "far apart" case.
    return 1


def style_pair_score(style_a, style_b):
    """
    0-20 score + short reason for a pair of style tags.
    """
    distance = _ladder_distance(style_a, style_b)

    if distance == 0:
        return 20, f"both {STYLE_LABELS[style_a]}"
    if distance == 1:
        return 15, f"{STYLE_LABELS[style_a]} + {STYLE_LABELS[style_b]} - compatible formality"
    return 8, f"{STYLE_LABELS[style_a]} + {STYLE_LABELS[style_b]} - a formality gap, but not disqualifying"


def outfit_style_score(items):
    """
    Average pairwise style_pair_score() across an outfit's items,
    mirroring color_theory.outfit_color_score()'s shape so
    outfit_recommendation.py can combine them symmetrically.
    """
    styles = [
        resolve_style(item.get("category"), item.get("styling"))
        for item in items
    ]

    if len(styles) < 2:
        return 16, ["single item - no style pairing to evaluate"]

    total = 0
    reasons = []
    pair_count = 0

    for i in range(len(styles)):
        for j in range(i + 1, len(styles)):
            score, reason = style_pair_score(styles[i], styles[j])
            total += score
            reasons.append(reason)
            pair_count += 1

    return (round(total / pair_count, 1) if pair_count else 16), reasons
