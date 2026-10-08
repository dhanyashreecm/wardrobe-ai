"""
Aesthetic + memorable names for generated outfits.

The aesthetic is DERIVED from the actual pieces (their kinds, colours,
style and occasion) - never picked at random - and the name follows
from it, so "Midnight Edit" is always a dark outfit and "Modern
Heritage" always an ethnic one.
"""
from backend.color_theory import classify_color
from backend.style_studio import recipes

DARK = {"black", "charcoal", "navy", "wine", "burgundy", "maroon", "plum", "forest", "chocolate"}
PASTEL = {"lavender", "lilac", "sage", "mint", "blush", "peach", "sky", "mauve", "ivory", "cream", "powder"}
WARM_GLOW = {"yellow", "mustard", "gold", "amber", "orange", "rust", "terracotta", "coral", "camel", "tan"}
ROSE = {"pink", "rose", "blush", "magenta", "fuchsia", "salmon", "red", "coral"}
JEWEL = {"emerald", "green", "wine", "burgundy", "maroon", "teal", "royal", "cobalt", "purple", "magenta", "red", "gold"}
DENIM_KINDS = {"jeans"}
TAILORED_KINDS = {"blazer", "coat"}

# aesthetic -> (label, [names]) ; first unused name is taken
AESTHETICS = {
    "festive_grace": ("Festive Grace", ["Festive Grace", "Golden Celebration", "Royal Evening"]),
    "modern_heritage": ("Modern Heritage", ["Modern Heritage", "Heritage Edit", "Contemporary Classic"]),
    "soft_heritage": ("Soft Heritage", ["Soft Heritage", "Morning Mehendi", "Pastel Poise"]),
    "midnight": ("Midnight Edit", ["Midnight Edit", "After Dark", "Noir Hour"]),
    "quiet_luxury": ("Quiet Luxury", ["Quiet Luxury", "Soft Power", "Polished Neutral"]),
    "modern_minimal": ("Modern Minimal", ["Modern Minimal", "Clean Lines", "Effortless Neutral"]),
    "city_rose": ("City Rose", ["City Rose", "Rose Hour", "Blush Edit"]),
    "golden_hour": ("Golden Hour", ["Golden Hour", "Warm Sunset", "Amber Days"]),
    "contemporary_muse": ("Contemporary Muse", ["Contemporary Muse", "One & Done", "Dress Story"]),
    "urban_classic": ("Urban Classic", ["Urban Classic", "Denim Diaries", "City Casual"]),
    "colour_pop": ("Colour Pop", ["Colour Pop", "Bold Move", "Bright Side"]),
    "weekend_ease": ("Weekend Ease", ["Weekend Ease", "Easy Sunday", "Off-Duty Cool"]),
    "sport_luxe": ("Sport Luxe", ["Sport Luxe", "Game Day", "Active Edge"]),
}


def _words(item):
    return {w for w in str(item.get("color") or "").lower().replace("-", " ").split()}


def _all_neutral(items):
    return all(classify_color(i.get("color")).get("neutral") for i in items if i.get("color"))


def aesthetic_for(outfit):
    core = recipes.core_items_of(outfit)
    kinds = {recipes.kind(i) for i in core}
    words = set().union(*[_words(i) for i in core]) if core else set()
    occasion = outfit.get("occasion")
    sporty = any(w in str(i.get("category") or "").lower() for i in core
                 for w in ("sport", "jersey", "track", "jogger", "athletic"))

    if outfit.get("style") == "ethnic":
        if occasion in ("wedding",) or words & JEWEL:
            return "festive_grace"
        if words & PASTEL:
            return "soft_heritage"
        return "modern_heritage"
    if sporty:
        return "sport_luxe"
    if len(words & DARK) >= 2 or (words and words <= (DARK | {"grey", "gray"}) and words & DARK):
        return "midnight"
    if kinds & TAILORED_KINDS and _all_neutral(core):
        return "quiet_luxury"
    if kinds & {"dress", "gown"}:
        return "contemporary_muse"
    if words & ROSE:
        return "city_rose"
    if words & WARM_GLOW:
        return "golden_hour"
    if _all_neutral(core):
        return "modern_minimal"
    if kinds & DENIM_KINDS:
        return "urban_classic"
    if not _all_neutral(core):
        return "colour_pop"
    return "weekend_ease"


def label_for(aesthetic):
    return AESTHETICS.get(aesthetic, AESTHETICS["weekend_ease"])[0]


def name_for(aesthetic, taken):
    _, names = AESTHETICS.get(aesthetic, AESTHETICS["weekend_ease"])
    for name in names:
        if name not in taken:
            return name
    base = names[0]
    n = 2
    while f"{base} {n}" in taken:
        n += 1
    return f"{base} {n}"


STYLE_CHOICES = [(key, label) for key, (label, _) in AESTHETICS.items()]
