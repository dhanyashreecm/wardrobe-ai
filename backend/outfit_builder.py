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
  * western and traditional pieces were mixed (saree + crop top,
    kurta + jeans, lehenga + sneakers)
  * accessories were handed out in rotation (outfit 1 got accessory 1,
    outfit 2 got accessory 2...), so a Dupatta could land on a shirt
    and jeans, or Mojaris on a western outfit
  * only the first 8 tops / 8 bottoms were ever looked at

TWO SEPARATE MODES (see outfit_style / MODE rules below):
  * Western     top + bottom (or dress) + footwear + accessories
  * Traditional a COMPLETE ethnic outfit - saree, lehenga, anarkali,
                salwar/kurta set, kurta + pajama/dhoti, sherwani -
                + traditional footwear + traditional accessories.
                A saree/lehenga is complete on its own: its blouse is
                part of the set and never has to be "matched".
A garment from one mode is never combined with the other.

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
                "tank", "sweatshirt", "hoodie", "sweater", "polo", "jersey",
                "camisole", "cami", "tunic"}),
    ("shirt", {"shirt", "shirts"}),
    ("blouse", {"blouse", "blouses", "choli"}),
    ("sherwani", {"sherwani", "sherwanis"}),
    ("kurta", {"kurta", "kurtas", "kurti", "kurtis"}),
    ("nehru", {"nehru"}),
    ("blazer", {"blazer", "blazers", "suit"}),
    ("coat", {"coat", "coats", "overcoat"}),
    ("jacket", {"jacket", "jackets", "cardigan", "shrug"}),
    # jackets are checked before jeans so "Denim Jacket" is a jacket
    ("jeans", {"jean", "jeans", "denim", "denims"}),
    ("pajama", {"pajama", "pajamas", "pyjama", "pyjamas"}),
    ("pant", {"pant", "pants", "trouser", "trousers", "chino", "chinos",
              "jogger", "joggers", "trackpants", "sweatpants"}),
    ("shorts", {"short", "shorts"}),
    ("skirt", {"skirt", "skirts"}),
    ("salwar", {"legging", "leggings", "salwar", "salwars", "churidar"}),
    ("palazzo", {"palazzo", "palazzos", "sharara", "shararas", "gharara"}),
    ("saree", {"saree", "sarees", "sari"}),
    ("lehenga", {"lehenga", "lehengas"}),
    ("anarkali", {"anarkali", "anarkalis"}),
    ("gown", {"gown", "gowns"}),
    ("dress", {"dress", "dresses", "frock", "frocks", "jumpsuit", "romper", "rompers"}),
    ("mojari", {"mojari", "mojaris", "jutti", "juttis", "kolhapuri"}),
    ("boots", {"boot", "boots"}),
    ("footwear", {"footwear", "shoe", "shoes", "sneaker", "sneakers",
                  "heel", "heels", "sandal", "sandals", "flats", "loafers",
                  "loafer", "slides", "slipper", "slippers", "flip", "flops"}),
    ("dupatta", {"dupatta", "dupattas", "stole"}),
    ("belt", {"belt", "belts"}),
    ("tie", {"tie", "ties", "bowtie"}),
    ("cap", {"cap", "caps", "hat", "hats"}),
    ("sunglasses", {"sunglass", "sunglasses", "shades"}),
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


# A complete ethnic set stored as one item ("Salwar Suit", "Kurta Set",
# "Anarkali Set", "Sharara Set").
_SET_WORDS = {"set", "sets", "suit", "suits"}
_SET_ETHNIC_WORDS = {"salwar", "kurta", "kurti", "churidar", "sharara",
                     "palazzo", "ethnic", "anarkali", "patiala"}


def kind_for(category):
    """The specific garment kind, or None if unrecognised."""
    tokens = _tokens(category)
    if not tokens:
        return None

    if tokens & _SET_WORDS and tokens & _SET_ETHNIC_WORDS:
        return "ethnic_set"
    # Plain leggings are their own kind: worn with a kurti (traditional)
    # or a t-shirt (athleisure). "Leggings & Salwars" stays a salwar.
    if tokens & {"legging", "leggings"} and not tokens & {"salwar", "salwars", "churidar"}:
        return "leggings"

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
    "pajama": BOTTOM, "leggings": BOTTOM,
    "dress": ONE_PIECE, "gown": ONE_PIECE, "saree": ONE_PIECE,
    "lehenga": ONE_PIECE, "anarkali": ONE_PIECE, "ethnic_set": ONE_PIECE,
    "jacket": LAYER, "coat": LAYER, "blazer": LAYER, "nehru": LAYER,
    "mojari": FOOTWEAR, "boots": FOOTWEAR, "footwear": FOOTWEAR,
    "dupatta": ACCESSORY, "belt": ACCESSORY, "bag": ACCESSORY,
    "watch": ACCESSORY, "earrings": ACCESSORY, "necklace": ACCESSORY,
    "ring": ACCESSORY, "bracelet": ACCESSORY, "head": ACCESSORY,
    "jewelry": ACCESSORY, "tie": ACCESSORY, "cap": ACCESSORY,
    "sunglasses": ACCESSORY,
    # A saree/lehenga blouse is part of that set: never recommended on
    # its own and never required to complete the saree/lehenga.
    "blouse": SET_PART,
    # Worn under a saree, never something to "recommend".
    "petticoat": HIDDEN,
}


def role_for(category):
    return ROLE.get(kind_for(category))


ETHNIC_KINDS = {
    "kurta", "kurta_men", "kurta_women", "sherwani", "dhoti", "salwar",
    "palazzo", "pajama", "saree", "lehenga", "anarkali", "ethnic_set",
    "blouse", "nehru",
}

WESTERN_KINDS = {
    "tshirt", "shirt", "jeans", "pant", "shorts", "skirt", "dress", "gown",
    "jacket", "coat", "blazer",
}

# Worn in either mode (the rest of the outfit decides).
NEUTRAL_KINDS = {"leggings"}

# Occasions of each mode. Everything not traditional is western.
TRADITIONAL_OCCASIONS = {"wedding", "traditional"}


def occasion_mode(occasion):
    return "traditional" if occasion in TRADITIONAL_OCCASIONS else "western"


def garment_mode(kind):
    """'traditional', 'western' or None (either / not a garment)."""
    if kind in ETHNIC_KINDS:
        return "traditional"
    if kind in WESTERN_KINDS:
        return "western"
    return None


# ============================================================
# 3. PAIRING TABLES
# ============================================================

# Which bottoms each top can be worn with.
# Western tops only with western bottoms, ethnic tops only with ethnic
# bottoms - no kurta + jeans, no crop top + salwar.
TOP_BOTTOM_PAIRS = {
    "tshirt": {"jeans", "pant", "shorts", "skirt", "leggings"},
    "shirt": {"jeans", "pant", "shorts", "skirt"},
    "kurta_men": {"dhoti", "pajama", "salwar"},
    "kurta_women": {"salwar", "palazzo", "pajama", "leggings"},
    "kurta": {"dhoti", "pajama", "salwar", "palazzo", "leggings"},
    "sherwani": {"dhoti", "pajama", "salwar"},
}


def is_plain_leggings(item):
    """'Leggings' on their own, not a salwar or churidar."""
    return kind_for(item.get("category")) == "leggings"


SPORTY_WORDS = {"sports", "sport", "jersey", "athletic", "track", "trackpants",
                "jogger", "joggers", "gym", "sweatpants", "tracksuit"}


def is_sporty(item):
    """Activewear (Sports Jersey, Track Pants, Joggers...)."""
    return bool(_tokens(item.get("category")) & SPORTY_WORDS)


def sporty_pair_ok(top_kind, top, bottom_kind, bottom):
    """
    Activewear only pairs with casual pieces: a jersey with jeans,
    shorts or track pants - never chinos or formal trousers; track
    pants with a t-shirt - never a shirt.
    """
    if is_sporty(top) and not (bottom_kind in ("jeans", "shorts") or is_sporty(bottom)):
        return False
    if is_sporty(bottom) and not (top_kind == "tshirt"):
        return False
    return True


def womens_ethnic(items):
    """True for a women's traditional outfit (saree, lehenga, suit...)."""
    from backend.category_gender import category_gender, FEMALE
    return any(kind_for(i.get("category")) in ETHNIC_KINDS and category_gender(i.get("category")) == FEMALE
               for i in items)


def outfit_style(kinds):
    """'ethnic', 'western' or 'mixed' (never allowed - see validator)."""
    kinds = set(kinds)
    ethnic = kinds & ETHNIC_KINDS
    western = kinds & WESTERN_KINDS
    if ethnic and western:
        return "mixed"
    return "ethnic" if ethnic else "western"


def layer_allowed(layer_kind, core_kinds):
    """Can this jacket/coat/blazer/nehru go over this outfit?"""
    core = set(core_kinds)
    style = outfit_style(core)

    if core & {"saree", "lehenga", "sherwani", "anarkali", "ethnic_set"}:
        return False  # these are complete looks on their own

    if layer_kind == "nehru":
        # Only over a men's kurta - never over western clothes.
        return bool(core & {"kurta", "kurta_men"})

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
        return style == "ethnic"

    if footwear_kind == "boots":
        if style == "ethnic":
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
        if core & {"lehenga", "anarkali", "ethnic_set"}:
            return True
        return bool(core & {"kurta_women", "kurta"}) and bool(
            core & {"salwar", "palazzo"}
        )

    if acc_kind == "belt":
        if style != "western" or occasion == "sports":
            return False
        return bool(core & {"jeans", "pant", "skirt", "dress"})

    if acc_kind == "head":
        return style == "ethnic"

    # Western-only accessories, each for the occasions it suits.
    if acc_kind == "tie":
        return style == "western" and occasion in ("office", "interview", "date", "party")
    if acc_kind == "cap":
        return style == "western" and occasion in ("casual", "day_outing", "college", "sports")
    if acc_kind == "sunglasses":
        return style == "western" and occasion not in ("office", "interview")

    return True  # bag, watch, jewellery - neutral enough for anything


# Which accessories each occasion leans towards (small ranking nudge).
OCCASION_ACCESSORY_PREFERENCE = {
    "office": {"watch", "bag", "belt", "tie"},
    "interview": {"watch", "belt", "bag", "tie"},
    "college": {"watch", "bag"},
    "casual": {"watch", "bag"},
    "day_outing": {"bag", "watch"},
    "date": {"earrings", "necklace", "bracelet", "watch"},
    "party": {"earrings", "necklace", "bracelet", "ring", "bag"},
    "wedding": {"earrings", "necklace", "bracelet", "head", "jewelry", "ring", "bag"},
    "traditional": {"earrings", "necklace", "bracelet", "jewelry", "head", "bag"},
}

MAX_ACCESSORIES = 2              # western: keep it simple
MAX_TRADITIONAL_ACCESSORIES = 3  # jewellery, bangles, clutch, maang tikka...


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
    TOP_BOTTOM_PAIRS, and complete one-pieces. A saree, lehenga,
    anarkali or ethnic set is a COMPLETE outfit by itself (its blouse
    or dupatta belongs to it) - no blouse matching is required.
    Colour-clashing top/bottom pairs are rejected.

    Yields dicts: {"type", "core": [(kind, item), ...], "notes": [...]}
    """
    for piece_kind, piece in groups[ONE_PIECE]:
        yield {"type": "one-piece", "core": [(piece_kind, piece)], "notes": []}

    for top_kind, top in groups[TOP]:
        allowed = TOP_BOTTOM_PAIRS.get(top_kind, set())
        for bottom_kind, bottom in groups[BOTTOM]:
            if bottom_kind not in allowed:
                continue
            if not sporty_pair_ok(top_kind, top, bottom_kind, bottom):
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
        elif kind == "nehru" and occasion in TRADITIONAL_OCCASIONS:
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
FORMAL_ETHNIC_KINDS = {"saree", "lehenga", "anarkali", "sherwani", "dhoti", "ethnic_set"}
CASUAL_SHOE_WORDS = {"sneaker", "sneakers", "sports", "trainer", "trainers",
                     "canvas", "flip", "flat", "flats", "sandal", "sandals"}


def choose_footwear(core_kinds, core_items, groups, weather, occasion=None):
    style = outfit_style(core_kinds)
    options = []
    for kind, item in groups[FOOTWEAR]:
        if not footwear_allowed(kind, core_kinds, weather):
            continue
        words = _tokens(item.get("category"))
        # Sports shoes/sneakers never go with traditional wear, and
        # office-style formal shoes never with a saree/lehenga/suit.
        if words & SPORTY_SHOE_WORDS and style == "ethnic":
            continue
        if style == "ethnic" and words & {"formal", "oxford", "oxfords"} and womens_ethnic(core_items):
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
        if occasion in ("party", "date", "office", "interview") and words & DRESSY_SHOE_WORDS:
            score += 10
        if style == "ethnic" and words & DRESSY_SHOE_WORDS:
            score += 4  # heels/formal shoes are fine with ethnic wear, mojaris better
        if occasion in ("casual", "college", "day_outing") and words & CASUAL_SHOE_WORDS:
            score += 10
        if occasion in ("casual", "college", "day_outing") and words & DRESSY_SHOE_WORDS:
            score -= 5
        if kind == "mojari" and style == "ethnic":
            score += 12  # the natural choice with ethnic wear
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
    """
    A few accessories that suit the outfit, never two of a kind:
    up to 2 for western looks, up to 3 traditional pieces (jewellery,
    bangles, clutch, maang tikka, dupatta) for traditional looks.
    """
    preferred = OCCASION_ACCESSORY_PREFERENCE.get(occasion, set())
    limit = MAX_TRADITIONAL_ACCESSORIES if outfit_style(core_kinds) == "ethnic" else MAX_ACCESSORIES

    options = []
    from backend.item_recommender import accessory_suits
    for kind, item in groups[ACCESSORY]:
        if not accessory_allowed(kind, core_kinds, occasion):
            continue
        if occasion and not accessory_suits(item, occasion):
            continue
        if kind == "belt" and any(is_sporty(piece) for piece in core_items):
            continue  # no belt on track pants or a jersey look
        if any(colors_clash(item, other) for other in core_items):
            continue
        score = _color_fit(item, core_items)
        if kind in preferred:
            score += 8
        if kind == "dupatta":
            score += 20  # completes a suit / lehenga
        if limit == MAX_TRADITIONAL_ACCESSORIES:
            # traditional styling: a clutch/potli over a daily handbag,
            # jewellery over a watch
            words = _tokens(item.get("category"))
            if kind == "bag":
                score += 6 if words & {"clutch", "potli"} else -3
            if kind == "watch":
                score -= 6
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
        if len(chosen) == limit:
            break
    return chosen


def item_id(item):
    value = item.get("_id")
    return str(value) if value is not None else None


def outfit_key(core_items):
    """Stable id for an outfit's main garments (ignores accessories)."""
    ids = sorted(filter(None, (item_id(item) for item in core_items)))
    return "|".join(ids)
