import re
from collections import defaultdict
from datetime import datetime

from backend import outfit_assignment, outfit_builder
from backend.category_gender import is_allowed_for_account
from backend.color_theory import outfit_color_score
from backend.occasion_model import occasion_fit
from backend.style_compatibility import outfit_style_score


# ============================================================
# OUTFIT RECOMMENDATION
# ============================================================

# The full set of occasions the app understands, and the words an
# item might have been (optionally) manually tagged with that
# should still count as a match for one of them. "outing" and
# "festive" (an earlier, smaller occasion list) are kept as aliases
# so items tagged that way before this change don't silently
# disappear.
#
# Occasion eligibility is now AUTOMATIC by default (see
# infer_occasions_for_category() below): a wardrobe item no longer
# needs a manually chosen occasion at all - which category it is
# (Shirt, Saree, Lehenga, ...) already implies which occasions it's
# a sensible fit for, and that's what actually gates recommendations
# now. A manual "occasion" tag - old items that already have one, or
# a deliberate override set via Edit - still works, but it can only
# ADD an occasion on top of what the category already implies, never
# remove one. That keeps this strict in the sense the user cares
# about (a wedding search never returns a pair of gym shorts) without
# requiring anyone to tag anything by hand.
OCCASION_ALIASES = {
    "casual": {"casual", "daily", "daily wear", "home", "hangout", "errands"},
    "day_outing": {"day outing", "day_outing", "outing", "day out", "daytime", "sightseeing", "brunch"},
    "college": {"college", "campus", "university", "school"},
    "office": {"office", "work", "business", "formal"},
    "interview": {"interview", "job interview"},
    "date": {"date", "date night", "romantic"},
    "party": {"party", "night out", "clubbing", "special occasion", "celebration"},
    "wedding": {"wedding", "shaadi", "marriage", "reception", "engagement"},
    "traditional": {"traditional", "ethnic", "traditional/ethnic", "festive", "festival", "holiday"},
    "sports": {"sports", "sport", "workout", "gym", "exercise", "running", "yoga"}
}

CANONICAL_OCCASIONS = [
    "casual", "day_outing", "college", "office", "interview",
    "date", "party", "wedding", "traditional", "sports"
]

# ------------------------------------------------------------
# CATEGORY <-> OCCASION AFFINITY (a heuristic, not a trained model)
#
# This is what makes occasion detection AUTOMATIC: a wardrobe item's
# CATEGORY (Shirt, Saree, Lehenga, ...) - already known, whether the
# user picked it or the AI classifier detected it - directly implies
# which occasions it's a sensible fit for. Nobody has to tag "this is
# for a wedding"; a Lehenga already implies that. See
# infer_occasions_for_category() below, which is what actually reads
# this map, and effective_occasions(), which is the single place
# that combines this with an (optional) manual override.
#
# Keys are checked against normalized category TOKENS (see
# _tokens()/_normalize_category() below), so both singular and
# plural forms are listed here explicitly (a category string is
# never stemmed automatically) - "Shorts" needs to hit "shorts", not
# just "short".
#
# Saree and kurta-style ethnic wear are treated as suitable for
# Office/Interview alongside Western wear, reflecting how they're
# actually worn day to day - this isn't only "traditional event"
# clothing.
# ------------------------------------------------------------

CATEGORY_OCCASION_AFFINITY = {
    # NOTE: "party" was deliberately DROPPED from Shirt/Pant/Trouser
    # below (it was previously included) - part of fixing the
    # "recommendations show nearly all wardrobe items for every
    # occasion" complaint. A plain shirt+pant is genuinely
    # office/date/casual wear, not specifically party wear - keeping
    # "party" here meant these two extremely common categories (and
    # therefore most of a typical wardrobe) matched 6 of 9 occasions
    # each, drowning out anything more specifically party-appropriate
    # (T-Shirt, Jacket, Dress, Skirt, Lehenga/Saree/Gown all still
    # carry "party" on their own).
    "shirt": {"casual", "day_outing", "college", "office", "interview", "date"},
    "shirts": {"casual", "day_outing", "college", "office", "interview", "date"},
    "tshirt": {"casual", "day_outing", "college", "date", "sports"},
    "tshirts": {"casual", "day_outing", "college", "date", "sports"},
    # NOTE: the stored category string "T-Shirt" normalizes (see
    # _normalize_category) to the tokens {"t", "shirt"} - it shares
    # the "shirt" token with plain "Shirt" and, because
    # infer_occasions_for_category() unions every mapped token's
    # set, currently inherits Shirt's broader affinity (including
    # office/interview) rather than the narrower "tshirt"/"tshirts"
    # entries above. Those two entries only take effect for a
    # category actually stored as one word ("Tshirt"/"TShirt"
    # without a hyphen). Known imprecision, not a crash risk - a
    # T-Shirt still correctly never appears for Wedding/Traditional.
    "pant": {"casual", "day_outing", "college", "office", "interview", "date"},
    "pants": {"casual", "day_outing", "college", "office", "interview", "date"},
    "trouser": {"casual", "day_outing", "college", "office", "interview", "date"},
    "trousers": {"casual", "day_outing", "college", "office", "interview", "date"},
    "jean": {"casual", "day_outing", "college", "date"},
    "jeans": {"casual", "day_outing", "college", "date"},
    "denim": {"casual", "day_outing", "college", "date"},
    "denims": {"casual", "day_outing", "college", "date"},
    "short": {"casual", "day_outing", "college", "sports"},
    "shorts": {"casual", "day_outing", "college", "sports"},
    "skirt": {"casual", "day_outing", "college", "date", "party"},
    "skirts": {"casual", "day_outing", "college", "date", "party"},
    "jacket": {"casual", "college", "office", "interview", "date", "party", "day_outing"},
    "jackets": {"casual", "college", "office", "interview", "date", "party", "day_outing"},
    "coat": {"casual", "college", "office", "interview", "date", "party", "day_outing"},
    # Garment types that used to be missing here silently counted as
    # suitable for EVERY occasion (a blazer for a workout).
    "blazer": {"college", "office", "interview", "date", "party", "wedding"},
    "blazers": {"college", "office", "interview", "date", "party", "wedding"},
    "anarkali": {"wedding", "traditional", "party"},
    "anarkalis": {"wedding", "traditional", "party"},
    "coats": {"casual", "college", "office", "interview", "date", "party", "day_outing"},
    "dress": {"casual", "day_outing", "college", "date", "party"},
    "dresses": {"casual", "day_outing", "college", "date", "party"},
    "saree": {"wedding", "traditional"},
    "sarees": {"wedding", "traditional"},
    "lehenga": {"wedding", "traditional"},
    "lehengas": {"wedding", "traditional"},
    "kurta": {"casual", "day_outing", "college", "office", "traditional", "party", "wedding"},
    "kurtas": {"casual", "day_outing", "college", "office", "traditional", "party"},
    "kurti": {"casual", "day_outing", "college", "office", "traditional", "party"},
    "kurtis": {"casual", "day_outing", "college", "office", "traditional", "party"},
    # ---- newly-selectable IndoFashion-backed categories ------
    "sherwani": {"wedding", "traditional", "party"},
    "sherwanis": {"wedding", "traditional", "party"},
    "dhoti": {"wedding", "traditional", "party"},
    "nehru": {"office", "interview", "wedding", "traditional", "party"},
    "blouse": {"day_outing", "traditional", "wedding", "party"},
    "blouses": {"day_outing", "traditional", "wedding", "party"},
    "gown": {"date", "party", "wedding"},
    "gowns": {"date", "party", "wedding"},
    "dupatta": {"wedding", "traditional", "party"},
    "dupattas": {"wedding", "traditional", "party"},
    "palazzo": {"casual", "day_outing", "college", "office", "traditional", "party"},
    "palazzos": {"casual", "day_outing", "college", "office", "traditional", "party"},
    "legging": {"casual", "day_outing", "college", "office", "traditional"},
    "leggings": {"casual", "day_outing", "college", "office", "traditional"},
    "salwar": {"casual", "day_outing", "college", "office", "traditional"},
    "salwars": {"casual", "day_outing", "college", "office", "traditional"},
}


SPORTSWEAR_WORDS = {"track", "trackpants", "jogger", "joggers", "sweatpants",
                    "tracksuit", "gym", "activewear", "sportswear", "yoga", "running"}

_KIND_TO_AFFINITY_KEY = {
    "kurta_men": "kurta",
    "kurta_women": "kurta",
    "jeans": "jeans",
    "boots": None,
}


def infer_occasions_for_category(category):
    """
    The set of occasions this GARMENT CATEGORY is a typical fit for,
    purely from what kind of clothing it is - this is what makes
    occasion detection automatic: nobody has to tell the app a
    Lehenga is for weddings, that's just what a Lehenga is.

    An unrecognized category (an accessory, or anything not in
    CATEGORY_OCCASION_AFFINITY) is treated as suitable for EVERY
    occasion rather than none - a bag or a watch isn't wrong for any
    of them, so it shouldn't block an otherwise-good outfit from
    being built.
    """

    # Use the ONE most specific garment kind when it is known, so a
    # multi-word category doesn't inherit a broader word's occasions:
    # "Dhoti Pants" is a dhoti (not office trousers) and "T-Shirt" is
    # a t-shirt (not an office shirt). Unrecognised categories fall
    # back to matching every word, as before.
    # Sportswear words decide first: track pants are not office
    # trousers, and leggings (not salwars) are fine for a workout.
    words = _tokens(category)
    if words & SPORTSWEAR_WORDS:
        return {"casual", "day_outing", "sports"}

    kind = outfit_builder.kind_for(category)
    affinity_key = _KIND_TO_AFFINITY_KEY.get(kind, kind)
    if affinity_key in CATEGORY_OCCASION_AFFINITY:
        occasions = set(CATEGORY_OCCASION_AFFINITY[affinity_key])
        if kind == "salwar" and words & {"legging", "leggings"}:
            occasions.add("sports")
        return occasions

    tokens = _tokens(category)
    mapped_tokens = tokens & CATEGORY_OCCASION_AFFINITY.keys()

    if not mapped_tokens:
        return set(CANONICAL_OCCASIONS)

    occasions = set()
    for token in mapped_tokens:
        occasions |= CATEGORY_OCCASION_AFFINITY[token]

    return occasions


def _resolve_manual_occasion(manual_occasion):
    """
    Resolves a manually-set/legacy occasion string to the canonical
    occasion(s) it refers to (via OCCASION_ALIASES), or an empty set
    if it's blank or unrecognized. Returns a set even though this
    is normally exactly one value, so it composes simply with
    infer_occasions_for_category()'s set in effective_occasions().
    """

    manual_occasion = (manual_occasion or "").strip().lower()

    if not manual_occasion:
        return set()

    if manual_occasion in CANONICAL_OCCASIONS:
        return {manual_occasion}

    for canonical, aliases in OCCASION_ALIASES.items():
        if manual_occasion in aliases:
            return {canonical}

    return set()


def effective_occasions(category, manual_occasion=None):
    """
    The full set of occasions a wardrobe item is eligible for: every
    occasion its CATEGORY is a typical fit for, plus whatever
    occasion it was manually tagged with (if any) - manual tagging
    is ADDITIVE, never a replacement, so setting one can only ever
    make an item eligible for MORE occasions, never fewer. This is
    the single place that decides "what occasions is this item
    good for" - used both right after upload (so the frontend can
    show the user what got auto-detected) and when filtering
    recommendations (see _filter_by_occasion below), so the two can
    never disagree with each other.
    """

    occasions = infer_occasions_for_category(category)
    occasions |= _resolve_manual_occasion(manual_occasion)

    return occasions


def resolve_occasion_query(occasion):
    """
    Resolves a REQUESTED occasion (e.g. the ?occasion= query param
    on /api/ai/recommend) to its canonical form via OCCASION_ALIASES -
    the same resolution _resolve_manual_occasion() already applies
    to an item's manual tag, now applied symmetrically to the
    incoming request too, so a client can ask for a recognized
    synonym ("formal", "outing", "festive", ...) and not just the
    exact canonical word. Falls back to "casual" for a blank value,
    and passes an unrecognized value through unchanged (it will
    simply never match anything in _occasion_matches, which is safe).
    """

    occasion = (occasion or "casual").strip().lower()

    if occasion in CANONICAL_OCCASIONS:
        return occasion

    for canonical, aliases in OCCASION_ALIASES.items():
        if occasion in aliases:
            return canonical

    return occasion


def _occasion_matches(item, requested_occasion):
    """
    True when the requested occasion is one this item is eligible
    for - see effective_occasions() above.
    """

    requested_occasion = resolve_occasion_query(requested_occasion)

    return requested_occasion in effective_occasions(
        item.get("category"),
        item.get("occasion")
    )


def _filter_by_occasion(wardrobe_items, occasion):
    return [
        item for item in wardrobe_items
        if _occasion_matches(item, occasion)
    ]


def _is_flagged(items, occasion):
    """
    True when at least one item only qualifies for `occasion`
    because of a MANUAL override that its category wouldn't
    normally suggest (e.g. a T-Shirt manually tagged "Wedding") -
    surfaced to the frontend as "worth a second look" rather than
    silently trusted or silently excluded. An item that qualifies
    purely from its category (the normal, automatic case now) is
    never flagged.
    """

    for item in items:
        manual_occasions = _resolve_manual_occasion(item.get("occasion"))

        if occasion not in manual_occasions:
            continue

        if occasion not in infer_occasions_for_category(item.get("category")):
            return True

    return False


# ============================================================
# CATEGORY NORMALIZATION
#
# Wardrobe items can end up with two very different-looking
# category strings for the same kind of garment:
#   - the manual dropdown value from the frontend, e.g.
#     "Dhoti Pants", "Leggings & Salwars", "Men Kurta"
#   - the label written by the IndoFashion classifier, which
#     overrides the manual category for anything that isn't an
#     accessory, e.g. "dhoti_pants", "leggings_and_salwars",
#     "kurta_men"
#
# Both need to be recognized as the same garment type, so
# everything is normalized to lowercase, space-separated words
# before it's matched against any keyword list.
# ============================================================

def _normalize_category(category):
    if not category:
        return ""

    normalized = category.lower().strip()
    # Strips punctuation too, not just _/-/& - matters for labels
    # like "Kurta (Men)"/"Mojaris (Women)" (see backend.category_gender,
    # which had a real bug from this exact gap - parens were
    # swallowing the "men"/"women" disambiguation token).
    normalized = re.sub(r"[_\-&()]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()

    return normalized


def _tokens(category):
    normalized = _normalize_category(category)

    if not normalized:
        return set()

    return set(normalized.split(" "))


# Token-based keyword sets. A category matches a bucket if any of
# its normalized words hits one of these markers - this way
# "kurta_men", "women_kurta", "men kurta" and plain "kurta" (or a
# plural "kurtas") all land in the same bucket without needing an
# ever-growing list of exact strings.

TOP_MARKERS = {
    "shirt", "shirts", "tshirt", "top", "tops",
    "blouse", "blouses", "kurta", "kurtas", "kurti", "kurtis",
    # A Sherwani is a complete top-half garment worn over a kurta
    # pajama/churidar, not an optional outer layer the way a jacket
    # is - it needs to be pairable directly with a bottom (e.g.
    # Dhoti Pants) to form a wedding/traditional outfit at all.
    # Previously bucketed only under LAYER_MARKERS, which meant a
    # wardrobe with a Sherwani + Dhoti Pants and no separate Western
    # top produced ZERO wedding recommendations - a real gap found
    # while testing 8 gender+occasion combinations this round.
    "sherwani", "sherwanis"
}

BOTTOM_MARKERS = {
    "pant", "pants", "trouser", "trousers", "jean", "jeans",
    "denim", "denims", "short", "shorts", "skirt", "skirts",
    "bottom", "bottoms", "legging", "leggings", "palazzo",
    "palazzos", "dhoti", "salwar", "salwars"
}

DRESS_MARKERS = {
    "dress", "dresses", "saree", "sarees", "salwar",
    "lehenga", "lehengas", "gown", "gowns", "frock", "frocks"
}

ACCESSORY_MARKERS = {
    "shoe", "shoes", "sneaker", "sneakers", "mojari", "mojaris",
    "footwear", "boot", "boots",
    "bag", "bags", "watch", "watches", "belt", "belts",
    "jewellery", "jewelry", "accessory", "accessories",
    "dupatta", "dupattas", "petticoat", "petticoats",
    # ---- newly-added jewelry/accessory categories -------------
    # Without these, an Earrings/Neck Chain/Finger Ring/Hand Cuff/
    # Head Accessory item matched NONE of the marker sets below and
    # was silently dropped from every outfit - never crashing, never
    # showing an error, just invisible. Same bug that "footwear"/
    # "boot"/"boots" above and "denim"/"denims" in BOTTOM_MARKERS
    # just got fixed for.
    "earring", "earrings", "neck", "chain", "chains",
    "finger", "ring", "rings", "cuff", "cuffs",
    "head", "headwear"
}

# Layering pieces - not a top/bottom/dress on their own, but worth
# folding in with accessories so they can still be suggested
# alongside an outfit instead of being silently ignored.
LAYER_MARKERS = {
    "jacket", "jackets", "sweater", "sweaters", "nehru",
    "coat", "coats"
    # (sherwani/sherwanis moved to TOP_MARKERS above)
}

# Rough category heuristics for weather suitability - not a real
# fabric/weight model, just a starting point until one exists.
LIGHT_MARKERS = {
    "shirt", "tshirt", "blouse", "shorts", "skirt", "dress",
    "top", "kurta", "kurtas", "kurti", "kurtis", "saree",
    "sarees", "dupatta", "dupattas", "palazzo", "palazzos"
}

WARM_LAYER_MARKERS = {
    "jacket", "jackets", "sweater", "sweaters",
    "nehru", "sherwani", "sherwanis",
    "coat", "coats", "boot", "boots"
}

# The optional "material" field (see app.py's add_wardrobe_item -
# ACCESSORY_CATEGORIES / MATERIAL_CATEGORIES in Wardrobe.js decide
# which categories even show that input) is free text, not a
# controlled vocabulary - this only checks for a WORD match, so
# "wool", "Wool blend", and "80% wool" all count, but a material
# typo or a language other than English won't. This is what lets a
# wool coat/sweater get recognized as cold-weather-appropriate even
# though "material" itself isn't a clothing category - see
# WARM_LAYER_MARKERS above for the category-based half of this.
WARM_MATERIAL_MARKERS = {
    "wool", "fleece", "thermal", "fur", "down",
    "flannel", "corduroy", "cashmere"
}

# Kept in sync with (but decoupled from) backend.weather.
# HUMID_THRESHOLD_PCT - this module deliberately never imports from
# backend.weather so it keeps working with ANY weather-shaped dict
# (a test fixture, a future second provider), not just OpenWeatherMap
# specifically. If the two ever drift apart, the worst case is one
# module calling a day "humid" a little earlier/later than the
# other - never a crash, since both simply skip this note when the
# key is missing.
HUMID_THRESHOLD_PCT = 70

# Worth mentioning rather than worth panicking about: below this the
# chance is too low to change what anyone wears.
RAIN_MENTION_PCT = 40

# How far "feels like" must diverge from the thermometer before it is
# worth telling the user about.
FEELS_LIKE_GAP_C = 3


def _has_warm_material(item):
    material = (item.get("material") or "").lower()
    if not material:
        return False
    material_tokens = set(re.split(r"[^a-z]+", material))
    return bool(material_tokens & WARM_MATERIAL_MARKERS)


def _weather_score(items, weather):
    """
    Rough weather-suitability score. Returns (points, reasons):
      - points: a neutral 5 points per item when there's no weather
        info, or when an item's category doesn't clearly fall into a
        "light" or "warm layer" bucket - weather should nudge
        ranking, not hide clothes the heuristic can't classify.
      - reasons: short, de-duplicated, order-preserved plain-English
        notes about WHY weather favored (or flagged) something in
        this outfit, used by _build_why() to populate the "why this
        works" bullets. Always [] when there's no weather info.

    Covers temperature (hot/cold), rain and wind on the pieces
    actually in the outfit, plus an honest humidity note (humidity
    doesn't change which pieces get picked - no wardrobe field says
    how breathable a fabric is - but the spec's "be honest, don't
    guess" instruction still means a muggy day should say so rather
    than staying silent about it).
    """

    if not weather:
        return 0, []

    points = 0
    notes = []

    is_hot = weather.get("is_hot")
    is_cold = weather.get("is_cold")
    is_rainy = weather.get("is_rainy")
    is_windy = weather.get("is_windy")

    for item in items:

        tokens = _tokens(item.get("category"))
        warm_material = _has_warm_material(item)

        if is_hot and tokens & LIGHT_MARKERS:
            points += 25
            notes.append("kept it light for today's heat")

        elif is_cold and (tokens & WARM_LAYER_MARKERS):
            points += 25
            notes.append("adds warmth for today's cold")

        elif is_cold and warm_material:
            # Category alone didn't mark this as a warm layer (e.g.
            # a plain "Shirt" or "Kurta"), but the user noted a warm
            # material on it - still a genuinely good cold-weather
            # pick, just a slightly smaller nudge than a category
            # that's unambiguously outerwear.
            points += 20
            notes.append("its warm material suits the cold")

        elif is_rainy and (tokens & WARM_LAYER_MARKERS):
            points += 15
            notes.append("gives some cover from the rain")

        else:
            points += 5

        # Wind is an INDEPENDENT small nudge, not an alternative to
        # the temperature/rain logic above - a warm layer earns this
        # on top of its hot/cold/rain points, since it helps with the
        # wind regardless of why it was already a good pick.
        if is_windy and (tokens & WARM_LAYER_MARKERS):
            points += 8
            notes.append("also helps block today's wind")

    if (
        weather.get("humidity_pct") is not None
        and weather["humidity_pct"] >= HUMID_THRESHOLD_PCT
    ):
        notes.append(
            "it's a humid day, so lighter fabrics will feel more comfortable"
        )

    # Rain PROBABILITY, separate from "it is raining". A 70% chance is
    # worth dressing for even though every individual reading may come
    # back dry, and saying the number is more useful than a flat
    # "might rain" - the user can decide what to do with 55% vs 90%.
    rain_chance = weather.get("rain_chance_pct")

    if rain_chance is not None and rain_chance >= RAIN_MENTION_PCT:
        notes.append(
            f"there's a {rain_chance}% chance of rain, so something "
            "water-resistant (or an umbrella) is worth having"
        )

    # When what it FEELS like differs noticeably from the thermometer,
    # say so - that gap is usually wind chill or humidity, and it is
    # the reason a "mild" day can still need a jacket.
    temperature = weather.get("temp_c")
    feels_like = weather.get("feels_like_c")

    if (
        temperature is not None
        and feels_like is not None
        and abs(feels_like - temperature) >= FEELS_LIKE_GAP_C
    ):
        if feels_like < temperature:
            notes.append(
                f"it's {temperature}\u00b0C but feels nearer "
                f"{feels_like}\u00b0C, so dress for the colder number"
            )
        else:
            notes.append(
                f"it's {temperature}\u00b0C but feels nearer "
                f"{feels_like}\u00b0C, so keep it breathable"
            )

    # Several items can trigger the identical note (e.g. two warm
    # layers on a cold day) - de-duplicate while keeping first-seen
    # order, then cap so "why" stays a short, scannable list rather
    # than repeating itself.
    seen = set()
    reasons = []
    for note in notes:
        if note not in seen:
            seen.add(note)
            reasons.append(note)

    return points / len(items), reasons[:3]


# ------------------------------------------------------------
# ACTIVITY -> CATEGORY AFFINITY (optional, additive - never a hard
# filter like occasion). Spec section asks for "activity/occasion"
# awareness; unlike occasion, an unmatched or unspecified activity
# never hides anything - it's a small ranking nudge on top of
# already-valid, already-occasion-filtered outfits, using only
# categories that actually exist in this app's wardrobe (see
# ALL_CATEGORIES in Wardrobe.js) rather than invented ones.
# ------------------------------------------------------------

CANONICAL_ACTIVITIES = ["sports", "outdoor", "formal_event", "travel"]

ACTIVITY_CATEGORY_AFFINITY = {
    "sports": {"tshirt", "shorts", "footwear"},
    "outdoor": {"jacket", "coat", "boots", "pant", "trouser", "trousers"},
    "formal_event": {"saree", "sarees", "lehenga", "lehengas", "gown", "gowns", "sherwani", "sherwanis", "kurta", "kurtas"},
    "travel": {"tshirt", "shirt", "pant", "jean", "jeans", "denim", "denims", "jacket", "footwear"},
}


def _activity_bonus(items, activity):
    """
    Small, additive bonus (never a filter) when an outfit's pieces
    line up with the stated activity. Returns (points, reason) -
    reason is None when there's no activity, or when nothing in the
    outfit happens to match it (an unmatched activity is silently
    neutral, not penalized - the wardrobe may just not have a
    dedicated piece for it).
    """
    if not activity:
        return 0, None

    affinity = ACTIVITY_CATEGORY_AFFINITY.get(activity)
    if not affinity:
        return 0, None

    matches = 0
    for item in items:
        tokens = _tokens(item.get("category"))
        if tokens & affinity:
            matches += 1

    if not matches:
        return 0, None

    label = activity.replace("_", " ")
    return min(matches * 6, 12), f"also fits well for {label}"


# ------------------------------------------------------------
# OCCASION -> COLOR PREFERENCE
#
# NOT a fixed universal color rule (the spec this was built against
# explicitly warns against that) - a small, explainable nudge on
# top of color_theory's harmony score, reflecting that different
# occasions reward different kinds of "good" color combinations:
# a restrained, low-contrast pairing reads as professional for an
# interview, while the same restraint would read as underdressed
# for a wedding, which tolerates (and often rewards) richer, bolder
# combinations. This never overrides color_theory's underlying
# harmony judgment - a genuinely clashing pair is never rescued by
# occasion, and a genuinely harmonious pair is never rejected by it.
# ------------------------------------------------------------

_RESTRAINED_REASONS = {"neutral balancing", "monochromatic"}
_BOLD_REASONS = {"complementary colors", "triadic-adjacent colors"}

_OCCASION_COLOR_PREFERENCE = {
    "interview": "restrained",
    "office": "restrained",
    "wedding": "bold",
    "traditional": "bold",
    "party": "bold",
}


def _occasion_color_bonus(occasion, color_reasons):
    preference = _OCCASION_COLOR_PREFERENCE.get(occasion)
    if not preference:
        return 0

    matches_preference = {"restrained": _RESTRAINED_REASONS, "bold": _BOLD_REASONS}[preference]

    for reason in color_reasons:
        for keyword in matches_preference:
            if keyword in reason:
                return 3

    return 0


def _score_outfit(items, occasion, weather=None, activity=None):
    """
    Suitability score for one outfit, combining several INDEPENDENT
    factors rather than one flat heuristic:

      - fit_points: a bonus when nothing in the outfit is "flagged"
        (see _is_flagged - every item's category is genuinely a
        typical fit for this occasion, none relying on a manual
        override the category itself wouldn't suggest).
      - color_points: real color-harmony scoring (complementary/
        analogous/monochromatic/neutral-balancing/triadic - see
        backend.color_theory), not just "are the color words
        different", plus a small occasion-appropriate nudge (see
        _occasion_color_bonus above).
      - style_points: style/formality compatibility between the
        pieces (see backend.style_compatibility) - a Blazer next to
        Gym Shorts scores lower here even though both might pass
        occasion filtering on their own.
      - weather_points: temperature/rain/wind/humidity awareness -
        see _weather_score above. Zero (and no reasons) when
        `weather` is None, so requests without weather behave exactly
        as before this was added.
      - activity_points: optional, additive activity-fit nudge - see
        _activity_bonus above. Zero (and no reason) when `activity`
        is None/unrecognized/unmatched.
      - occasion_points: how well this outfit suits THIS occasion
        specifically - see backend.occasion_model, which scores each
        garment against usage statistics measured from 44,446 real
        catalogue items plus a formality target per occasion.

        This is the term that makes the ranking actually depend on
        the occasion. Without it (the behaviour before it existed)
        every factor above was occasion-independent apart from a
        3-point colour nudge, so any two occasions whose eligible
        items overlapped returned an identical list in an identical
        order - measurably so: casual, day_outing, college and date
        all returned the same five outfits, each scoring exactly
        65.0, on a plain jeans-and-t-shirts wardrobe.

    Every item here has already passed _filter_by_occasion AND
    _filter_by_gender, so all of them are already valid for this
    request - this scoring step only RANKS valid combinations
    against each other; a high color, style, weather or activity
    score can never rescue an outfit that failed a hard restriction;
    it can only rank one valid outfit above another valid one.
    """

    flagged = _is_flagged(items, occasion)

    fit_points = 0 if flagged else 20

    color_points, color_reasons = outfit_color_score(items)
    color_points += _occasion_color_bonus(occasion, color_reasons)

    style_points, style_reasons = outfit_style_score(items)

    weather_points, weather_reasons = _weather_score(items, weather)

    activity_points, activity_reason = _activity_bonus(items, activity)
    activity_reasons = [activity_reason] if activity_reason else []

    occasion_points, occasion_reasons = occasion_fit(items, occasion)

    return {
        "score": round(
            fit_points + color_points + style_points
            + weather_points + activity_points + occasion_points,
            1
        ),
        "flagged": flagged,
        "color_reasons": color_reasons,
        "style_reasons": style_reasons,
        "weather_reasons": weather_reasons,
        "activity_reasons": activity_reasons,
        "occasion_reasons": occasion_reasons,
    }


def _build_why(
    occasion, flagged, color_reasons, style_reasons,
    weather_reasons=None, activity_reasons=None, occasion_reasons=None
):
    """
    Short, human-readable "why this works" bullets (spec section 10)
    - built directly from the same reasons already computed for
    scoring, never invented after the fact. A flagged outfit still
    gets bullets (it's still a valid, gender/occasion-approved
    combination - "flagged" only means at least one piece is an
    occasion stretch), it's just honest about that instead of
    pretending every piece is a perfect fit.

    `weather_reasons`/`activity_reasons` default to None so every
    existing call site (and every existing test) that doesn't pass
    them keeps working unchanged - they just produce no extra
    bullets, exactly like before weather/activity awareness existed.
    """
    label = occasion.replace("_", " ")
    bullets = []

    if flagged:
        bullets.append(
            f"One piece here is a bit of a stretch for {label}, but still wearable together."
        )
    else:
        bullets.append(f"Every piece is a genuine fit for {label}.")

    for reason in color_reasons:
        if "no color pairing" not in reason:
            bullets.append(f"Color: {reason}.")

    for reason in style_reasons:
        if "no style pairing" not in reason:
            bullets.append(f"Style: {reason}.")

    for reason in (weather_reasons or []):
        bullets.append(f"Weather: {reason}.")

    for reason in (activity_reasons or []):
        bullets.append(f"Activity: {reason}.")

    # Placed last deliberately: these say how well the outfit suits
    # the occasion as a WHOLE (see backend.occasion_model), which
    # reads as a summing-up after the per-factor bullets above.
    for reason in (occasion_reasons or []):
        bullets.append(f"Occasion: {reason}.")

    return bullets


def _filter_by_gender(wardrobe_items, account_gender):
    """
    Defense-in-depth gender separation: even though upload-time
    AI auto-detection and the manual category dropdown are already
    gender-guarded (see app.py), this is the LAST line of defense
    that keeps a Male account's recommendations from ever including
    a confidently women's-only category (Saree, Lehenga, Blouse,
    Gown, Petticoat, Dupatta, Palazzos, Leggings & Salwars, Skirt,
    Dress, women's Kurta/Mojaris) and vice versa - including for
    legacy/migrated items that predate this gender system. A unisex
    item, or an account with no gender on file, is never filtered.
    """
    if not account_gender:
        return wardrobe_items

    return [
        item for item in wardrobe_items
        if is_allowed_for_account(item.get("category"), account_gender)
    ]


def _outfit_item_ids(outfit):
    """
    The _ids of an outfit's MAIN garments (top/bottom, one-piece,
    blouse, layer, footwear) - accessories are left out on purpose.
    Used by _diversify() below and by trip_planner.py to spread which
    clothes get used; a wardrobe usually has only a couple of watches
    or bags, and those repeating is expected, not a lack of variety.
    Falls back to every item for outfits built before core ids existed.
    """
    if outfit.get("core_item_ids"):
        return list(outfit["core_item_ids"])

    return [
        item.get("_id")
        for item in outfit["items"]
        if item.get("_id")
    ]


def _diversify(candidates, limit):
    """
    Greedily picks up to `limit` outfits, spreading which garments get
    used instead of taking the raw top N by score - otherwise one shirt
    that pairs well with everything fills every slot. At each step it
    takes the outfit whose garments have been used least so far, ties
    broken by score, so the best outfits still come first.
    """
    remaining = list(candidates)
    selected = []
    usage_count = defaultdict(int)

    while remaining and len(selected) < limit:

        remaining.sort(
            key=lambda outfit: (
                sum(
                    usage_count[item_id]
                    for item_id in _outfit_item_ids(outfit)
                ),
                -outfit["score"],
            )
        )

        chosen = remaining.pop(0)
        selected.append(chosen)

        for item_id in _outfit_item_ids(chosen):
            usage_count[item_id] += 1

    return selected


# ============================================================
# WEAR HISTORY + LIKE/DISLIKE
#
# wear_history: list of {"item_ids": [...], "outfit_key": "...",
#                        "worn_at": datetime}  (see outfit_feedback.py)
# feedback:     {outfit_key: "like" | "dislike"}
#
# Worn-recently pieces are ranked LOWER (not hidden) so suggestions
# rotate through the wardrobe; a disliked combination is never shown
# again; a liked one gets a boost.
# ============================================================

RECENT_DAYS = 2            # worn in the last 2 days -> big penalty
WEEK_DAYS = 7              # worn earlier this week  -> smaller penalty
RECENT_ITEM_PENALTY = 12
WEEK_ITEM_PENALTY = 6
SAME_OUTFIT_PENALTY = 10   # this exact combination worn this week
LIKE_BONUS = 12
COLD_SHORTS_PENALTY = 15


def _days_since(moment, now):
    if not moment:
        return None
    try:
        return (now - moment).total_seconds() / 86400
    except TypeError:
        return None


def _history_adjustment(core_items, key, wear_history, now):
    if not wear_history:
        return 0, []

    last_item_wear = {}
    last_outfit_wear = None

    for entry in wear_history:
        worn_at = entry.get("worn_at")
        for worn_id in entry.get("item_ids") or []:
            previous = last_item_wear.get(worn_id)
            if previous is None or (worn_at and worn_at > previous):
                last_item_wear[worn_id] = worn_at
        if key and entry.get("outfit_key") == key:
            if last_outfit_wear is None or (worn_at and worn_at > last_outfit_wear):
                last_outfit_wear = worn_at

    points = 0
    reasons = []

    for item in core_items:
        days = _days_since(last_item_wear.get(str(item.get("_id"))), now)
        if days is None:
            continue
        name = item.get("category") or "this piece"
        if days <= RECENT_DAYS:
            points -= RECENT_ITEM_PENALTY
            reasons.append(f"you wore this {name} very recently")
        elif days <= WEEK_DAYS:
            points -= WEEK_ITEM_PENALTY
            reasons.append(f"you wore this {name} earlier this week")

    outfit_days = _days_since(last_outfit_wear, now)
    if outfit_days is not None and outfit_days <= WEEK_DAYS:
        points -= SAME_OUTFIT_PENALTY
        reasons.append("you wore this exact combination this week")

    if not reasons:
        reasons.append("a fresh pick - none of these were worn this week")

    return points, reasons


def _cold_weather_penalty(core_kinds, weather):
    if weather and weather.get("is_cold") and "shorts" in core_kinds:
        return -COLD_SHORTS_PENALTY, ["shorts are a chilly choice today"]
    return 0, []


ETHNIC_ONLY_OCCASIONS = {"traditional"}


def _core_candidates(gender_ok, activity, feedback):
    """
    Every wearable main outfit in the wardrobe (before any occasion
    is chosen), with the occasions and activities it is eligible for
    and how well it fits each one.
    """
    groups = outfit_builder.classify_items(gender_ok)
    candidates = {}

    for combo in outfit_builder.core_combinations(groups):
        core = combo["core"]
        core_kinds = [kind for kind, _ in core]
        core_items = [item for _, item in core]
        key = outfit_builder.outfit_key(core_items)

        if not key or key in candidates or feedback.get(key) == "dislike":
            continue

        # A blouse follows its saree/lehenga, so only the main pieces
        # decide which occasions the outfit suits.
        deciding = [
            item for kind, item in core
            if outfit_builder.ROLE.get(kind) != outfit_builder.SET_PART
        ]
        eligible = set(CANONICAL_OCCASIONS)
        for item in deciding:
            eligible &= effective_occasions(item.get("category"), item.get("occasion"))

        # Traditional is ETHNIC-ONLY: no western pieces
        # and no Indo-western mixes (kurta + jeans) there.
        if outfit_builder.outfit_style(core_kinds) != "ethnic":
            eligible -= ETHNIC_ONLY_OCCASIONS

        if not eligible:
            continue

        fit = {
            occ: occasion_fit(core_items, occ)[0]
            + outfit_assignment.kind_weight(
                outfit_assignment.OCCASION_KIND_WEIGHT.get(occ, {}), core_kinds
            )
            + outfit_assignment.colour_weight(occ, deciding)
            for occ in eligible
        }

        activities = outfit_assignment.eligible_activities(core_kinds)
        activity_fit = {
            name: outfit_assignment.kind_weight(
                outfit_assignment.ACTIVITY_RULES[name]["weight"], core_kinds
            )
            for name in activities
        }

        candidates[key] = {
            "combo": combo,
            "core": core,
            "core_kinds": core_kinds,
            "core_items": core_items,
            "eligible": eligible,
            "fit": fit,
            "activities": activities,
            "activity_fit": activity_fit,
        }

    return candidates


def _complete_and_score(
    candidate, extras, occasion, weather, activity, wear_history,
    feedback, now
):
    """Adds layer/footwear/accessories, then scores one outfit."""
    core = candidate["core"]
    core_kinds = candidate["core_kinds"]
    core_items = candidate["core_items"]
    key = outfit_builder.outfit_key(core_items)

    extra_notes = list(candidate["combo"]["notes"])

    garments = list(core_items)
    garment_kinds = list(core_kinds)
    roles = {}
    for kind, item in core:
        roles[str(item.get("_id"))] = outfit_builder.ROLE.get(kind)

    layer = outfit_builder.choose_layer(core, extras, occasion, weather)
    if layer and not outfit_builder.too_many_colors(garments + [layer[1]]):
        layer_kind, layer_item, layer_reason = layer
        garments.insert(0, layer_item)
        garment_kinds.append(layer_kind)
        roles[str(layer_item.get("_id"))] = outfit_builder.LAYER
        extra_notes.append(f"Layer: {layer_reason}.")

    footwear = outfit_builder.choose_footwear(
        garment_kinds, garments, extras, weather, occasion
    )
    if footwear and not outfit_builder.too_many_colors(garments + [footwear[1]]):
        garments.append(footwear[1])
        roles[str(footwear[1].get("_id"))] = outfit_builder.FOOTWEAR

    accessories = outfit_builder.choose_accessories(
        garment_kinds, garments, extras, occasion
    )
    for _, accessory in accessories:
        roles[str(accessory.get("_id"))] = outfit_builder.ACCESSORY

    outcome = _score_outfit(garments, occasion, weather, activity)

    cold_points, cold_reasons = _cold_weather_penalty(core_kinds, weather)
    # Only the main garments count for "worn recently" - most people
    # own a couple of pairs of shoes, and wearing them again is not a
    # lack of variety.
    history_points, history_reasons = _history_adjustment(
        core_items, key, wear_history, now
    )
    liked = feedback.get(key) == "like"
    like_points = LIKE_BONUS if liked else 0

    score = round(outcome["score"] + cold_points + history_points + like_points, 1)

    why = _build_why(
        occasion, outcome["flagged"],
        outcome["color_reasons"], outcome["style_reasons"],
        outcome["weather_reasons"] + cold_reasons,
        outcome["activity_reasons"], outcome["occasion_reasons"]
    )
    why.extend(extra_notes)
    if liked:
        why.append("You liked this combination before.")
    if wear_history:
        why.extend(f"History: {reason}." for reason in history_reasons)

    return {
        "occasion": occasion,
        "activity": activity,
        "items": garments + [item for _, item in accessories],
        "type": candidate["combo"]["type"],
        "style": outfit_builder.outfit_style(garment_kinds),
        "roles": roles,
        "outfit_key": key,
        # What the frontend sends back for "I wore this" / like /
        # dislike, so the server computes the same outfit_key.
        "key_item_ids": [
            str(item.get("_id")) for item in core_items if item.get("_id")
        ],
        "core_item_ids": [
            str(item.get("_id")) for item in garments if item.get("_id")
        ],
        "liked": liked,
        "score": score,
        "flagged": outcome["flagged"],
        "color_reasons": outcome["color_reasons"],
        "style_reasons": outcome["style_reasons"],
        "weather_reasons": outcome["weather_reasons"] + cold_reasons,
        "activity_reasons": outcome["activity_reasons"],
        "occasion_reasons": outcome["occasion_reasons"],
        "history_reasons": history_reasons if wear_history else [],
        "why": why,
    }


def _extras_for(gender_ok, occasion, activity):
    """Layers, footwear and accessories allowed for this occasion/activity."""
    groups = outfit_builder.classify_items(_filter_by_occasion(gender_ok, occasion))
    for role in (outfit_builder.LAYER, outfit_builder.FOOTWEAR, outfit_builder.ACCESSORY):
        groups[role] = [
            (kind, item) for kind, item in groups[role]
            if outfit_assignment.activity_allows_extra(role, kind, activity)
        ]
    return groups


def recommend_outfits(
    wardrobe_items, occasion="casual", weather=None,
    account_gender=None, limit=10, activity=None,
    wear_history=None, feedback=None, now=None,
    exclusive=False, notes_out=None
):
    """
    Generate ranked, complete outfits from the user's wardrobe.

      1. HARD FILTERS - gender, occasion, and (if chosen) activity.
      2. BUILD - backend.outfit_builder decides which garments can be
         worn together and rejects clashing colours.
      3. KEEP OCCASIONS DIFFERENT (exclusive=True, used by the app) -
         backend.outfit_assignment gives every outfit ONE home
         occasion (and one home activity), so casual, college, day
         out... don't all show the same outfits.
      4. COMPLETE - layer only when there's a reason, matching
         footwear, up to 2 suitable accessories.
      5. SCORE - colour, style, weather, activity, occasion fit, wear
         history and likes.
      6. DIVERSIFY - so one garment doesn't fill every slot.

    exclusive=False (the default, used by the trip planner and tests)
    returns every suitable outfit without the one-home-occasion rule.
    notes_out, if a list is passed, receives plain-English notes
    about what was done (e.g. outfits kept for other occasions).
    """
    if not wardrobe_items:
        return []

    feedback = feedback or {}
    now = now or datetime.utcnow()
    notes = notes_out if notes_out is not None else []

    occasion = resolve_occasion_query(occasion)
    activity_key = outfit_assignment.resolve_activity(activity)

    gender_ok = _filter_by_gender(wardrobe_items, account_gender)
    candidates = _core_candidates(gender_ok, activity_key, feedback)

    suitable = {
        key: c for key, c in candidates.items()
        if occasion in c["eligible"]
        and outfit_assignment.activity_allows_core(c["core_kinds"], activity_key)
    }

    if not suitable:
        if activity_key and any(occasion in c["eligible"] for c in candidates.values()):
            notes.append(
                f"None of your {occasion.replace('_', ' ')} outfits suit "
                f"{outfit_assignment.ACTIVITY_RULES[activity_key]['label']}. "
                f"Try another activity, or add pieces meant for it."
            )
        return []

    chosen = suitable

    if exclusive:
        homes = outfit_assignment.draft(
            {key: {"eligible": c["eligible"], "fit": c["fit"]}
             for key, c in candidates.items()},
            CANONICAL_OCCASIONS,
        )
        mine = {key: c for key, c in suitable.items() if homes.get(key) == occasion}

        if activity_key and mine:
            activity_homes = outfit_assignment.draft(
                {key: {"eligible": candidates[key]["activities"],
                       "fit": candidates[key]["activity_fit"]}
                 for key, c in candidates.items() if homes.get(key) == occasion},
                list(outfit_assignment.ACTIVITY_RULES),
            )
            mine = {key: c for key, c in mine.items()
                    if activity_homes.get(key) == activity_key}

        other_occasions = sorted({
            homes[key].replace("_", " ")
            for key in suitable
            if homes.get(key) and homes[key] != occasion
        })
        moved_activity = sum(
            1 for key in suitable
            if homes.get(key) == occasion and key not in mine
        )

        if mine:
            chosen = mine
            if other_occasions:
                notes.append(
                    "To keep every occasion different, outfits that suit "
                    "another occasion better are shown there instead ("
                    + ", ".join(other_occasions) + ")."
                )
            if moved_activity:
                notes.append(
                    f"{moved_activity} more outfit(s) for this occasion are "
                    f"shown under other activities."
                )
        else:
            notes.append(
                "Your wardrobe doesn't have pieces specific enough to give "
                "this choice its own outfits, so these are shared with "
                "other occasions or activities. Adding a few more items "
                "will make each one different."
            )

    extras = _extras_for(gender_ok, occasion, activity_key)

    recommendations = [
        _complete_and_score(c, extras, occasion, weather, activity_key,
                            wear_history, feedback, now)
        for c in chosen.values()
    ]

    return _diversify(recommendations, limit=limit)


def describe_missing_pieces(wardrobe_items, occasion="casual", account_gender=None):
    """
    Plain-English notes when the wardrobe can't make a complete outfit
    for this occasion - never invents wardrobe contents. Uses the same
    filters and the same outfit_builder rules as recommend_outfits(),
    so the note always matches what actually happened.
    """
    occasion = resolve_occasion_query(occasion)
    label = occasion.replace("_", " ")

    gender_ok = _filter_by_gender(wardrobe_items, account_gender)
    filtered = _filter_by_occasion(gender_ok, occasion)

    if not filtered:
        return [
            f"Your wardrobe does not contain any items suitable for "
            f"{label} yet."
        ]

    groups = outfit_builder.classify_items(filtered)
    groups[outfit_builder.SET_PART] = outfit_builder.classify_items(
        gender_ok
    )[outfit_builder.SET_PART]

    if any(True for _ in outfit_builder.core_combinations(groups)):
        return []

    tops = groups[outfit_builder.TOP]
    bottoms = groups[outfit_builder.BOTTOM]

    if tops and bottoms:
        compatible = any(
            bottom_kind in outfit_builder.TOP_BOTTOM_PAIRS.get(top_kind, set())
            for top_kind, _ in tops
            for bottom_kind, _ in bottoms
        )
        if compatible:
            return [
                f"Your {label} tops and bottoms clash in colour, so no "
                f"outfit was suggested. A neutral piece (black, white, "
                f"grey, beige, navy or denim) would pair with them."
            ]
        needed = sorted({
            bottom
            for top_kind, _ in tops
            for bottom in outfit_builder.TOP_BOTTOM_PAIRS.get(top_kind, set())
        })
        return [
            f"Your {label} tops and bottoms don't go together. Your tops "
            f"pair with: {', '.join(needed)}."
        ]

    if tops:
        return [
            f"Your wardrobe does not contain a suitable bottom to "
            f"pair with your {label} tops."
        ]

    if bottoms:
        return [
            f"Your wardrobe does not contain a suitable top to pair "
            f"with your {label} bottoms."
        ]

    if groups[outfit_builder.SET_PART]:
        return [
            f"You have blouses, but no saree or lehenga suitable for "
            f"{label} to wear them with."
        ]

    return [
        f"Your wardrobe does not contain a complete outfit for {label} "
        f"yet - only accessories, footwear or layers."
    ]
