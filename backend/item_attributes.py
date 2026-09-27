"""
WHAT WE CAN HONESTLY SAY ABOUT A GARMENT WE JUST SAW.

When an item is uploaded, this builds the structured description the
recommendation engine wants: role, style, season and weather
suitability, layering, colour. It is deliberately conservative - the
governing rule is the one in the brief: "do not confidently invent
information that cannot be visually determined."

WHAT IS DERIVED, AND FROM WHAT

  category, role, layering  from garment_taxonomy - the category is
                            either the user's own choice or a model
                            prediction they accepted, so this is
                            solid ground.
  style, occasions          from occasion_model, whose profiles come
                            from 44,446 labelled catalogue items, and
                            from the app's existing occasion affinity.
  primary/secondary colour, from color_detection's pixel analysis of
  pattern                   the actual photo.
  season, weather           inferred from the garment TYPE, not from
                            the image: a coat is warm because coats
                            are warm, which is a statement about the
                            category rather than a claim about this
                            particular photo.

WHAT IS DELIBERATELY NOT DERIVED

  material/fabric   Cotton, linen and a cotton-linen blend are not
                    separable from a 224x224 photo, and getting it
                    wrong would feed bad advice into the weather
                    scoring (which does read material when the user
                    supplies it). Left as whatever the user typed,
                    or absent.
  subcategory       "A-line skirt" vs "pencil skirt", "bootcut" vs
                    "straight" - no dataset available to this project
                    has those labels, so no model here can produce
                    them. Absent rather than guessed.
  brand, size, fit  Not visually determinable at all.

Everything returned is therefore either something the user told us,
something measured from the image, or something true of the category
by definition. Nothing is a guess dressed up as a fact.
"""

from backend import garment_taxonomy
from backend.occasion_model import (
    formality_for_category,
    profile_for_category,
)
from backend.outfit_recommendation import (
    LIGHT_MARKERS,
    WARM_LAYER_MARKERS,
    _tokens,
    effective_occasions,
)


# Seasons a garment suits, by what the garment IS. A coat is a
# cold-weather garment whatever colour it is; shorts are not.
def season_suitability(category):
    """
    Which seasons this garment type suits - as a statement about the
    category, never about the individual photo.
    """
    tokens = _tokens(category)

    if tokens & WARM_LAYER_MARKERS:
        return ["autumn", "winter"]

    if tokens & LIGHT_MARKERS:
        return ["spring", "summer"]

    # Everything else genuinely works year-round in most climates -
    # a shirt, a saree, jeans. Saying "all seasons" here is more
    # honest than picking two at random.
    return ["spring", "summer", "autumn", "winter"]


def weather_suitability(category):
    """
    Plain-language notes on the conditions this garment type helps
    with. Only what follows from the category; no claim is made about
    fabric, which cannot be seen.
    """
    tokens = _tokens(category)

    notes = []

    if tokens & WARM_LAYER_MARKERS:
        notes.append("cold")
        notes.append("wind")

    if tokens & LIGHT_MARKERS:
        notes.append("heat")

    role = garment_taxonomy.role_for(category)

    if role == garment_taxonomy.OUTERWEAR:
        notes.append("light rain")

    return notes


def style_label(category, styling=None):
    """
    casual / smart / formal / ethnic - from the catalogue usage mix
    and the formality it implies, not from a hand-written list.

    A manual "styling" tag (the Casual vs Wedding/Festive choice the
    app already offers for sarees and similar) always wins: the user
    knows which of their sarees is the wedding one, and no image model
    can tell.
    """
    if styling:
        return styling.strip().lower().replace("/", "-").replace(" ", "-")

    profile = profile_for_category(category)

    dominant = max(profile.items(), key=lambda pair: pair[1])[0] if profile else ""

    if dominant == "Ethnic":
        return "ethnic"

    if dominant == "Formal":
        return "formal"

    formality = formality_for_category(category)

    if formality >= 0.55:
        return "smart"

    return "casual"


def layering_role(category):
    """
    How this piece layers: "outer" goes over other things, "base" goes
    under them, "standalone" is a one-piece, "bottom" is worn below.
    Used to keep outfit building sensible (two base layers is not an
    outfit; a coat over a saree is fine).
    """
    role = garment_taxonomy.role_for(category)

    if role == garment_taxonomy.OUTERWEAR:
        return "outer"

    if role == garment_taxonomy.TOP:
        return "base"

    if role == garment_taxonomy.ONE_PIECE:
        return "standalone"

    if role == garment_taxonomy.BOTTOM:
        return "bottom"

    return "accessory"


def describe_item(category, colors=None, styling=None, material=None,
                  manual_occasion=""):
    """
    The full structured record for one wardrobe item.

    `colors` is color_detection.detect_colors()'s output, or None when
    colour analysis was unavailable - in which case the colour fields
    say so rather than defaulting to something plausible.

    Fields that cannot be determined are present but null/empty, so a
    caller can tell "we looked and could not say" apart from "we never
    looked" - and so the UI can invite the user to fill them in.
    """
    colors = colors or {}

    return {
        "category": category,
        # No dataset available to this project labels garment
        # sub-types (bootcut vs straight, A-line vs pencil), so this
        # stays empty rather than being invented.
        "subcategory": None,

        "role": garment_taxonomy.role_for(category),
        "family": garment_taxonomy.family_for(category),
        "layering_role": layering_role(category),

        "primary_color": colors.get("primary"),
        "secondary_colors": colors.get("secondary", []),
        "pattern": (
            "patterned" if colors.get("is_patterned")
            else ("solid" if colors.get("primary") else None)
        ),
        "color_confidence": colors.get("confidence"),

        # Only ever what the user typed. Fabric is not separable from
        # a photo, and a wrong guess here would corrupt the
        # weather scoring that reads it.
        "material": material or None,

        "style": style_label(category, styling),
        "formality": round(formality_for_category(category), 2),
        "occasions": sorted(effective_occasions(category, manual_occasion)),
        "season_suitability": season_suitability(category),
        "weather_suitability": weather_suitability(category),
    }
