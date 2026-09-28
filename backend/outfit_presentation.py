"""
Everything the UI needs to PRESENT outfits and wardrobe items, built
only from real data:

  * display_name(item)        "Black Bootcut Jeans", "Pink Saree"
  * item_group(item)          which wardrobe tab it belongs to
                              (Tops, Bottoms, Dresses, Sarees, Ethnic,
                              Outerwear, Shoes, Accessories)
  * style_tags(outfit)        Casual / Smart / Formal / Ethnic / Party
  * outfit_title(outfit)      "Party Night Look", "Campus Classic"...
  * validate_outfit(...)      the FINAL check every outfit must pass
                              before it is sent to the browser
  * matches_colour / matches_style - the page's Colour/Style filters
"""
from backend import outfit_builder as ob
from backend.category_gender import is_allowed_for_account, item_allowed_for_account
from backend.color_theory import classify_color
from backend.style_compatibility import resolve_style


# ------------------------------------------------------------
# Items
# ------------------------------------------------------------

_PRETTY = {
    "Denims": "Jeans", "Pant": "Trousers", "Kurta (Men)": "Kurta",
    "Kurta (Women)": "Kurta", "Mojaris (Men)": "Mojaris",
    "Mojaris (Women)": "Mojaris", "Leggings & Salwars": "Leggings",
    "Footwear": "Shoes",
}


def display_name(item):
    colour = (item.get("color") or "").strip().title()
    category = item.get("category") or "Item"
    name = _PRETTY.get(category, category)
    return f"{colour} {name}".strip()


GROUP_BY_KIND = {
    "tshirt": "Tops", "shirt": "Tops",
    "jeans": "Bottoms", "pant": "Bottoms", "shorts": "Bottoms",
    "skirt": "Bottoms",
    "dress": "Dresses", "gown": "Dresses",
    "saree": "Sarees",
    "lehenga": "Ethnic", "anarkali": "Ethnic", "kurta": "Ethnic",
    "kurta_men": "Ethnic", "kurta_women": "Ethnic", "sherwani": "Ethnic",
    "dhoti": "Ethnic", "salwar": "Ethnic", "palazzo": "Ethnic",
    "pajama": "Ethnic", "ethnic_set": "Ethnic", "leggings": "Bottoms",
    "blouse": "Ethnic", "petticoat": "Ethnic", "dupatta": "Ethnic",
    "jacket": "Outerwear", "coat": "Outerwear", "blazer": "Outerwear",
    "nehru": "Outerwear",
    "mojari": "Shoes", "boots": "Shoes", "footwear": "Shoes",
}


def item_group(item):
    kind = ob.kind_for(item.get("category"))
    if kind in GROUP_BY_KIND:
        return GROUP_BY_KIND[kind]
    if ob.ROLE.get(kind) == ob.ACCESSORY:
        return "Accessories"
    return "Other"


def item_style_label(item):
    style = resolve_style(item.get("category"), item.get("styling"))
    return {
        "casual": "Casual", "smart_casual": "Smart", "formal": "Formal",
        "traditional": "Traditional", "festive": "Festive",
    }.get(style, "Smart")


def present_item(item):
    """Adds display fields; never changes the stored item."""
    enriched = dict(item)
    enriched["display_name"] = display_name(item)
    enriched["group"] = item_group(item)
    enriched["style_label"] = item_style_label(item)
    return enriched


# ------------------------------------------------------------
# Outfits
# ------------------------------------------------------------

_TITLES = {
    "casual": ["Easy Weekend Look", "Laid-back Classic", "Everyday Ease"],
    "day_outing": ["Day Out Look", "Sunny Stroll", "Brunch Ready"],
    "college": ["Campus Classic", "Lecture to Lunch", "Campus Cool"],
    "office": ["Office Polish", "Workday Sharp", "Desk to Dinner"],
    "interview": ["Interview Ready", "First Impression", "Quiet Confidence"],
    "date": ["Date Night Vibes", "Dinner Date", "Evening Charm"],
    "party": ["Party Night Look", "Chic & Classy", "After Dark"],
    "wedding": ["Wedding Guest Look", "Festive Glow", "Celebration Ready"],
    "traditional": ["Traditional Grace", "Festive Edit", "Classic Ethnic"],
    "sports": ["Workout Ready", "Active Day", "Gym Session"],
}

OCCASION_LABELS = {
    "casual": "Casual", "day_outing": "Day Outing", "college": "College",
    "office": "Office", "interview": "Interview", "date": "Date Night",
    "party": "Party", "wedding": "Wedding", "traditional": "Traditional",
    "sports": "Sports / Workout",
}


def occasion_label(occasion):
    return OCCASION_LABELS.get(occasion, (occasion or "").replace("_", " ").title())


def outfit_title(outfit, taken=()):
    options = _TITLES.get(outfit.get("occasion"), ["Your Look"])
    key = outfit.get("outfit_key") or ""
    start = sum(map(ord, key)) % len(options)
    for step in range(len(options)):
        title = options[(start + step) % len(options)]
        if title not in taken:
            return title
    # All used: name it after its main colour instead of repeating.
    colour = (outfit["items"][0].get("color") or "").title()
    return f"{colour} {options[start]}".strip()


def style_tags(outfit):
    tags = set()
    styles = set()
    for item in outfit["items"]:
        role = outfit.get("roles", {}).get(str(item.get("_id")))
        if role in (ob.ACCESSORY, ob.FOOTWEAR):
            continue
        styles.add(resolve_style(item.get("category"), item.get("styling")))
    if outfit.get("style") == "ethnic":
        tags.add("Ethnic")
    if "casual" in styles:
        tags.add("Casual")
    if "smart_casual" in styles:
        tags.add("Smart")
    if "formal" in styles or outfit.get("occasion") in ("office", "interview"):
        tags.add("Formal")
    if "festive" in styles or outfit.get("occasion") in ("party", "date"):
        tags.add("Party")
    return sorted(tags)


def colour_families(outfit):
    families = []
    for item in outfit["items"]:
        info = classify_color(item.get("color") or "")
        word = (item.get("color") or "").strip().lower()
        families.append(word if info.get("neutral") else info.get("family") or word)
    return families


def matches_colour(outfit, colour):
    if not colour:
        return True
    colour = colour.strip().lower()
    wanted = classify_color(colour)
    for item in outfit["items"]:
        word = (item.get("color") or "").strip().lower()
        if colour in word:
            return True
        info = classify_color(word)
        if (wanted.get("recognized") and not wanted.get("neutral")
                and info.get("family") == wanted.get("family")):
            return True
    return False


def matches_style(outfit, style):
    if not style:
        return True
    return style.strip().title() in style_tags(outfit)


def validate_outfit(outfit, wardrobe_by_id, account_gender, occasion):
    """
    The FINAL check before an outfit reaches the user. Returns
    (ok, reason). Anything that fails is dropped, never "fixed up".
    """
    ids = [str(item.get("_id")) for item in outfit.get("items", [])]
    if not ids or any(not value or value == "None" for value in ids):
        return False, "item without an id"
    if len(ids) != len(set(ids)):
        return False, "same item used twice"

    for item_id in ids:
        stored = wardrobe_by_id.get(item_id)
        if stored is None:
            return False, "item is not in this user's wardrobe (deleted?)"
        if not stored.get("image_path"):
            return False, "item has no image"
        if not item_allowed_for_account(stored, account_gender):
            return False, "item is for the other gender"

    roles = outfit.get("roles", {})
    main_roles = [roles.get(item_id) for item_id in ids]
    if main_roles.count(ob.TOP) > 1 or main_roles.count(ob.BOTTOM) > 1:
        return False, "two tops or two bottoms"
    if ob.ONE_PIECE in main_roles and (ob.TOP in main_roles or ob.BOTTOM in main_roles):
        return False, "one-piece mixed with separates"
    if ob.ONE_PIECE not in main_roles and not (
        ob.TOP in main_roles and ob.BOTTOM in main_roles
    ):
        return False, "incomplete outfit"

    if outfit.get("occasion") != occasion:
        return False, "wrong occasion"

    # ---- traditional / western are separate modes ----
    mode = ob.occasion_mode(occasion)
    kinds = {item_id: ob.kind_for(wardrobe_by_id[item_id].get("category")) for item_id in ids}
    garment_modes = {ob.garment_mode(kind) for kind in kinds.values()} - {None}
    if len(garment_modes) > 1:
        return False, "mixes traditional and western pieces"
    if garment_modes and garment_modes != {mode}:
        return False, f"{garment_modes.pop()} outfit for a {mode} occasion"
    for item_id, kind in kinds.items():
        role = ob.ROLE.get(kind)
        words = ob._tokens(wardrobe_by_id[item_id].get("category"))
        if role in (ob.SET_PART, ob.HIDDEN):
            return False, "blouse/petticoat shown as a separate piece"
        if role == ob.FOOTWEAR:
            if mode == "traditional" and (kind == "boots" or words & ob.SPORTY_SHOE_WORDS):
                return False, "sneakers/boots with traditional wear"
            if mode == "western" and kind == "mojari":
                return False, "mojaris with western wear"
            if (mode == "traditional" and words & {"formal", "oxford", "oxfords"}
                    and ob.womens_ethnic([wardrobe_by_id[i] for i in ids])):
                return False, "office shoes with a saree/lehenga/suit"
        if role == ob.ACCESSORY:
            if mode == "western" and kind in ("dupatta", "head"):
                return False, "traditional accessory with western wear"
            if mode == "traditional" and kind == "belt":
                return False, "belt with traditional wear"

    top = [kinds[i] for i in ids if roles.get(i) == ob.TOP]
    bottom = [kinds[i] for i in ids if roles.get(i) == ob.BOTTOM]
    if top and bottom and bottom[0] not in ob.TOP_BOTTOM_PAIRS.get(top[0], set()):
        return False, f"{top[0]} doesn't go with {bottom[0]}"

    accessories = sum(1 for i in ids if roles.get(i) == ob.ACCESSORY)
    limit = ob.MAX_TRADITIONAL_ACCESSORIES if mode == "traditional" else ob.MAX_ACCESSORIES
    if accessories > limit:
        return False, "too many accessories"

    return True, "ok"
