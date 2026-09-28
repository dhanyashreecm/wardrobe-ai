"""
HOW WELL DOES THIS OUTFIT SUIT THIS OCCASION?

The problem this solves
-----------------------
Before this module, "occasion" only decided which items were ELIGIBLE
(see outfit_recommendation._filter_by_occasion). Once an item passed
that filter, the occasion contributed nothing at all to its score, so
any two occasions with overlapping eligibility returned the same
outfits in the same order. Measured on a plain wardrobe (2 jeans, 2
t-shirts, 1 shirt, 1 trousers), casual / day_outing / college / date
produced a byte-identical top-5, every outfit scoring exactly 65.0.
That is the "different occasions give me the same recommendations"
complaint, and no amount of colour or style tuning fixes it, because
none of those terms vary with the occasion either.

This module adds the missing dimension: a per-occasion FIT score, so
the same wardrobe re-ranks when the occasion changes.

Where the numbers come from
---------------------------
Not from invention. The project already contains the Myntra fashion
dataset (dataset/kaggle_fashion/styles.csv, 44,446 real catalogue
items), and every row carries a "usage" label - Casual, Formal,
Ethnic, Sports, Party, Smart Casual, Travel. Aggregating usage by
garment type gives a measured profile per category, e.g.

    Jeans      Casual 100%             Trousers  Casual 54%  Formal 45%
    Tshirts    Casual 86%  Sports 14%  Kurtas    Ethnic 100%
    Shirts     Casual 72%  Formal 27%  Sarees    Ethnic 100%

data/category_usage.json holds that table; build_occasion_model.py
regenerates it from the CSV. This is what lets the engine know, from
evidence rather than assertion, that trousers are a more formal
garment than jeans while both are perfectly ordinary casual wear.

What the data does NOT support
------------------------------
The same dataset has only 29 "Party" rows and 67 "Smart Casual" out of
44k, so it cannot characterise party or date wear. Those occasions are
handled on a FORMALITY axis instead (below), which is an explicit
modelling decision, documented here rather than hidden: a date sits
above everyday casual and below an interview; a party favours
statement pieces over basics. Where the data is thin, the model says
so instead of implying a measurement that was never made.

Occasions are targets over the same axes
----------------------------------------
Each occasion is expressed as the usage mix it wants plus a target
formality, and an outfit scores by how close its items sit to that
target. Nothing here is a per-occasion allow-list of items: add a new
category and it inherits a sensible profile from its usage data, with
no rule to write.
"""

import json
import os
import re


_DATA_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "category_usage.json"
)


def _load_usage_table():
    """
    The measured usage mix per Myntra article type. Missing or
    unreadable file is survivable: every category then falls back to
    the neutral profile below, which costs accuracy but never breaks
    recommendations.
    """
    try:
        with open(_DATA_PATH, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception as error:
        print(f"Occasion model: could not read {_DATA_PATH} ({error}) - "
              "falling back to neutral profiles.")
        return {}


USAGE_TABLE = _load_usage_table()


# The app's own category names -> the Myntra article type that
# represents them. Written as tokens (see _tokens) rather than exact
# strings so "Kurta (Women)", "kurta_men" and "Kurtas" all resolve to
# the same profile.
CATEGORY_TO_ARTICLE = {
    # ---- multi-word names, matched BEFORE single tokens ----------
    # "T-Shirt" normalises to the tokens {"t", "shirt"}; matching a
    # single token would resolve it through "shirt" and give a
    # t-shirt a shirt's 27%-formal profile, making it rank as
    # dressier than jeans. Compound names are therefore resolved
    # whole first - the same reason "Sweatshirt" must not be read as
    # "Shirt", or "Tank Top" as "Top".
    "t shirt": "Tshirts",
    "tank top": "Tshirts",
    "crop top": "Tops",
    "formal shirt": "Shirts",
    "casual shirt": "Shirts",
    "formal pants": "Trousers",
    "casual pants": "Trousers",
    "dhoti pants": "Salwar",
    "nehru jacket": "Blazers",
    "kurta men": "Kurtas",
    "kurta women": "Kurtis",
    "women kurta": "Kurtis",
    "leggings and salwars": "Leggings",
    "lehenga choli": "Lehenga Choli",
    # ---- single tokens -------------------------------------------
    "tshirt": "Tshirts",
    "shirt": "Shirts",
    "top": "Tops", "tops": "Tops",
    "blouse": "Tops",
    "jean": "Jeans", "jeans": "Jeans", "denim": "Jeans", "denims": "Jeans",
    "trouser": "Trousers", "trousers": "Trousers",
    "pant": "Trousers", "pants": "Trousers",
    "legging": "Leggings", "leggings": "Leggings",
    "short": "Shorts", "shorts": "Shorts",
    "skirt": "Skirts", "skirts": "Skirts",
    "kurta": "Kurtas", "kurtas": "Kurtas",
    "kurti": "Kurtis", "kurtis": "Kurtis",
    "saree": "Sarees", "sarees": "Sarees",
    "dress": "Dresses", "dresses": "Dresses",
    "gown": "Dresses", "gowns": "Dresses",
    "jacket": "Jackets", "jackets": "Jackets",
    "blazer": "Blazers", "blazers": "Blazers",
    "sweater": "Sweaters", "sweaters": "Sweaters",
    "sweatshirt": "Sweatshirts", "hoodie": "Sweatshirts",
    "churidar": "Churidar",
    "salwar": "Salwar", "salwars": "Salwar",
    "palazzo": "Patiala", "palazzos": "Patiala",
    "dupatta": "Dupatta", "dupattas": "Dupatta",
    "lehenga": "Lehenga Choli", "lehengas": "Lehenga Choli",
    "heel": "Heels", "heels": "Heels",
    "sneaker": "Casual Shoes", "sneakers": "Casual Shoes",
    "flat": "Flats", "flats": "Flats",
    "sandal": "Sandals", "sandals": "Sandals",
}


# Categories with no Myntra counterpart at all, given an explicit
# profile rather than being silently treated as neutral. These are
# ethnic menswear (absent from the Myntra subset) plus accessories.
EXPLICIT_PROFILES = {
    # Lehenga Choli has only 4 rows in the catalogue - far too few to
    # measure, so it is dropped from the generated table (see
    # build_occasion_model's minimum). Without an entry here it would
    # fall through to the neutral "casual" profile, which would rank a
    # lehenga as everyday wear and let it lose a wedding to a t-shirt.
    # Stated explicitly rather than implied by thin data.
    "lehenga": {"Ethnic": 0.85, "Party": 0.15},
    "lehengas": {"Ethnic": 0.85, "Party": 0.15},
    "anarkali": {"Ethnic": 0.9, "Party": 0.1},
    "sherwani": {"Ethnic": 1.0},
    "sherwanis": {"Ethnic": 1.0},
    "dhoti": {"Ethnic": 1.0},
    "nehru": {"Ethnic": 0.8, "Formal": 0.2},
    "mojari": {"Ethnic": 1.0},
    "mojaris": {"Ethnic": 1.0},
    "petticoat": {"Ethnic": 1.0},
    "petticoats": {"Ethnic": 1.0},
}


NEUTRAL_PROFILE = {"Casual": 1.0}


# How formal each usage label is, 0 (gym clothes) to 1 (interview
# suit). Used to give every garment a single formality number, which
# is what separates occasions the usage labels cannot - a date from a
# coffee run, an office day from an interview.
USAGE_FORMALITY = {
    "Sports": 0.05,
    "Travel": 0.2,
    "Casual": 0.3,
    "Ethnic": 0.6,
    "Party": 0.65,
    "Smart Casual": 0.65,
    "Formal": 0.95,
}


# Each occasion: the usage mix it rewards, and the formality it aims
# at. "tolerance" is how quickly the score falls off either side of
# that target - a party tolerates a wide range of registers, an
# interview very little.
OCCASION_TARGETS = {
    "casual":      {"usage": {"Casual": 1.0},                 "formality": 0.30, "tolerance": 0.35},
    "college":     {"usage": {"Casual": 0.9, "Sports": 0.1},  "formality": 0.28, "tolerance": 0.30},
    "day_outing":  {"usage": {"Casual": 1.0},                 "formality": 0.38, "tolerance": 0.30},
    "date":        {"usage": {"Casual": 0.6, "Smart Casual": 0.3, "Party": 0.1},
                                                              "formality": 0.55, "tolerance": 0.25},
    "party":       {"usage": {"Party": 0.5, "Smart Casual": 0.3, "Ethnic": 0.2},
                                                              "formality": 0.65, "tolerance": 0.28},
    "office":      {"usage": {"Formal": 0.7, "Smart Casual": 0.3},
                                                              "formality": 0.85, "tolerance": 0.25},
    "interview":   {"usage": {"Formal": 1.0},                 "formality": 0.95, "tolerance": 0.18},
    "wedding":     {"usage": {"Ethnic": 0.85, "Party": 0.15}, "formality": 0.80, "tolerance": 0.28},
    "traditional": {"usage": {"Ethnic": 1.0},                 "formality": 0.65, "tolerance": 0.30},
    "festive":     {"usage": {"Ethnic": 0.8, "Party": 0.2},   "formality": 0.70, "tolerance": 0.30},
    "travel":      {"usage": {"Casual": 0.8, "Travel": 0.2},  "formality": 0.25, "tolerance": 0.35},
}


# The occasion term's maximum contribution to an outfit's score. Sized
# against the existing terms (fit 20, colour ~20, style ~20) so it can
# genuinely re-rank outfits without being able to override a hard
# eligibility failure - see outfit_recommendation._score_outfit, where
# a flagged outfit loses more than this is worth.
MAX_OCCASION_POINTS = 18


def _tokens(category):
    normalized = re.sub(r"[_\-&()]", " ", (category or "").lower().strip())
    return [token for token in normalized.split() if token]


def article_for_category(category):
    """
    Which catalogue article type represents this garment, or None.

    Resolution runs widest-match-first, which is what keeps
    "T-Shirt" from being read as a shirt:

      1. the whole normalised name  ("t shirt" -> Tshirts)
      2. any adjacent word pair     ("nehru jacket" -> Blazers)
      3. a single token, longest first ("sweatshirt" before "shirt")
    """
    tokens = _tokens(category)

    if not tokens:
        return None

    whole = " ".join(tokens)

    if whole in CATEGORY_TO_ARTICLE:
        return CATEGORY_TO_ARTICLE[whole]

    for index in range(len(tokens) - 1):
        pair = f"{tokens[index]} {tokens[index + 1]}"
        if pair in CATEGORY_TO_ARTICLE:
            return CATEGORY_TO_ARTICLE[pair]

    for token in sorted(tokens, key=len, reverse=True):
        if token in CATEGORY_TO_ARTICLE:
            return CATEGORY_TO_ARTICLE[token]

    return None


def profile_for_category(category):
    """
    The usage mix for one garment, as measured shares that sum to ~1.

    Resolution order: an explicit profile for categories the dataset
    never contained, then the catalogue table (via
    article_for_category), then neutral.
    """
    tokens = _tokens(category)

    whole = " ".join(tokens)

    if whole in EXPLICIT_PROFILES:
        return EXPLICIT_PROFILES[whole]

    for token in sorted(tokens, key=len, reverse=True):
        if token in EXPLICIT_PROFILES:
            return EXPLICIT_PROFILES[token]

    article = article_for_category(category)

    if article and article in USAGE_TABLE:
        return USAGE_TABLE[article]

    return NEUTRAL_PROFILE


def formality_for_category(category):
    """
    One number, 0-1, for how dressed-up a garment is: its usage mix
    weighted by USAGE_FORMALITY. Jeans (100% casual) land at 0.30;
    trousers (54% casual, 45% formal) near 0.59; a saree (100% ethnic)
    at 0.60. Nothing is hand-assigned per garment - change the data
    and these move with it.
    """
    profile = profile_for_category(category)

    total = sum(profile.values()) or 1.0

    return sum(
        share * USAGE_FORMALITY.get(usage, 0.3)
        for usage, share in profile.items()
    ) / total


def _usage_match(profile, target_usage):
    """
    Overlap between what a garment IS and what an occasion WANTS: the
    shared mass of the two distributions. 1.0 means every catalogue
    item of this type carries exactly the usage the occasion asks for.
    """
    total = sum(profile.values()) or 1.0

    return sum(
        min(share / total, target_usage.get(usage, 0.0))
        for usage, share in profile.items()
    )


def occasion_fit(items, occasion):
    """
    Scores one complete outfit against one occasion, returning
    (points, reasons).

    Two halves, deliberately:

      * usage match - does this GARMENT TYPE belong at this kind of
        event, per the catalogue data.
      * formality distance - is the outfit pitched at the right level,
        which is what tells a date from a coffee run when both are
        "casual" garments.

    Reasons are plain English and traceable to the two halves above;
    they feed the "why this works" bullets, so they must never claim
    more than was actually computed.

    An unknown occasion scores 0 with no reasons - neutral, not
    penalised, so a new occasion string can never silently suppress
    every outfit.
    """
    target = OCCASION_TARGETS.get(occasion)

    if not target or not items:
        return 0, []

    clothing = [
        item for item in items
        if not _is_accessory(item.get("category"))
    ]

    scored_items = clothing or items

    usage_scores = []
    formalities = []

    for item in scored_items:
        profile = profile_for_category(item.get("category"))
        usage_scores.append(_usage_match(profile, target["usage"]))
        formalities.append(formality_for_category(item.get("category")))

    average_usage = sum(usage_scores) / len(usage_scores)

    outfit_formality = sum(formalities) / len(formalities)

    distance = abs(outfit_formality - target["formality"])

    # Linear falloff, floored at zero: an outfit a full tolerance-width
    # away from the target contributes nothing here rather than going
    # negative, because the eligibility filter has already removed
    # anything genuinely inappropriate.
    formality_score = max(0.0, 1.0 - distance / target["tolerance"])

    # Usage weighted slightly higher than formality: what a garment IS
    # for is measured from 44k real items, while the formality ladder
    # is a modelling choice.
    combined = 0.6 * average_usage + 0.4 * formality_score

    points = round(MAX_OCCASION_POINTS * combined, 1)

    reasons = []

    if average_usage >= 0.6:
        reasons.append(
            f"these pieces are typically worn for "
            f"{_dominant_usage(target['usage'])} occasions"
        )
    elif average_usage <= 0.25:
        reasons.append(
            f"more of an everyday choice than a "
            f"{occasion.replace('_', ' ')} one"
        )

    if formality_score >= 0.75:
        reasons.append(
            f"pitched at about the right level of dressiness for "
            f"{occasion.replace('_', ' ')}"
        )
    elif outfit_formality < target["formality"] - target["tolerance"] * 0.6:
        reasons.append(f"a little casual for {occasion.replace('_', ' ')}")
    elif outfit_formality > target["formality"] + target["tolerance"] * 0.6:
        reasons.append(f"a little dressy for {occasion.replace('_', ' ')}")

    return points, reasons[:2]


def _dominant_usage(target_usage):
    if not target_usage:
        return "everyday"

    label = max(target_usage.items(), key=lambda pair: pair[1])[0]

    return {
        "Casual": "everyday",
        "Formal": "formal",
        "Ethnic": "traditional",
        "Party": "party",
        "Smart Casual": "smart-casual",
        "Sports": "active",
        "Travel": "travel",
    }.get(label, label.lower())


_ACCESSORY_TOKENS = {"bag", "bags", "watch", "watches", "belt", "belts",
                     "jewelry", "jewellery", "dupatta", "dupattas"}


def _is_accessory(category):
    return bool(set(_tokens(category)) & _ACCESSORY_TOKENS)


def describe_category(category):
    """
    Diagnostic helper (used by the tests and by build_occasion_model):
    what the model believes about one garment.
    """
    return {
        "category": category,
        "profile": profile_for_category(category),
        "formality": round(formality_for_category(category), 3),
    }
