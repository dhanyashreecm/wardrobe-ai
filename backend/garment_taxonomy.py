"""
WHAT KIND OF GARMENT IS THIS, AND WHAT MAY THE MODEL SAY ABOUT IT?

Two jobs, both aimed at the same class of bug.

1. ROLES - is this a top, a bottom, a one-piece, outerwear, footwear
   or an accessory. Candidate generation uses roles so an outfit can
   never be two bottoms (jeans + leggings) or two tops (crop top +
   blouse), whatever their colours or styles score.

2. FAMILIES - which broad family a category belongs to, and therefore
   whether the image model is entitled to overrule the user about it.

Why (2) exists
--------------
The IndoFashion classifier was trained on exactly 15 classes, all
Indian ethnic wear: blouse, dhoti_pants, dupattas, gowns, kurta_men,
leggings_and_salwars, lehenga, mojaris_men, mojaris_women,
nehru_jackets, palazzos, petticoats, saree, sherwanis, women_kurta.
It has never seen jeans, a t-shirt, a skirt or a crop top, so for any
of those it still returns one of its 15 - whichever looks nearest. Its
nearest neighbour for a plain skirt is a petticoat; for jeans,
leggings_and_salwars; for a crop top, a blouse.

That is the model behaving exactly as trained. The BUG was that
app.py trusted any of those 15 labels at 0.5 confidence and wrote it
over the category the user had chosen by hand - so a user who
correctly selected "Jeans" got "Leggings & Salwars" saved instead,
with no way to tell it had happened.

The rule here: a model may refine a user's choice WITHIN a family
(saree vs lehenga is a genuine call it is qualified to make, both are
ethnic one-pieces it was trained on), and it may propose a category
when the user offered none. It may never silently move an item across
families - from western bottom to ethnic bottom, or from western top
to ethnic top - because that is precisely the move it makes when
asked about a garment outside its training set. Cross-family
disagreements become a SUGGESTION the user confirms, not a silent
overwrite.

This costs nothing when the model is right (the user confirms in one
click) and prevents the whole class of "the app renamed my clothes"
failures when it is wrong.
"""

import re


# ---------------------------------------------------------------
# ROLES - what part of an outfit an item can fill
# ---------------------------------------------------------------

TOP = "TOP"
BOTTOM = "BOTTOM"
ONE_PIECE = "ONE_PIECE"
OUTERWEAR = "OUTERWEAR"
FOOTWEAR = "FOOTWEAR"
ACCESSORY = "ACCESSORY"
UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------
# FAMILIES - the taxonomy the override rule is written against
# ---------------------------------------------------------------

WESTERN_TOP = "western_top"
WESTERN_BOTTOM = "western_bottom"
WESTERN_ONE_PIECE = "western_one_piece"
ETHNIC_TOP = "ethnic_top"
ETHNIC_BOTTOM = "ethnic_bottom"
ETHNIC_ONE_PIECE = "ethnic_one_piece"
OUTERWEAR_FAMILY = "outerwear"
FOOTWEAR_FAMILY = "footwear"
ACCESSORY_FAMILY = "accessory"


# token -> (family, role). Written as tokens so a dropdown label
# ("Kurta (Men)"), a stored category ("Dhoti Pants") and a raw model
# class ("kurta_men") all resolve the same way.
#
# Multi-word keys are matched before single tokens - see _resolve -
# so "crop top" is a top rather than being read through "top", and
# "t shirt" is not read through "shirt".
TAXONOMY = {
    # ---- western tops -------------------------------------------
    "t shirt": (WESTERN_TOP, TOP),
    "tshirt": (WESTERN_TOP, TOP),
    "crop top": (WESTERN_TOP, TOP),
    "tank top": (WESTERN_TOP, TOP),
    "shirt": (WESTERN_TOP, TOP),
    "top": (WESTERN_TOP, TOP),
    "tops": (WESTERN_TOP, TOP),
    "sweatshirt": (WESTERN_TOP, TOP),
    "hoodie": (WESTERN_TOP, TOP),
    "sweater": (WESTERN_TOP, TOP),

    # ---- western bottoms ----------------------------------------
    "jean": (WESTERN_BOTTOM, BOTTOM),
    "jeans": (WESTERN_BOTTOM, BOTTOM),
    "denim": (WESTERN_BOTTOM, BOTTOM),
    "denims": (WESTERN_BOTTOM, BOTTOM),
    "trouser": (WESTERN_BOTTOM, BOTTOM),
    "trousers": (WESTERN_BOTTOM, BOTTOM),
    "pant": (WESTERN_BOTTOM, BOTTOM),
    "pants": (WESTERN_BOTTOM, BOTTOM),
    "short": (WESTERN_BOTTOM, BOTTOM),
    "shorts": (WESTERN_BOTTOM, BOTTOM),
    "skirt": (WESTERN_BOTTOM, BOTTOM),
    "skirts": (WESTERN_BOTTOM, BOTTOM),

    # ---- western one-pieces --------------------------------------
    "dress": (WESTERN_ONE_PIECE, ONE_PIECE),
    "dresses": (WESTERN_ONE_PIECE, ONE_PIECE),
    "gown": (WESTERN_ONE_PIECE, ONE_PIECE),
    "gowns": (WESTERN_ONE_PIECE, ONE_PIECE),

    # ---- ethnic tops ---------------------------------------------
    "blouse": (ETHNIC_TOP, TOP),
    "blouses": (ETHNIC_TOP, TOP),
    "kurta": (ETHNIC_TOP, TOP),
    "kurtas": (ETHNIC_TOP, TOP),
    "kurti": (ETHNIC_TOP, TOP),
    "kurtis": (ETHNIC_TOP, TOP),

    # ---- ethnic bottoms ------------------------------------------
    "legging": (ETHNIC_BOTTOM, BOTTOM),
    "leggings": (ETHNIC_BOTTOM, BOTTOM),
    "salwar": (ETHNIC_BOTTOM, BOTTOM),
    "salwars": (ETHNIC_BOTTOM, BOTTOM),
    "churidar": (ETHNIC_BOTTOM, BOTTOM),
    "palazzo": (ETHNIC_BOTTOM, BOTTOM),
    "palazzos": (ETHNIC_BOTTOM, BOTTOM),
    "petticoat": (ETHNIC_BOTTOM, BOTTOM),
    "petticoats": (ETHNIC_BOTTOM, BOTTOM),
    "dhoti": (ETHNIC_BOTTOM, BOTTOM),

    # ---- ethnic one-pieces ---------------------------------------
    "saree": (ETHNIC_ONE_PIECE, ONE_PIECE),
    "sarees": (ETHNIC_ONE_PIECE, ONE_PIECE),
    "lehenga": (ETHNIC_ONE_PIECE, ONE_PIECE),
    "lehengas": (ETHNIC_ONE_PIECE, ONE_PIECE),
    "anarkali": (ETHNIC_ONE_PIECE, ONE_PIECE),
    "sherwani": (ETHNIC_ONE_PIECE, ONE_PIECE),
    "sherwanis": (ETHNIC_ONE_PIECE, ONE_PIECE),

    # ---- outerwear ------------------------------------------------
    "jacket": (OUTERWEAR_FAMILY, OUTERWEAR),
    "jackets": (OUTERWEAR_FAMILY, OUTERWEAR),
    "coat": (OUTERWEAR_FAMILY, OUTERWEAR),
    "coats": (OUTERWEAR_FAMILY, OUTERWEAR),
    "blazer": (OUTERWEAR_FAMILY, OUTERWEAR),
    "blazers": (OUTERWEAR_FAMILY, OUTERWEAR),
    "nehru": (OUTERWEAR_FAMILY, OUTERWEAR),
    "cardigan": (OUTERWEAR_FAMILY, OUTERWEAR),

    # ---- footwear / accessories -----------------------------------
    "mojari": (FOOTWEAR_FAMILY, FOOTWEAR),
    "mojaris": (FOOTWEAR_FAMILY, FOOTWEAR),
    "heel": (FOOTWEAR_FAMILY, FOOTWEAR),
    "heels": (FOOTWEAR_FAMILY, FOOTWEAR),
    "sneaker": (FOOTWEAR_FAMILY, FOOTWEAR),
    "sneakers": (FOOTWEAR_FAMILY, FOOTWEAR),
    "shoe": (FOOTWEAR_FAMILY, FOOTWEAR),
    "shoes": (FOOTWEAR_FAMILY, FOOTWEAR),
    "bag": (ACCESSORY_FAMILY, ACCESSORY),
    "bags": (ACCESSORY_FAMILY, ACCESSORY),
    "watch": (ACCESSORY_FAMILY, ACCESSORY),
    "watches": (ACCESSORY_FAMILY, ACCESSORY),
    "belt": (ACCESSORY_FAMILY, ACCESSORY),
    "belts": (ACCESSORY_FAMILY, ACCESSORY),
    "jewelry": (ACCESSORY_FAMILY, ACCESSORY),
    "jewellery": (ACCESSORY_FAMILY, ACCESSORY),
    "dupatta": (ACCESSORY_FAMILY, ACCESSORY),
    "dupattas": (ACCESSORY_FAMILY, ACCESSORY),
}


# The families the IndoFashion model was actually trained on. A
# prediction is only ever trusted for a category inside these - the
# model has no western training data at all, so a western garment is
# something it can only ever guess about.
MODEL_COMPETENT_FAMILIES = {ETHNIC_TOP, ETHNIC_BOTTOM, ETHNIC_ONE_PIECE,
                            FOOTWEAR_FAMILY, ACCESSORY_FAMILY}


def _tokens(category):
    normalized = re.sub(r"[_\-&()]", " ", (category or "").lower().strip())
    return [token for token in normalized.split() if token]


def _resolve(category):
    tokens = _tokens(category)

    if not tokens:
        return None

    whole = " ".join(tokens)

    if whole in TAXONOMY:
        return TAXONOMY[whole]

    for index in range(len(tokens) - 1):
        pair = f"{tokens[index]} {tokens[index + 1]}"
        if pair in TAXONOMY:
            return TAXONOMY[pair]

    for token in sorted(tokens, key=len, reverse=True):
        if token in TAXONOMY:
            return TAXONOMY[token]

    return None


def family_for(category):
    """The garment family, or None for something unrecognised."""
    resolved = _resolve(category)
    return resolved[0] if resolved else None


def role_for(category):
    """
    TOP / BOTTOM / ONE_PIECE / OUTERWEAR / FOOTWEAR / ACCESSORY, or
    UNKNOWN. Unknown is deliberately not treated as any role, so a
    new or misspelled category can never be paired into a nonsense
    outfit on the assumption that it is a top.
    """
    resolved = _resolve(category)
    return resolved[1] if resolved else UNKNOWN


def is_bottom(category):
    return role_for(category) == BOTTOM


def is_top(category):
    return role_for(category) == TOP


def is_one_piece(category):
    return role_for(category) == ONE_PIECE


def outfit_shape_is_valid(categories):
    """
    True if this set of garments could be a real outfit.

    The rules are about ROLES, not about specific garments, so nothing
    needs updating when a category is added:

      * at most one bottom (jeans + leggings is not an outfit)
      * at most one top, unless one of them is outerwear (a shirt
        under a blazer is a legitimate layering, a crop top under a
        blouse is not)
      * a one-piece (saree, lehenga, dress) does not take a separate
        top or bottom
      * otherwise a complete outfit needs a top AND a bottom
    """
    roles = [role_for(category) for category in categories]

    if roles.count(BOTTOM) > 1:
        return False

    if roles.count(TOP) > 1:
        return False

    if roles.count(ONE_PIECE) > 1:
        return False

    if ONE_PIECE in roles and (TOP in roles or BOTTOM in roles):
        return False

    if ONE_PIECE in roles:
        return True

    return TOP in roles and BOTTOM in roles


def model_may_override(manual_category, predicted_category):
    """
    May the image model's prediction REPLACE what the user chose?

    Returns (allowed, reason). Allowed only when:

      * the user gave no category at all - nothing to overrule; or
      * the prediction stays inside the same family, which is the
        model refining a call it was trained to make (saree vs
        lehenga, kurta vs kurti).

    Anything crossing a family boundary is refused, because that is
    the signature of the model being asked about a garment outside
    its training set: a western bottom "becoming" an ethnic bottom, a
    western top "becoming" an ethnic top. Those become a suggestion
    for the user to confirm instead.
    """
    if not manual_category:
        return True, "no manual category was chosen"

    manual_family = family_for(manual_category)
    predicted_family = family_for(predicted_category)

    if manual_family is None:
        return True, "the chosen category is not in the taxonomy"

    if predicted_family is None:
        return False, "the prediction is not in the taxonomy"

    if manual_family == predicted_family:
        return True, f"both are {manual_family.replace('_', ' ')}"

    if predicted_family not in MODEL_COMPETENT_FAMILIES:
        return False, "the model was not trained on this kind of garment"

    return False, (
        f"the model would move this from {manual_family.replace('_', ' ')} "
        f"to {predicted_family.replace('_', ' ')}, which it is not "
        "qualified to decide - the model has no training data for "
        "western garments"
    )
