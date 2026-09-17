import re
from collections import defaultdict


# ============================================================
# OUTFIT RECOMMENDATION
# ============================================================

# The full set of occasions the dropdown offers, and the words a
# stored item might use that should still count as a match for one
# of them. Occasion filtering is STRICT (see _filter_by_occasion
# below): asking for "party" only ever returns items tagged party
# (or one of its aliases) - never casual items mixed in "just in
# case".
OCCASION_ALIASES = {
    "casual": {"casual", "daily", "daily wear", "college", "home"},
    "outing": {"outing", "day out", "hangout", "brunch", "errands"},
    "formal": {"formal", "office", "work", "business"},
    "party": {"party", "night out", "clubbing", "special occasion"},
    "festive": {"festive", "festival", "celebration", "holiday"},
    "traditional": {"traditional", "ethnic", "traditional/ethnic"}
}

CANONICAL_OCCASIONS = list(OCCASION_ALIASES.keys())


def _occasion_matches(item_occasion, requested_occasion):
    """
    True when an item's stored occasion is the requested one, or
    one of its known aliases. An item with no occasion recorded is
    treated as "casual" (the same default used when an item is
    first added), never as a wildcard that matches everything.
    """

    item_occasion = (item_occasion or "casual").lower().strip()
    requested_occasion = (requested_occasion or "casual").lower().strip()

    if item_occasion == requested_occasion:
        return True

    return item_occasion in OCCASION_ALIASES.get(requested_occasion, set())


def _filter_by_occasion(wardrobe_items, occasion):
    return [
        item for item in wardrobe_items
        if _occasion_matches(item.get("occasion"), occasion)
    ]


# ============================================================
# CATEGORY NORMALIZATION
#
# Wardrobe items can end up with two very different-looking
# category strings for the same kind of garment:
#   - the manual dropdown value from the frontend, e.g.
#     "Dhoti Pants", "Leggings & Salwars", "Men Kurta"
#   - the label written by the IndoFashion classifier, which
#     overrides the manual category for anything that isn't an
#     accessory, e.g. "dhoti_pants", "leggings_and_salwars",
#     "kurta_men"
#
# Both need to be recognized as the same garment type, so
# everything is normalized to lowercase, space-separated words
# before it's matched against any keyword list.
# ============================================================

def _normalize_category(category):
    if not category:
        return ""

    normalized = category.lower().strip()
    normalized = re.sub(r"[_\-&]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()

    return normalized


def _tokens(category):
    normalized = _normalize_category(category)

    if not normalized:
        return set()

    return set(normalized.split(" "))


# Token-based keyword sets. A category matches a bucket if any of
# its normalized words hits one of these markers - this way
# "kurta_men", "women_kurta", "men kurta" and plain "kurta" (or a
# plural "kurtas") all land in the same bucket without needing an
# ever-growing list of exact strings.

TOP_MARKERS = {
    "shirt", "shirts", "tshirt", "top", "tops",
    "blouse", "blouses", "kurta", "kurtas", "kurti", "kurtis"
}

BOTTOM_MARKERS = {
    "pant", "pants", "trouser", "trousers", "jean", "jeans",
    "short", "shorts", "skirt", "skirts", "bottom", "bottoms",
    "legging", "leggings", "palazzo", "palazzos", "dhoti"
}

DRESS_MARKERS = {
    "dress", "dresses", "saree", "sarees", "salwar",
    "lehenga", "lehengas", "gown", "gowns", "frock", "frocks"
}

ACCESSORY_MARKERS = {
    "shoe", "shoes", "sneaker", "sneakers", "mojari", "mojaris",
    "bag", "bags", "watch", "watches", "belt", "belts",
    "jewellery", "jewelry", "accessory", "accessories",
    "dupatta", "dupattas"
}

# Layering pieces - not a top/bottom/dress on their own, but worth
# folding in with accessories so they can still be suggested
# alongside an outfit instead of being silently ignored.
LAYER_MARKERS = {
    "jacket", "jackets", "sweater", "sweaters",
    "sherwani", "sherwanis", "nehru"
}

# Rough category heuristics for weather suitability - not a real
# fabric/weight model, just a starting point until one exists.
LIGHT_MARKERS = {
    "shirt", "tshirt", "blouse", "shorts", "skirt", "dress",
    "top", "kurta", "kurtas", "kurti", "kurtis", "saree",
    "sarees", "dupatta", "dupattas", "palazzo", "palazzos"
}

WARM_LAYER_MARKERS = {
    "jacket", "jackets", "sweater", "sweaters",
    "nehru", "sherwani", "sherwanis"
}


def _weather_score(items, weather):
    """
    Rough weather-suitability score. Returns a neutral 5 points
    per item when there's no weather info, or when an item's
    category doesn't clearly fall into a "light" or "warm layer"
    bucket - weather should nudge ranking, not hide clothes the
    heuristic can't classify.
    """

    if not weather:
        return 0

    points = 0

    for item in items:

        tokens = _tokens(item.get("category"))

        if weather.get("is_hot") and tokens & LIGHT_MARKERS:
            points += 25

        elif weather.get("is_cold") and tokens & WARM_LAYER_MARKERS:
            points += 25

        elif weather.get("is_rainy") and tokens & WARM_LAYER_MARKERS:
            points += 15

        else:
            points += 5

    return points / len(items)


def _score_outfit(items, weather=None):
    """
    Rough compatibility score for one outfit: a small bonus for
    pieces that don't all share the exact same color word, and
    (when weather data is available) how weather-appropriate the
    pieces are. Occasion is no longer part of the score - by the
    time an outfit reaches this function every item in it has
    already been filtered down to the requested occasion (see
    _filter_by_occasion), so there's nothing left for it to rank.
    """

    colors = {
        (item.get("color") or "")
        .lower()
        .strip()
        for item in items
        if item.get("color")
    }

    color_points = (
        15
        if len(colors) == len(items)
        else 8
    )

    weather_points = _weather_score(
        items,
        weather
    )

    return (
        color_points
        + weather_points
    )


def recommend_outfits(wardrobe_items, occasion="casual", weather=None):
    """
    Generate ranked complete outfit recommendations
    from the user's wardrobe.

    Uses existing wardrobe categories, colors and occasions - no
    additional AI training required. `weather`, when provided, is
    the dict returned by backend.weather.get_weather() and nudges
    ranking toward weather-appropriate pieces.

    Occasion filtering is strict: asking for "party" only builds
    outfits out of items tagged party (or a known alias of it) -
    a casual top never sneaks into a party recommendation just
    because the wardrobe happens to be short on party tops.
    """

    if not wardrobe_items:
        return []

    wardrobe_items = _filter_by_occasion(wardrobe_items, occasion)

    if not wardrobe_items:
        return []


    # --------------------------------------------------------
    # Bucket items into tops / bottoms / dresses / accessories
    # by matching normalized category tokens against keyword
    # marker sets, instead of relying on exact category strings.
    # This is what lets items land in the right bucket whether
    # their category came from the manual dropdown ("Dhoti
    # Pants") or was overwritten by the IndoFashion classifier
    # ("dhoti_pants").
    # --------------------------------------------------------

    tops = []
    bottoms = []
    dresses = []
    accessories = []

    for item in wardrobe_items:

        category = item.get("category")

        if not category:
            continue

        tokens = _tokens(category)

        if not tokens:
            continue

        if tokens & DRESS_MARKERS:
            dresses.append(item)
        elif tokens & TOP_MARKERS:
            tops.append(item)
        elif tokens & BOTTOM_MARKERS:
            bottoms.append(item)
        elif tokens & (ACCESSORY_MARKERS | LAYER_MARKERS):
            accessories.append(item)

        # Anything that matches none of the marker sets is left
        # out of outfit generation entirely (rather than crashing
        # or silently misclassifying it into the wrong bucket).


    recommendations = []


    # ========================================================
    # DRESS / ONE-PIECE OUTFITS
    # ========================================================

    for dress in dresses[:5]:

        items = [dress]

        if accessories:

            items.append(
                accessories[
                    len(recommendations)
                    % len(accessories)
                ]
            )

        recommendations.append({
            "occasion": occasion,
            "items": items,
            "type": "one-piece",
            "score": round(
                _score_outfit(
                    items,
                    weather
                ),
                1
            )
        })


    # ========================================================
    # TOP + BOTTOM OUTFITS
    # ========================================================

    for top in tops[:8]:

        for bottom in bottoms[:8]:

            items = [top, bottom]

            if accessories:

                items.append(
                    accessories[
                        len(recommendations)
                        % len(accessories)
                    ]
                )

            recommendations.append({
                "occasion": occasion,
                "items": items,
                "type": "top-bottom",
                "score": round(
                    _score_outfit(
                        items,
                        weather
                    ),
                    1
                )
            })


    # ========================================================
    # RANK BY SCORE, THEN LIMIT RESULTS
    #
    # Best occasion/color matches surface first instead of
    # whatever order items happened to be grouped in.
    # ========================================================

    recommendations.sort(
        key=lambda outfit: outfit["score"],
        reverse=True
    )

    return recommendations[:10]
