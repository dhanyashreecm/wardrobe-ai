"""
THE CANONICAL WARDROBE CATEGORY CATALOGUE - one list for the whole app.

Every category a user can pick, the AI can assign, or the recommender
can reason about is defined here once, with the genders it belongs to:

    men's account   -> only entries whose genders include "male"
    women's account -> only entries whose genders include "female"

Shared garments (T-Shirt, Jeans, Blazer, Sneakers...) list both
genders; gender-specific ones (Saree, Sherwani, Heels, Tie...) list
one. The frontend never keeps its own list: it asks
GET /api/wardrobe/categories, which is built from this module for the
signed-in account's saved gender.

Values are what gets stored on a wardrobe item. They are chosen so the
garment taxonomy (outfit_builder.kind_for) understands every one of
them, which the tests check.

Older items and the trained classifier use a few legacy names
("Denims", "Pant", "Hand Cuff", "Leggings & Salwars"...). They stay
valid through LEGACY_NAMES and are never rewritten behind the user's
back - see normalize_categories.py for the optional, reviewed
migration.
"""

import re

MALE, FEMALE = "male", "female"
M, F, B = (MALE,), (FEMALE,), (MALE, FEMALE)

# Section order is the order the Add Item dropdown shows.
SECTIONS = ["Tops", "Bottoms", "Dresses", "Traditional", "Outerwear",
            "Activewear", "Footwear", "Accessories"]

# (value, label, section, genders, flags)
#   flags: "material" - ask for the material (leather, gold, wool...)
#          "styling"  - ask casual vs wedding/festive
_ENTRIES = [
    # ---------------- Tops ----------------
    ("T-Shirt", "T-Shirt", "Tops", B, ()),
    ("Shirt", "Shirt", "Tops", B, ()),
    ("Casual Shirt", "Casual Shirt", "Tops", M, ()),
    ("Formal Shirt", "Formal Shirt", "Tops", M, ()),
    ("Polo Shirt", "Polo Shirt", "Tops", M, ()),
    ("Tank Top", "Tank Top", "Tops", B, ()),
    ("Top", "Top", "Tops", F, ()),
    ("Crop Top", "Crop Top", "Tops", F, ()),
    ("Camisole", "Camisole", "Tops", F, ()),
    ("Tunic", "Tunic", "Tops", F, ()),
    # ---------------- Bottoms ----------------
    ("Jeans", "Jeans / Denim", "Bottoms", B, ()),
    ("Trousers", "Trousers / Pants", "Bottoms", B, ()),
    ("Formal Trousers", "Formal Trousers", "Bottoms", M, ()),
    ("Chinos", "Chinos", "Bottoms", M, ()),
    ("Cargo Pants", "Cargo Pants", "Bottoms", M, ()),
    ("Wide-Leg Pants", "Wide-Leg Pants", "Bottoms", F, ()),
    ("Shorts", "Shorts", "Bottoms", B, ()),
    ("Skirt", "Skirt", "Bottoms", F, ()),
    # ---------------- Dresses ----------------
    ("Dress", "Dress", "Dresses", F, ()),
    ("Gown", "Gown", "Dresses", F, ()),
    ("Jumpsuit", "Jumpsuit", "Dresses", F, ()),
    ("Romper", "Romper", "Dresses", F, ()),
    # ---------------- Traditional ----------------
    ("Kurta (Men)", "Kurta", "Traditional", M, ("styling",)),
    ("Kurta Set (Men)", "Kurta Set / Kurta Pajama", "Traditional", M, ("styling",)),
    ("Sherwani", "Sherwani", "Traditional", M, ()),
    ("Nehru Jacket", "Nehru Jacket", "Traditional", M, ()),
    ("Dhoti Pants", "Dhoti Pants", "Traditional", M, ()),
    ("Pajama", "Pajama / Churidar", "Traditional", M, ()),
    ("Saree", "Saree", "Traditional", F, ("styling",)),
    ("Casual Saree", "Casual Saree", "Traditional", F, ()),
    ("Wedding Saree", "Wedding Saree", "Traditional", F, ()),
    ("Lehenga", "Lehenga", "Traditional", F, ("styling",)),
    ("Salwar Suit", "Salwar Suit", "Traditional", F, ("styling",)),
    ("Kurta (Women)", "Kurta / Kurti", "Traditional", F, ("styling",)),
    ("Kurta Set (Women)", "Kurta Set", "Traditional", F, ("styling",)),
    ("Anarkali", "Anarkali", "Traditional", F, ("styling",)),
    ("Salwar", "Salwar / Churidar", "Traditional", F, ()),
    ("Palazzos", "Palazzos", "Traditional", F, ()),
    ("Sharara", "Sharara", "Traditional", F, ()),
    ("Dupatta", "Dupatta", "Traditional", F, ()),
    ("Blouse", "Saree / Lehenga Blouse", "Traditional", F, ()),
    # ---------------- Outerwear ----------------
    ("Jacket", "Jacket", "Outerwear", B, ("material",)),
    ("Blazer", "Blazer", "Outerwear", B, ("material",)),
    ("Coat", "Coat", "Outerwear", B, ("material",)),
    ("Bomber Jacket", "Bomber Jacket", "Outerwear", M, ("material",)),
    ("Denim Jacket", "Denim Jacket", "Outerwear", B, ()),
    ("Leather Jacket", "Leather Jacket", "Outerwear", B, ()),
    ("Hoodie", "Hoodie", "Outerwear", B, ("material",)),
    ("Cardigan", "Cardigan / Sweater", "Outerwear", B, ("material",)),
    ("Shrug", "Shrug", "Outerwear", F, ("material",)),
    # ---------------- Activewear ----------------
    ("Sports T-Shirt", "Sports T-Shirt", "Activewear", B, ()),
    ("Sports Jersey", "Sports Jersey", "Activewear", B, ()),
    ("Track Pants", "Track Pants", "Activewear", B, ()),
    ("Joggers", "Joggers", "Activewear", B, ()),
    ("Athletic Shorts", "Athletic Shorts", "Activewear", B, ()),
    ("Leggings", "Leggings", "Activewear", F, ()),
    ("Track Jacket", "Track / Sports Jacket", "Activewear", B, ()),
    # ---------------- Footwear ----------------
    ("Sneakers", "Sneakers", "Footwear", B, ()),
    ("Sports Shoes", "Sports Shoes", "Footwear", B, ()),
    ("Formal Shoes", "Formal Shoes", "Footwear", B, ()),
    ("Loafers", "Loafers", "Footwear", B, ()),
    ("Boots", "Boots", "Footwear", B, ()),
    ("Sandals", "Sandals", "Footwear", B, ()),
    ("Slides", "Slippers / Slides", "Footwear", M, ()),
    ("Heels", "Heels", "Footwear", F, ()),
    ("Flats", "Flats", "Footwear", F, ()),
    ("Mojaris (Men)", "Mojaris / Juttis", "Footwear", M, ()),
    ("Mojaris (Women)", "Mojaris / Juttis", "Footwear", F, ()),
    # ---------------- Accessories ----------------
    ("Belt", "Belt", "Accessories", B, ("material",)),
    ("Watch", "Watch", "Accessories", B, ("material",)),
    ("Bag", "Bag", "Accessories", B, ("material",)),
    ("Handbag", "Handbag", "Accessories", F, ("material",)),
    ("Clutch", "Clutch / Potli", "Accessories", F, ("material",)),
    ("Tie", "Tie", "Accessories", M, ()),
    ("Bow Tie", "Bow Tie", "Accessories", M, ()),
    ("Cap", "Cap / Hat", "Accessories", B, ()),
    ("Sunglasses", "Sunglasses", "Accessories", B, ()),
    ("Bracelet", "Bracelet / Kada", "Accessories", M, ("material",)),
    ("Chain", "Chain", "Accessories", M, ("material",)),
    ("Earrings", "Earrings", "Accessories", F, ("material",)),
    ("Necklace", "Necklace / Chain", "Accessories", F, ("material",)),
    ("Ring", "Ring", "Accessories", B, ("material",)),
    ("Bangles", "Bracelet / Bangles", "Accessories", F, ("material",)),
    ("Head Accessory", "Head Accessory", "Accessories", F, ("material",)),
]

CATALOG = {
    value: {"value": value, "label": label, "section": section,
            "genders": genders, "flags": set(flags)}
    for value, label, section, genders, flags in _ENTRIES
}

# Names used by older items, the trained classifier and the IndoFashion
# model -> the catalogue entry they mean. Recognised, never forced.
LEGACY_NAMES = {
    "denims": "Jeans", "denim": "Jeans", "jean": "Jeans",
    "pant": "Trousers", "pants": "Trousers", "trouser": "Trousers",
    "tshirt": "T-Shirt", "t shirt": "T-Shirt", "tshirts": "T-Shirt",
    "footwear": None,  # generic shoes: gender-neutral, see is_valid_for
    "shoes": None,
    "hand cuff": None, "neck chain": None, "finger ring": None,
    "jewelry": None, "jewellery": None,
    "leggings & salwars": "Salwar", "leggings and salwars": "Salwar",
    "leggings_and_salwars": "Salwar",
    "kurta men": "Kurta (Men)", "kurta_men": "Kurta (Men)",
    "women kurta": "Kurta (Women)", "women_kurta": "Kurta (Women)",
    "mojaris men": "Mojaris (Men)", "mojaris_men": "Mojaris (Men)",
    "mojaris women": "Mojaris (Women)", "mojaris_women": "Mojaris (Women)",
    "dhoti_pants": "Dhoti Pants", "nehru_jackets": "Nehru Jacket",
    "sherwanis": "Sherwani", "sarees": "Saree", "lehengas": "Lehenga",
    "gowns": "Gown", "palazzos": "Palazzos", "dupattas": "Dupatta",
    "petticoat": None, "petticoats": None,
}

# Legacy names that are valid for BOTH genders but are not a single
# catalogue entry (generic "Footwear", "Hand Cuff"...), and legacy names
# valid for one gender only.
_LEGACY_GENDERS = {
    "footwear": B, "shoes": B, "hand cuff": B, "neck chain": B,
    "finger ring": B, "jewelry": B, "jewellery": B,
    "petticoat": F, "petticoats": F,
}


def _key(category):
    text = (category or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


_BY_KEY = {_key(value): value for value in CATALOG}


def canonical(category):
    """Catalogue value for a category name (legacy names included), or None."""
    key = _key(category)
    if not key:
        return None
    if key in _BY_KEY:
        return _BY_KEY[key]
    mapped = LEGACY_NAMES.get(key) or LEGACY_NAMES.get(key.replace("_", " "))
    return mapped


def known(category):
    """True for catalogue values and recognised legacy names."""
    key = _key(category)
    return bool(canonical(category)) or key in _LEGACY_GENDERS


def genders_of(category):
    """Tuple of genders the category belongs to, or None if unknown."""
    value = canonical(category)
    if value:
        return CATALOG[value]["genders"]
    return _LEGACY_GENDERS.get(_key(category))


def normalize_gender(gender):
    g = (gender or "").strip().lower()
    if g in ("male", "man", "men", "m"):
        return MALE
    if g in ("female", "woman", "women", "f"):
        return FEMALE
    return None


def is_valid_for(category, gender):
    """
    HARD RULE used by uploads and edits: the category must be in the
    catalogue (or a recognised legacy name) AND belong to this gender.
    """
    g = normalize_gender(gender)
    genders = genders_of(category)
    if genders is None or g is None:
        return False
    return g in genders


def categories_for(gender):
    """[{name, categories:[{value,label,flags}]}] for one gender, in order."""
    g = normalize_gender(gender)
    if g is None:
        return []
    sections = []
    for section in SECTIONS:
        entries = [
            {"value": e["value"], "label": e["label"], "flags": sorted(e["flags"])}
            for e in CATALOG.values()
            if e["section"] == section and g in e["genders"]
        ]
        if entries:
            sections.append({"name": section, "categories": entries})
    return sections


# Legacy names whose modern equivalent depends on who wears it.
_BY_GENDER = {
    "hand cuff": {MALE: "Bracelet", FEMALE: "Bangles"},
    "neck chain": {MALE: "Chain", FEMALE: "Necklace"},
    "finger ring": {MALE: "Ring", FEMALE: "Ring"},
}


def canonical_for_gender(category, gender):
    """
    The name to STORE for a new upload/edit: the catalogue value when
    there is one (legacy "Denims" -> "Jeans", "Hand Cuff" -> "Bangles"
    for a women's account), otherwise the name as given (generic legacy
    "Footwear"). Call only after is_valid_for() passed.
    """
    g = normalize_gender(gender)
    by_gender = _BY_GENDER.get(_key(category))
    if by_gender and g in by_gender:
        return by_gender[g]
    return canonical(category) or (category or "").strip()


def values_for(gender):
    g = normalize_gender(gender)
    return {e["value"] for e in CATALOG.values() if g in e["genders"]}


# ============================================================
# WHAT THE PHOTO CLASSIFIER MAY DECIDE ON ITS OWN
#
# The trained classifier (backend/garment_classifier.py) knows 32
# classes, several of them much broader than this catalogue: it has one
# "Pant" class (trousers, chinos, track pants and joggers all look like
# "Pant" to it), one "Footwear" class, one "Jacket" class (jacket,
# blazer, coat...), and it merges leggings with salwars. It has no
# class at all for Sports Jersey, Formal Shoes, Track Pants, Blazer,
# Crop Top, Jumpsuit...
#
# So a prediction is applied automatically ONLY when the class means
# exactly one catalogue category for this gender, the class scored
# well on its held-out test set (F1 >= 0.78, from
# backend/data/garment_classifier.json) and the model is confident.
# Otherwise the user is asked to pick, from that family only, with the
# model's best guess pre-selected. Nothing is silently mapped to a
# more specific category the model cannot actually see.
# ============================================================

CLASSIFIER_FAMILIES = {
    # reliable, one meaning
    "Saree": ["Saree"], "Lehenga": ["Lehenga"], "Blouse": ["Blouse"],
    "Denims": ["Jeans"], "Shorts": ["Shorts", "Athletic Shorts"],
    "Sherwani": ["Sherwani"], "Nehru Jacket": ["Nehru Jacket"],
    "Kurta (Men)": ["Kurta (Men)", "Kurta Set (Men)"],
    "Mojaris (Men)": ["Mojaris (Men)"], "Mojaris (Women)": ["Mojaris (Women)"],
    "Palazzos": ["Palazzos", "Sharara"], "Petticoat": ["Petticoat"],
    "Belt": ["Belt"], "Watch": ["Watch"], "Earrings": ["Earrings"],
    "Neck Chain": ["Chain", "Necklace"], "Finger Ring": ["Ring"],
    "Hand Cuff": ["Bracelet", "Bangles"],
    # broad classes: always the user's choice within the family
    "Shirt": ["Shirt", "Casual Shirt", "Formal Shirt"],
    "T-Shirt": ["T-Shirt", "Polo Shirt", "Sports T-Shirt", "Sports Jersey", "Tank Top"],
    "Top": ["Top", "Crop Top", "Tank Top", "Camisole", "Tunic", "T-Shirt"],
    "Pant": ["Trousers", "Formal Trousers", "Chinos", "Cargo Pants", "Wide-Leg Pants",
             "Track Pants", "Joggers"],
    "Jacket": ["Jacket", "Blazer", "Coat", "Bomber Jacket", "Denim Jacket", "Leather Jacket",
               "Hoodie", "Cardigan", "Shrug", "Track Jacket"],
    "Footwear": ["Sneakers", "Sports Shoes", "Formal Shoes", "Loafers", "Boots", "Sandals",
                 "Slides", "Heels", "Flats"],
    "Bag": ["Bag", "Handbag", "Clutch"],
    "Leggings & Salwars": ["Leggings", "Salwar", "Jeans"],
    # weak classes (test F1 below 0.78): the user confirms
    "Dress": ["Dress", "Jumpsuit", "Romper", "Gown"],
    "Gown": ["Gown", "Dress", "Anarkali"],
    "Kurta (Women)": ["Kurta (Women)", "Kurta Set (Women)", "Salwar Suit", "Anarkali", "Tunic"],
    "Dhoti Pants": ["Dhoti Pants", "Pajama"],
    "Dupatta": ["Dupatta", "Saree"],
    "Skirt": ["Skirt", "Lehenga"],
}
WEAK_CLASSES = {"Dress", "Gown", "Kurta (Women)", "Dhoti Pants", "Dupatta", "Skirt"}


def classifier_decision(prediction, gender, threshold):
    """
    prediction: {"category", "confidence", "top": [(class, prob), ...]}
    Returns {"category": value} when the model may decide, otherwise
    {"choose": [{"value", "label"}...], "guess": value or None,
    "reason": text}. Every value is valid for `gender`.
    """
    g = normalize_gender(gender)
    allowed = values_for(g)

    def family(label):
        options = [v for v in CLASSIFIER_FAMILIES.get(label, [canonical(label) or label]) if v in allowed]
        if label == "Petticoat" and g == FEMALE:
            options = ["Petticoat"]
        return options

    label = prediction.get("category")
    confidence = prediction.get("confidence") or 0
    options = family(label)
    if confidence >= threshold and label not in WEAK_CLASSES and len(options) == 1:
        return {"category": options[0]}

    # not sure, or a broad class: offer this family (plus the runner-up's)
    for other, _ in (prediction.get("top") or [])[1:2]:
        if confidence < threshold:
            options += [v for v in family(other) if v not in options]
    choices = [{"value": v, "label": CATALOG[v]["label"] if v in CATALOG else v} for v in options]
    if confidence < threshold:
        reason = "The AI isn't sure what this is"
    else:
        friendly = {"Pant": "trousers", "Denims": "jeans", "Leggings & Salwars": "leggings or a salwar",
                    "Footwear": "shoes", "T-Shirt": "a T-shirt", "Top": "a top", "Shirt": "a shirt",
                    "Jacket": "a jacket", "Bag": "a bag", "Dress": "a dress", "Gown": "a gown",
                    "Shorts": "shorts", "Skirt": "a skirt", "Dupatta": "a dupatta"}.get(label, (label or "").lower())
        reason = f"It looks like {friendly} - please choose the exact type"
    return {"choose": choices, "guess": options[0] if options else None, "reason": reason}
