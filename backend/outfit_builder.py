"""
OUTFIT BUILDER - which garments can actually be worn TOGETHER.

outfit_recommendation.py decides which items suit an OCCASION and how
good a finished outfit is (colour, style, weather, occasion fit). This
module answers the question that has to come first: is this set of
garments a real outfit at all?

It exists because the old approach grouped clothes into loose buckets
("tops", "bottoms", "accessories") and paired anything with anything:

  * a Sherwani could be paired with jeans, a saree Blouse with shorts
  * "Leggings & Salwars" was treated as a one-piece dress, so leggings
    were recommended on their own as a complete outfit
  * a saree or lehenga never came with its blouse
  * accessories were handed out in rotation (outfit 1 got accessory 1,
    outfit 2 got accessory 2...), so a Dupatta could land on a shirt
    and jeans, or Mojaris on a western outfit
  * only the first 8 tops / 8 bottoms were ever looked at

The rules here are explicit, readable tables - no machine learning -
so every "these go together" decision can be explained in a viva.

Every item is first given a KIND (tshirt, kurta_women, saree, mojari,
belt...). The tables below say which kinds pair with which.
"""

import re

from backend.color_theory import classify_color, color_harmony


# ============================================================
# 1. KIND - what exactly is this garment
# ============================================================

# Checked top to bottom, first match wins. Order matters:
#   - "dhoti" before "pant"  ("Dhoti Pants" is a dhoti, not trousers)
#   - "t shirt" before "shirt"
#   - "petticoat" first (it is an under-layer, never shown)
_KIND_RULES = [
    ("petticoat", {"petticoat", "petticoats"}),
    ("dhoti", {"dhoti", "dhotis"}),
    ("tshirt", {"tshirt", "tshirts", "tee", "tees", "top", "tops", "crop",
                "tank", "sweatshirt", "hoodie", "sweater", "polo"}),
    ("shirt", {"shirt", "shirts"}),
    ("blouse", {"blouse", "blouses", "choli"}),
    ("sherwani", {"sherwani", "sherwanis"}),
    ("kurta", {"kurta", "kurtas", "kurti", "kurtis"}),
    ("jeans", {"jean", "jeans", "denim", "denims"}),
    ("pant", {"pant", "pants", "trouser", "trousers", "chino", "chinos",
              "pajama", "pyjama"}),
    ("shorts", {"short", "shorts"}),
    ("skirt", {"skirt", "skirts"}),
    ("salwar", {"legging", "leggings", "salwar", "salwars", "churidar"}),
    ("palazzo", {"palazzo", "palazzos"}),
    ("saree", {"saree", "sarees", "sari"}),
    ("lehenga", {"lehenga", "lehengas"}),
    ("anarkali", {"anarkali", "anarkalis"}),
    ("gown", {"gown", "gowns"}),
    ("dress", {"dress", "dresses", "frock", "frocks", "jumpsuit"}),
    ("nehru", {"nehru"}),
    ("blazer", {"blazer", "blazers", "suit"}),
    ("coat", {"coat", "coats", "overcoat"}),
    ("jacket", {"jacket", "jackets", "cardigan", "shrug"}),
    ("mojari", {"mojari", "mojaris", "jutti", "juttis", "kolhapuri"}),
    ("boots", {"boot", "boots"}),
    ("footwear", {"footwear", "shoe", "shoes", "sneaker", "sneakers",
                  "heel", "heels", "sandal", "sandals", "flats", "loafers"}),
    ("dupatta", {"dupatta", "dupattas", "stole"}),
    ("belt", {"belt", "belts"}),
    ("bag", {"bag", "bags", "clutch", "purse", "handbag"}),
    ("watch", {"watch", "watches"}),
    ("earrings", {"earring", "earrings", "jhumka", "jhumkas"}),
    ("necklace", {"necklace", "necklaces", "chain", "chains", "pendant"}),
    ("ring", {"ring", "rings"}),
    ("bracelet", {"cuff", "cuffs", "bracelet", "bracelets", "bangle",
                  "bangles", "kada"}),
    ("head", {"head", "headwear", "tikka", "headband", "hairband"}),
    ("jewelry", {"jewelry", "jewellery"}),
]

# "Kurta (Men)" / "kurta_men" / "Kurta (Women)" / "women_kurta"
_WOMEN_TOKENS = {"women", "womens", "woman", "ladies", "female"}
_MEN_TOKENS = {"men", "mens", "man", "male"}


def _tokens(category):
    text = (category or "").lower()
    text = re.sub(r"t[\s_\-]?shirt", "tshirt", text)
    text = re.sub(r"[^a-z]+", " ", text)
    return set(text.split())


def kind_for(category):
    """The specific garment kind, or None if unrecognised."""
    tokens = _tokens(category)
    if not tokens:
        return None

    for kind, markers in _KIND_RULES:
        if tokens & markers:
            if kind == "kurta":
                if tokens & _WOMEN_TOKENS or tokens & {"kurti", "kurtis"}:
                    return "kurta_women"
                if tokens & _MEN_TOKENS:
                    return "kurta_men"
            return kind

    return None


# ============================================================
# 2. ROLE - which slot of an outfit a kind fills
# ============================================================

TOP, BOTTOM, ONE_PIECE, LAYER, FOOTWEAR, ACCESSORY, SET_PART, HIDDEN = (
    "top", "bottom", "one_piece", "layer", "footwear", "accessory",
    "set_part", "hidden",
)

ROLE = {
    "tshirt": TOP, "shirt": TOP, "kurta": TOP, "kurta_men": TOP,
    "kurta_women": TOP, "sherwani": TOP,
    "jeans": BOTTOM, "pant": BOTTOM, "shorts": BOTTOM, "skirt": BOTTOM,
    "dhoti": BOTTOM, "salwar": BOTTOM, "palazzo": BOTTOM,
    "dress": ONE_PIECE, "gown": ONE_PIECE, "saree": ONE_PIECE,
    "lehenga": ONE_PIECE, "anarkali": ONE_PIECE,
    "jacket": LAYER, "coat": LAYER, "blazer": LAYER, "nehru": LAYER,
    "mojari": FOOTWEAR, "boots": FOOTWEAR, "footwear": FOOTWEAR,
    "dupatta": ACCESSORY, "belt": ACCESSORY, "bag": ACCESSORY,
    "watch": ACCESSORY, "earrings": ACCESSORY, "necklace": ACCESSORY,
    "ring": ACCESSORY, "bracelet": ACCESSORY, "head": ACCESSORY,
    "jewelry": ACCESSORY,
    # A saree/lehenga blouse is only ever worn as part of that set.
    "blouse": SET_PART,
    # Worn under a saree, never something to "recommend".
    "petticoat": HIDDEN,
}


def role_for(category):
    return ROLE.get(kind_for(category))


ETHNIC_KINDS = {
    "kurta", "kurta_men", "kurta_women", "sherwani", "dhoti", "salwar",
    "palazzo", "saree", "lehenga", "anarkali", "blouse",
}


# ============================================================
# 3. PAIRING TABLES
# ============================================================

# Which bottoms each top can be worn with.
TOP_BOTTOM_PAIRS = {
    "tshirt": {"jeans", "pant", "shorts", "skirt"},
    "shirt": {"jeans", "pant", "shorts", "skirt"},
    "kurta_men": {"dhoti", "pant", "jeans"},
    "kurta_women": {"salwar", "palazzo", "jeans", "pant"},
    "kurta": {"dhoti", "pant", "jeans", "salwar", "palazzo"},
    "sherwani": {"dhoti", "pant"},
}

# One-pieces that need another garment to be wearable.
SET_NEEDS_BLOUSE = {"saree", "lehenga"}


def is_plain_leggings(item):
    """'Leggings' on their own (western/athleisure), not a salwar or churidar."""
    words = _tokens(item.get("category"))
    return bool(words & {"legging", "leggings"}) and not words & {"salwar", "salwars", "churidar"}


def outfit_style(kinds):
    """'ethnic', 'fusion' (kurta + jeans/pant) or 'western'."""
    kinds = set(kinds)
    ethnic = kinds & ETHNIC_KINDS
    if not ethnic:
        return "western"
    if kinds & {"jeans", "pant"} and not kinds & {"dhoti", "sherwani"}:
        return "fusion"
    return "ethnic"


def layer_allowed(layer_kind, core_kinds):
    """Can this jacket/coat/blazer/nehru go over this outfit?"""
    core = set(core_kinds)
    style = outfit_style(core)

    if core & {"saree", "lehenga", "sherwani", "anarkali"}:
        return False  # these are complete looks on their own

    if layer_kind == "nehru":
        # Over a kurta, or a shirt with trousers/jeans (Indo-western)
        if core & {"kurta", "kurta_men"}:
            return True
        return "shirt" in core and bool(core & {"pant", "jeans"})

    if style != "western":
        return False

    if layer_kind == "blazer":
        return "shorts" not in core

    # jacket / coat - fine over any western outfit
    return True


def footwear_allowed(footwear_kind, core_kinds, weather=None):
    style = outfit_style(core_kinds)
    core = set(core_kinds)

    if footwear_kind == "mojari":
        return style in ("ethnic", "fusion")

    if footwear_kind == "boots":
        if core & {"saree", "lehenga", "dhoti", "sherwani"}:
            return False
        if weather and weather.get("is_hot"):
            return False
        return True

    return True  # generic footwear goes with anything


def accessory_allowed(acc_kind, core_kinds, occasion):
    core = set(core_kinds)
    style = outfit_style(core)

    if acc_kind == "dupatta":
        # Salwar/palazzo suits, lehenga and anarkali. Not a saree
        # (it has its own pallu) and never western wear.
        if core & {"lehenga", "anarkali"}:
            return True
        return bool(core & {"kurta_women", "kurta"}) and bool(
            core & {"salwar", "palazzo"}
        )

    if acc_kind == "belt":
        if style != "western":
            return False
        return bool(core & {"jeans", "pant", "skirt", "shorts", "dress"})

    if acc_kind == "head":
        return style == "ethnic" and occasion in ("wedding", "traditional", "party")

    return True  # bag, watch, jewellery - neutral enough for anything


# Which accessories each occasion leans towards (small ranking nudge).
OCCASION_ACCESSORY_PREFERENCE = {
    "office": {"watch", "bag", "belt"},
    "interview": {"watch", "belt", "bag"},
    "college": {"watch", "bag"},
    "casual": {"watch", "bag"},
    "day_outing": {"bag", "watch"},
    "date": {"earrings", "necklace", "bracelet", "watch"},
    "party": {"earrings", "necklace", "bracelet", "ring", "bag"},
    "wedding": {"earrings", "necklace", "bracelet", "head", "jewelry", "ring"},
    "traditional": {"earrings", "necklace", "bracelet", "jewelry", "head"},
}

MAX_ACCESSORIES = 2


# ============================================================
# 4. COLOUR CHECKS used for hard rejection
# ============================================================

CLASH_SCORE = 8  # color_theory's "colors clash somewhat"


def colors_clash(item_a, item_b):
    a = (item_a.get("color") or "").strip()
    b = (item_b.get("color") or "").strip()
    if not a or not b:
        return False
    score, _ = color_harmony(a, b)
    return score <= CLASH_SCORE


def _color_fit(item, others):
    """Average harmony of `item` against `others` (0-25)."""
    color = (item.get("color") or "").strip()
    scores = []
    for other in others:
        other_color = (other.get("color") or "").strip()
        if color and other_color:
            scores.append(color_harmony(color, other_color)[0])
    return sum(scores) / len(scores) if scores else 12


def _blouse_fit(blouse, piece):
    """
    How well a blouse suits a saree/lehenga. Unlike a shirt and
    trousers, an ethnic set looks richer with a matching or
    contrasting COLOURED blouse than a plain neutral one, so neutral
    blouses score a little lower here (still chosen if nothing else
    fits).
    """
    blouse_color = (blouse.get("color") or "").strip()
    piece_color = (piece.get("color") or "").strip()
    if not blouse_color or not piece_color:
        return 12
    info = classify_color(blouse_color)
    score, reason = color_harmony(blouse_color, piece_color)
    if info["recognized"] and info["neutral"]:
        return 15
    return score + (4 if reason == "monochromatic" else 0)


def too_many_colors(items, limit=3):
    """More than `limit` distinct non-neutral colour families looks busy."""
    families = set()
    for item in items:
        info = classify_color(item.get("color") or "")
        if info["recognized"] and not info["neutral"]:
            families.add(info["family"])
    return len(families) > limit


# ============================================================
# 5. BUILD CANDIDATES
# ============================================================

def classify_items(items):
    """Groups wardrobe items by role, attaching their kind."""
    groups = {TOP: [], BOTTOM: [], ONE_PIECE: [], LAYER: [], FOOTWEAR: [],
              ACCESSORY: [], SET_PART: []}
    for item in items:
        kind = kind_for(item.get("category"))
        role = ROLE.get(kind)
        if role in groups:
            groups[role].append((kind, item))
    return groups


def core_combinations(groups):
    """
    Every wearable base outfit: top + bottom pairs allowed by
    TOP_BOTTOM_PAIRS, and one-pieces (with a matching blouse for a
    saree/lehenga). Colour-clashing top/bottom pairs are rejected.

    Yields dicts: {"type", "core": [(kind, item), ...], "notes": [...]}
    """
    blouses = groups[SET_PART]

    for piece_kind, piece in groups[ONE_PIECE]:
        if piece_kind in SET_NEEDS_BLOUSE:
            if blouses:
                blouse_kind, blouse = max(
                    blouses, key=lambda kb: _blouse_fit(kb[1], piece)
                )
                yield {
                    "type": "set",
                    "core": [(piece_kind, piece), (blouse_kind, blouse)],
                    "notes": [],
                }
            else:
                yield {
                    "type": "one-piece",
                    "core": [(piece_kind, piece)],
                    "notes": [
                        f"No blouse in your wardrobe yet - wear this "
                        f"{piece_kind} with its matching blouse."
                    ],
                }
        else:
            yield {"type": "one-piece", "core": [(piece_kind, piece)], "notes": []}

    for top_kind, top in groups[TOP]:
        allowed = TOP_BOTTOM_PAIRS.get(top_kind, set())
        for bottom_kind, bottom in groups[BOTTOM]:
            # A t-shirt/tank with plain leggings is athleisure; a
            # t-shirt with a salwar is never an outfit.
            athleisure = top_kind == "tshirt" and is_plain_leggings(bottom)
            if bottom_kind not in allowed and not athleisure:
                continue
            if colors_clash(top, bottom):
                continue
            yield {
                "type": "top-bottom",
                "core": [(top_kind, top), (bottom_kind, bottom)],
                "notes": [],
            }


def choose_layer(core, groups, occasion, weather):
    """A jacket/coat/blazer/nehru only when there's a reason to wear one."""
    if weather and weather.get("is_hot"):
        return None

    core_kinds = [kind for kind, _ in core]
    core_items = [item for _, item in core]

    needs_warmth = bool(weather) and any(
        weather.get(flag) for flag in ("is_cold", "is_rainy", "is_windy")
    )

    options = []
    for kind, item in groups[LAYER]:
        if not layer_allowed(kind, core_kinds):
            continue
        if any(colors_clash(item, other) for other in core_items):
            continue

        if needs_warmth:
            reason = "an extra layer for the weather"
        elif kind == "blazer" and occasion in ("office", "interview"):
            reason = f"a blazer sharpens the look for {occasion}"
        elif kind == "nehru" and occasion in ("wedding", "traditional", "party"):
            reason = "a Nehru jacket makes it more festive"
        else:
            continue

        options.append((_color_fit(item, core_items), kind, item, reason))

    if not options:
        return None

    _, kind, item, reason = max(options, key=lambda option: option[0])
    return kind, item, reason


DRESSY_SHOE_WORDS = {"heel", "heels", "stiletto", "pump", "pumps", "wedge", "formal", "oxford"}
SPORTY_SHOE_WORDS = {"sneaker", "sneakers", "sports", "trainer", "trainers", "canvas", "running"}
FORMAL_ETHNIC_KINDS = {"saree", "lehenga", "anarkali", "sherwani", "dhoti"}
CASUAL_SHOE_WORDS = {"sneaker", "sneakers", "sports", "trainer", "trainers",
                     "canvas", "flip", "flat", "flats", "sandal", "sandals"}


def choose_footwear(core_kinds, core_items, groups, weather, occasion=None):
    style = outfit_style(core_kinds)
    options = []
    for kind, item in groups[FOOTWEAR]:
        if not footwear_allowed(kind, core_kinds, weather):
            continue
        words = _tokens(item.get("category"))
        # Sports shoes/sneakers never go with a saree, lehenga,
        # anarkali, sherwani or dhoti.
        if words & SPORTY_SHOE_WORDS and set(core_kinds) & FORMAL_ETHNIC_KINDS:
            continue
        # Same occasion rules as the Shoes tab (item_recommender).
        if occasion:
            from backend.item_recommender import footwear_suits
            if not footwear_suits(item, occasion):
                continue
        score = _color_fit(item, core_items)
        # Tie-break: shoes in the same colour as a main piece look
        # deliberate (black dress + black heels).
        shoe_colour = (item.get("color") or "").strip().lower()
        if shoe_colour and any(shoe_colour == (g.get("color") or "").strip().lower() for g in core_items):
            score += 2
        if occasion in ("party", "date", "wedding", "traditional", "office", "interview") and words & DRESSY_SHOE_WORDS:
            score += 10
        if occasion in ("casual", "college", "day_outing") and words & CASUAL_SHOE_WORDS:
            score += 10
        if occasion in ("casual", "college", "day_outing") and words & DRESSY_SHOE_WORDS:
            score -= 5
        if kind == "mojari" and style == "ethnic":
            score += 10  # the natural choice with ethnic wear
        if kind == "boots" and weather and (
            weather.get("is_cold") or weather.get("is_rainy")
        ):
            score += 8
        options.append((score, kind, item))

    if not options:
        return None
    _, kind, item = max(options, key=lambda option: option[0])
    return kind, item


def _metal(item):
    color = (item.get("color") or "").lower()
    for metal in ("gold", "silver", "rose gold", "copper", "bronze"):
        if metal in color:
            return "gold" if metal in ("gold", "rose gold", "copper", "bronze") else metal
    return None


def choose_accessories(core_kinds, core_items, groups, occasion):
    """Up to MAX_ACCESSORIES that suit the outfit, never two of a kind."""
    preferred = OCCASION_ACCESSORY_PREFERENCE.get(occasion, set())

    options = []
    from backend.item_recommender import accessory_suits
    for kind, item in groups[ACCESSORY]:
        if not accessory_allowed(kind, core_kinds, occasion):
            continue
        if occasion and not accessory_suits(item, occasion):
            continue
        if any(colors_clash(item, other) for other in core_items):
            continue
        score = _color_fit(item, core_items)
        if kind in preferred:
            score += 8
        if kind == "dupatta":
            score += 20  # completes a suit / lehenga
        options.append((score, kind, item))

    options.sort(key=lambda option: option[0], reverse=True)

    chosen = []
    used_kinds = set()
    used_metals = set()
    for _, kind, item in options:
        if kind in used_kinds:
            continue
        metal = _metal(item)
        if metal and used_metals and metal not in used_metals:
            continue  # don't mix gold and silver jewellery
        chosen.append((kind, item))
        used_kinds.add(kind)
        if metal:
            used_metals.add(metal)
        if len(chosen) == MAX_ACCESSORIES:
            break
    return chosen


def item_id(item):
    value = item.get("_id")
    return str(value) if value is not None else None


def outfit_key(core_items):
    """Stable id for an outfit's main garments (ignores accessories)."""
    ids = sorted(filter(None, (item_id(item) for item in core_items)))
    return "|".join(ids)
