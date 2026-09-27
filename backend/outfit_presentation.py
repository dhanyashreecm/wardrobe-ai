"""
Everything the UI needs to PRESENT outfits and wardrobe items, built
only from real data:

  * display_name(item)        "Black Bootcut Jeans", "Pink Saree"
  * item_group(item)          which wardrobe tab it belongs to
                              (Tops, Bottoms, Dresses, Sarees, Ethnic,
                              Outerwear, Shoes, Accessories)
  * style_tags(outfit)        Casual / Smart / Formal / Ethnic / Party
  * outfit_title(outfit)      "Party Night Look", "Campus Classic"...
  * inspiration(outfit)       a Pinterest SEARCH LINK for the look
                              (no scraping, no copied images - the user
                              opens Pinterest themselves; if Pinterest is
                              unreachable nothing else is affected)
  * validate_outfit(...)      the FINAL check every outfit must pass
                              before it is sent to the browser
  * matches_colour / matches_style - the page's Colour/Style filters
"""
from urllib.parse import quote_plus

from backend import outfit_builder as ob
from backend.category_gender import is_allowed_for_account
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
    "blouse": "Ethnic", "petticoat": "Ethnic", "dupatta": "Ethnic",
    "jacket": "Outerwear", "coat": "Outerwear", "blazer": "Outerwear",
    "nehru": "Outerwear",
    "mojari": "Shoes", "boots": "Shoes", "footwear": "Shoes",
}


def item_group(item):
    kind = ob.kind_for(item.get("category"))
    if ob.is_plain_leggings(item):
        return "Bottoms"
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
    if outfit.get("style") in ("ethnic", "fusion"):
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


_INSPO_WORDS = {
    "casual": "casual outfit", "day_outing": "day out outfit",
    "college": "college outfit", "office": "office outfit",
    "interview": "interview outfit", "date": "date night outfit",
    "party": "party outfit", "wedding": "wedding guest outfit",
    "traditional": "traditional ethnic outfit",
    "sports": "gym workout outfit",
}


def inspiration(outfit, gender=None):
    """A Pinterest search built from the outfit's own colours/pieces."""
    main = [
        item for item in outfit["items"]
        if outfit.get("roles", {}).get(str(item.get("_id")))
        in (ob.TOP, ob.BOTTOM, ob.ONE_PIECE)
    ]
    words = " ".join(display_name(item).lower() for item in main[:2])
    who = {"male": "men", "female": "women"}.get((gender or "").lower(), "")
    query = f"{words} {_INSPO_WORDS.get(outfit.get('occasion'), 'outfit')} {who}".strip()
    return {
        "title": f"Inspo: {words}" if words else "Outfit inspiration",
        "query": query,
        "pinterest_url": "https://www.pinterest.com/search/pins/?q=" + quote_plus(query),
    }


def occasion_inspiration(occasion, gender=None):
    who = {"male": "men", "female": "women"}.get((gender or "").lower(), "")
    base = _INSPO_WORDS.get(occasion, "outfit")
    ideas = {
        "party": ["black satin party look", "sequin top party outfit", "little black dress styling"],
        "wedding": ["pastel lehenga wedding guest", "silk saree wedding look", "festive jewellery styling"],
        "traditional": ["cotton kurta set", "handloom saree styling", "ethnic everyday look"],
        "date": ["date night dress", "minimal date outfit", "evening top and jeans"],
        "college": ["college outfit ideas", "jeans and top campus look", "comfy kurti with jeans"],
        "casual": ["weekend casual outfit", "white tee and jeans", "easy summer look"],
        "day_outing": ["brunch outfit", "sundress day out", "sightseeing outfit"],
        "office": ["office wear ideas", "shirt and trousers workwear", "kurta office look"],
        "interview": ["interview outfit", "formal shirt trousers", "minimal professional look"],
        "sports": ["gym outfit ideas", "athleisure look", "running outfit"],
    }.get(occasion, [base])
    return [
        {
            "title": idea.title(),
            "pinterest_url": "https://www.pinterest.com/search/pins/?q="
            + quote_plus(f"{idea} {who}".strip()),
        }
        for idea in ideas
    ]


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
        if not is_allowed_for_account(stored.get("category"), account_gender):
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
    if occasion == "traditional" and outfit.get("style") != "ethnic":
        return False, "western piece in a traditional outfit"

    return True, "ok"
