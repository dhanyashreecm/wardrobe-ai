"""
Trend recipes: does an outfit (or a wardrobe) recreate a trend?

A recipe is plain data in data/trends.json:

    {"slots": [{"label": "a blazer", "kinds": ["blazer"], "categories": [...]}],
     "palette": {"words": [...], "min": 1},
     "patterned_core": true | "solid_core": true,
     "mode": "ethnic" | "western"}

Each slot must be filled by a DIFFERENT piece of the outfit. "kinds"
are outfit_builder kinds (the same vocabulary every other rule in the
app uses), so legacy category names work too. "categories" narrows a
slot to exact catalogue values (e.g. only "Cardigan" among jackets).
"""
from backend import category_catalog
from backend import outfit_builder as ob

MAIN_ROLES = {ob.TOP, ob.BOTTOM, ob.ONE_PIECE, ob.LAYER}


def kind(item):
    return ob.kind_for(item.get("category"))


def _colour_words(item):
    words = set()
    for value in [item.get("color")] + list(_secondary(item)):
        for part in str(value or "").lower().replace("-", " ").split():
            words.add(part)
    return words


def _secondary(item):
    colours = ((item.get("attributes") or {}).get("colors") or {})
    return colours.get("secondary") or []


def is_patterned(item):
    colours = ((item.get("attributes") or {}).get("colors") or {})
    return bool(colours.get("is_patterned"))


def slot_accepts(slot, item):
    if kind(item) not in set(slot.get("kinds") or []):
        return False
    wanted = slot.get("categories")
    if wanted:
        value = category_catalog.canonical(item.get("category")) or item.get("category")
        return value in wanted
    return True


def _fill_slots(slots, items):
    """Backtracking: every slot gets a different item. Returns items or None."""
    chosen = []

    def place(index, used):
        if index == len(slots):
            return True
        for item in items:
            key = id(item)
            if key in used or not slot_accepts(slots[index], item):
                continue
            chosen.append(item)
            if place(index + 1, used | {key}):
                return True
            chosen.pop()
        return False

    return list(chosen) if place(0, frozenset()) else None


def _palette_ok(recipe, core_items):
    palette = recipe.get("palette")
    if not palette:
        return True
    words = set(palette.get("words") or [])
    hits = sum(1 for item in core_items if _colour_words(item) & words)
    return hits >= int(palette.get("min", 1))


def core_items_of(outfit):
    roles = outfit.get("roles") or {}
    core = [item for item in outfit.get("items", [])
            if roles.get(str(item.get("_id"))) in MAIN_ROLES]
    return core or list(outfit.get("items", []))


def outfit_matches(recipe, outfit):
    """(True, pieces used) if this generated outfit recreates the trend."""
    slots = recipe.get("slots") or []
    if not slots:
        return False, []
    items = list(outfit.get("items", []))
    core = core_items_of(outfit)
    if recipe.get("mode") and outfit.get("style") != recipe["mode"]:
        return False, []
    if recipe.get("patterned_core") and not any(is_patterned(i) for i in core):
        return False, []
    if recipe.get("solid_core") and any(is_patterned(i) for i in core):
        return False, []
    if not _palette_ok(recipe, core):
        return False, []
    pieces = _fill_slots(slots, items)
    return (pieces is not None), (pieces or [])


def missing_slots(recipe, wardrobe_items):
    """Slots nothing in the wardrobe could ever fill (gender-filtered items)."""
    return [slot for slot in (recipe.get("slots") or [])
            if not any(slot_accepts(slot, item) for item in wardrobe_items)]


def pieces_for(recipe, wardrobe_items):
    """Wardrobe pieces that could fill at least one slot (for 'you own N pieces')."""
    slots = recipe.get("slots") or []
    return [item for item in wardrobe_items if any(slot_accepts(s, item) for s in slots)]
