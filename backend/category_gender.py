"""
CATEGORY <-> GENDER heuristic (not a trained model).

This is what makes classification/recommendation/similar-search
"gender-aware" WITHOUT retraining the IndoFashion classifier - see
the project spec's explicit instruction: "Do not train a new model
unnecessarily if an effective improvement to the existing
architecture is possible."

Grounded in real data, not guesswork:

1. IndoFashion's own 16 trained classes already encode gender in
   their names (kurta_men vs women_kurta, mojaris_men vs
   mojaris_women, sherwanis, dhoti_pants, nehru_jackets -> menswear;
   lehenga, saree, blouse, gowns, petticoats, dupattas, palazzos,
   leggings_and_salwars -> womenswear). See
   dataset/indofashion/class_names.json on the live project - this
   is the exact, unmodified 16-class list the model was trained on.

2. For the Western "basics" IndoFashion was never trained on (Shirt,
   T-Shirt, Pant, Jacket, ...), this is cross-checked against
   dataset/kaggle_fashion/styles.csv (the Myntra dataset already
   sitting in the project, unused until now) - a REAL labeled
   dataset with an explicit "gender" column (Men/Women/Boys/Girls/
   Unisex) across 44,441 garments. Shirts/Jackets/Pants/T-Shirts
   appear in large numbers for BOTH Men and Women there, which is
   why they're kept unisex here rather than guessed one way.

Every category maps to exactly one bucket: "male", "female", or
"unisex". Unknown/unmapped categories default to "unisex" (the least
restrictive choice) rather than silently excluding a new category
type from a wardrobe.
"""

import re

MALE = "male"
FEMALE = "female"
UNISEX = "unisex"


def _normalize(category):
    if not category:
        return ""
    normalized = category.lower().strip()
    # Strips punctuation too, not just _/-/& - this matters here
    # specifically because the manual dropdown labels for
    # disambiguated categories use parentheses ("Kurta (Men)",
    # "Mojaris (Women)") and the male/female split below depends on
    # "men"/"women" surviving as a clean, separate token.
    normalized = re.sub(r"[_\-&()]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _tokens(category):
    normalized = _normalize(category)
    if not normalized:
        return set()
    return set(normalized.split(" "))


# Token -> gender bucket. Keys are checked against normalized
# category TOKENS (see _tokens above), the same way
# outfit_recommendation.CATEGORY_OCCASION_AFFINITY is - so both the
# manual dropdown label ("Kurta (Men)", "Dhoti Pants") and the raw
# IndoFashion class label ("kurta_men", "dhoti_pants") resolve to the
# same bucket.
CATEGORY_GENDER_TOKENS = {
    # ---- IndoFashion's 16 trained classes -------------------
    "blouse": FEMALE, "blouses": FEMALE,
    "dhoti": MALE,  # "dhoti pants" / "dhoti_pants"
    "dupatta": FEMALE, "dupattas": FEMALE,
    "gown": FEMALE, "gowns": FEMALE,
    "sherwani": MALE, "sherwanis": MALE,
    "nehru": MALE,  # "nehru jacket(s)" / "nehru_jackets"
    "palazzo": FEMALE, "palazzos": FEMALE,
    "petticoat": FEMALE, "petticoats": FEMALE,
    "saree": FEMALE, "sarees": FEMALE,
    "lehenga": FEMALE, "lehengas": FEMALE,
    "legging": FEMALE, "leggings": FEMALE,
    "salwar": FEMALE, "salwars": FEMALE,
    "mojari": UNISEX, "mojaris": UNISEX,  # disambiguated by "men"/"women" token below
    # ---- Western basics, cross-checked against styles.csv ---
    "shirt": UNISEX, "shirts": UNISEX,
    "tshirt": UNISEX, "tshirts": UNISEX, "t": UNISEX,
    "pant": UNISEX, "pants": UNISEX,
    "trouser": UNISEX, "trousers": UNISEX,
    "jean": UNISEX, "jeans": UNISEX,
    "short": UNISEX, "shorts": UNISEX,
    "jacket": UNISEX, "jackets": UNISEX,
    "bag": UNISEX, "bags": UNISEX,
    "watch": UNISEX, "watches": UNISEX,
    "belt": UNISEX, "belts": UNISEX,
    "jewelry": UNISEX, "jewellery": UNISEX,
    # ---- App-only categories not in IndoFashion's 16 classes -
    # (styles.csv confirms Skirts/Dresses skew overwhelmingly
    # Women in the actual labeled data, so these stay gendered
    # rather than unisex.)
    "skirt": FEMALE, "skirts": FEMALE,
    "dress": FEMALE, "dresses": FEMALE,
    "kurta": None,  # ambiguous alone - see _gender_from_tokens below
    "kurtas": None,
    "kurti": FEMALE, "kurtis": FEMALE,
    "men": MALE,
    "women": FEMALE,
}


def category_gender(category):
    """
    Returns "male", "female", or "unisex" for a given category
    string - a manual dropdown label ("Kurta (Men)", "Dhoti Pants",
    "Sherwani") or a raw IndoFashion class name ("kurta_men",
    "dhoti_pants", "sherwanis"). Never returns None: an unrecognized
    category defaults to "unisex" so an unexpected/new category type
    is never silently hidden from either gender's wardrobe.
    """

    tokens = _tokens(category)

    if not tokens:
        return UNISEX

    # "kurta"/"kurtas" alone is genuinely ambiguous (both
    # "kurta_men" and "women_kurta" contain it) - disambiguated by
    # whether "men" or "women" also appears in the same string.
    if tokens & {"kurta", "kurtas"}:
        if "women" in tokens:
            return FEMALE
        if "men" in tokens:
            return MALE
        # A bare "Kurta" with no men/women qualifier at all (legacy
        # data from before this category was gender-split) is left
        # unisex rather than guessed.
        return UNISEX

    # "mojari(s)" is unisex on its own but IS gendered once "men" or
    # "women" is present ("Mojaris (Men)", "mojaris_men").
    if tokens & {"mojari", "mojaris"}:
        if "women" in tokens:
            return FEMALE
        if "men" in tokens:
            return MALE
        return UNISEX

    buckets = set()
    for token in tokens:
        bucket = CATEGORY_GENDER_TOKENS.get(token)
        if bucket:
            buckets.add(bucket)

    if FEMALE in buckets and MALE not in buckets:
        return FEMALE
    if MALE in buckets and FEMALE not in buckets:
        return MALE
    if MALE in buckets and FEMALE in buckets:
        # Conflicting signals (shouldn't normally happen) - fall
        # back to unisex rather than guessing either direction.
        return UNISEX

    return UNISEX


def is_allowed_for_account(category, account_gender):
    """
    True unless `category` is gendered strictly opposite to
    `account_gender`. A category with no clear gender (unisex,
    or account_gender itself not set/unknown) is always allowed -
    this function only ever BLOCKS a confident cross-gender match,
    it never requires one.
    """

    if not account_gender:
        return True

    bucket = category_gender(category)

    if bucket == UNISEX:
        return True

    account_gender = account_gender.strip().lower()

    if account_gender == "male" and bucket == FEMALE:
        return False

    if account_gender == "female" and bucket == MALE:
        return False

    return True
