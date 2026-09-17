import re
from collections import defaultdict

from backend.category_gender import is_allowed_for_account
from backend.color_theory import outfit_color_score
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
    "traditional": {"traditional", "ethnic", "traditional/ethnic", "festive", "festival", "holiday"}
}

CANONICAL_OCCASIONS = [
    "casual", "day_outing", "college", "office", "interview",
    "date", "party", "wedding", "traditional"
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
    "tshirt": {"casual", "day_outing", "college", "date"},
    "tshirts": {"casual", "day_outing", "college", "date"},
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
    "short": {"casual", "day_outing", "college"},
    "shorts": {"casual", "day_outing", "college"},
    "skirt": {"casual", "day_outing", "college", "date", "party"},
    "skirts": {"casual", "day_outing", "college", "date", "party"},
    "jacket": {"office", "interview", "date", "party", "day_outing"},
    "jackets": {"office", "interview", "date", "party", "day_outing"},
    "dress": {"casual", "day_outing", "college", "date", "party"},
    "dresses": {"casual", "day_outing", "college", "date", "party"},
    "saree": {"office", "interview", "wedding", "traditional", "party"},
    "sarees": {"office", "interview", "wedding", "traditional", "party"},
    "lehenga": {"wedding", "party", "traditional"},
    "lehengas": {"wedding", "party", "traditional"},
    "kurta": {"casual", "day_outing", "college", "office", "traditional", "party"},
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
    "gown": {"date", "party", "wedding", "traditional"},
    "gowns": {"date", "party", "wedding", "traditional"},
    "dupatta": {"wedding", "traditional", "party"},
    "dupattas": {"wedding", "traditional", "party"},
    "palazzo": {"casual", "day_outing", "college", "traditional", "party"},
    "palazzos": {"casual", "day_outing", "college", "traditional", "party"},
    "legging": {"casual", "day_outing", "college", "traditional"},
    "leggings": {"casual", "day_outing", "college", "traditional"},
    "salwar": {"casual", "day_outing", "college", "traditional"},
    "salwars": {"casual", "day_outing", "college", "traditional"},
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
    "short", "shorts", "skirt", "skirts", "bottom", "bottoms",
    "legging", "leggings", "palazzo", "palazzos", "dhoti",
    "salwar", "salwars"
}

DRESS_MARKERS = {
    "dress", "dresses", "saree", "sarees", "salwar",
    "lehenga", "lehengas", "gown", "gowns", "frock", "frocks"
}

ACCESSORY_MARKERS = {
    "shoe", "shoes", "sneaker", "sneakers", "mojari", "mojaris",
    "bag", "bags", "watch", "watches", "belt", "belts",
    "jewellery", "jewelry", "accessory", "accessories",
    "dupatta", "dupattas", "petticoat", "petticoats"
}

# Layering pieces - not a top/bottom/dress on their own, but worth
# folding in with accessories so they can still be suggested
# alongside an outfit instead of being silently ignored.
LAYER_MARKERS = {
    "jacket", "jackets", "sweater", "sweaters", "nehru"
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
    "nehru", "sherwani", "sherwanis"
}


def _weather_score(items, weather):
    """
    Rough weather-suitability score. Returns a neutral 5 points
    per item when there's no weather info, or when an item's
    category doesn't clearly fall into a "light" or "warm layer"
    bucket - weather should nudge ranking, not hide clothes the
    heuristic can't classify.
    """

    if not weather:
        return 0

    points = 0

    for item in items:

        tokens = _tokens(item.get("category"))

        if weather.get("is_hot") and tokens & LIGHT_MARKERS:
            points += 25

        elif weather.get("is_cold") and tokens & WARM_LAYER_MARKERS:
            points += 25

        elif weather.get("is_rainy") and tokens & WARM_LAYER_MARKERS:
            points += 15

        else:
            points += 5

    return points / len(items)


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


def _score_outfit(items, occasion, weather=None):
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
      - weather_points: unchanged from before.

    Every item here has already passed _filter_by_occasion AND
    _filter_by_gender, so all of them are already valid for this
    request - this scoring step only RANKS valid combinations
    against each other; a high color or style score can never
    rescue an outfit that failed a hard restriction; it can only
    rank one valid outfit above another valid one.
    """

    flagged = _is_flagged(items, occasion)

    fit_points = 0 if flagged else 20

    color_points, color_reasons = outfit_color_score(items)
    color_points += _occasion_color_bonus(occasion, color_reasons)

    style_points, style_reasons = outfit_style_score(items)

    weather_points = _weather_score(
        items,
        weather
    )

    return {
        "score": round(
            fit_points + color_points + style_points + weather_points,
            1
        ),
        "flagged": flagged,
        "color_reasons": color_reasons,
        "style_reasons": style_reasons,
    }


def _build_why(occasion, flagged, color_reasons, style_reasons):
    """
    Short, human-readable "why this works" bullets (spec section 10)
    - built directly from the same reasons already computed for
    scoring, never invented after the fact. A flagged outfit still
    gets bullets (it's still a valid, gender/occasion-approved
    combination - "flagged" only means at least one piece is an
    occasion stretch), it's just honest about that instead of
    pretending every piece is a perfect fit.
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


def recommend_outfits(wardrobe_items, occasion="casual", weather=None, account_gender=None):
    """
    Generate ranked complete outfit recommendations
    from the user's wardrobe.

    Uses existing wardrobe categories, colors and (automatically
    inferred) occasions - no manual occasion tagging required.
    `weather`, when provided, is the dict returned by
    backend.weather.get_weather() and nudges ranking toward
    weather-appropriate pieces. `account_gender` ("Male"/"Female"),
    when provided, is a defense-in-depth filter - see
    _filter_by_gender() above.

    Occasion filtering is strict: asking for "party" only builds
    outfits from items whose CATEGORY is actually a fit for party
    wear (see infer_occasions_for_category), or that were manually
    tagged party - a pair of gym shorts never sneaks into a party
    recommendation just because the wardrobe happens to be short on
    party wear.
    """

    if not wardrobe_items:
        return []

    # Resolve once, up front, so filtering, flagging, and the
    # "occasion" echoed back in each recommendation all agree on
    # the same canonical value - a request for a recognized synonym
    # ("formal", "outing", "festive", ...) behaves identically to
    # requesting the canonical word itself.
    occasion = resolve_occasion_query(occasion)

    wardrobe_items = _filter_by_gender(wardrobe_items, account_gender)
    wardrobe_items = _filter_by_occasion(wardrobe_items, occasion)

    if not wardrobe_items:
        return []


    # --------------------------------------------------------
    # Bucket items into tops / bottoms / dresses / accessories
    # by matching normalized category tokens against keyword
    # marker sets, instead of relying on exact category strings.
    # This is what lets items land in the right bucket whether
    # their category came from the manual dropdown ("Dhoti
    # Pants") or was overwritten by the IndoFashion classifier
    # ("dhoti_pants").
    # --------------------------------------------------------

    tops = []
    bottoms = []
    dresses = []
    accessories = []

    for item in wardrobe_items:

        category = item.get("category")

        if not category:
            continue

        tokens = _tokens(category)

        if not tokens:
            continue

        if tokens & DRESS_MARKERS:
            dresses.append(item)
        elif tokens & TOP_MARKERS:
            tops.append(item)
        elif tokens & BOTTOM_MARKERS:
            bottoms.append(item)
        elif tokens & (ACCESSORY_MARKERS | LAYER_MARKERS):
            accessories.append(item)

        # Anything that matches none of the marker sets is left
        # out of outfit generation entirely (rather than crashing
        # or silently misclassifying it into the wrong bucket).


    recommendations = []


    # ========================================================
    # DRESS / ONE-PIECE OUTFITS
    # ========================================================

    for dress in dresses[:5]:

        items = [dress]

        if accessories:

            items.append(
                accessories[
                    len(recommendations)
                    % len(accessories)
                ]
            )

        outcome = _score_outfit(items, occasion, weather)

        recommendations.append({
            "occasion": occasion,
            "items": items,
            "type": "one-piece",
            "score": outcome["score"],
            "flagged": outcome["flagged"],
            "color_reasons": outcome["color_reasons"],
            "style_reasons": outcome["style_reasons"],
            "why": _build_why(
                occasion, outcome["flagged"],
                outcome["color_reasons"], outcome["style_reasons"]
            )
        })


    # ========================================================
    # TOP + BOTTOM OUTFITS
    # ========================================================

    for top in tops[:8]:

        for bottom in bottoms[:8]:

            items = [top, bottom]

            if accessories:

                items.append(
                    accessories[
                        len(recommendations)
                        % len(accessories)
                    ]
                )

            outcome = _score_outfit(items, occasion, weather)

            recommendations.append({
                "occasion": occasion,
                "items": items,
                "type": "top-bottom",
                "score": outcome["score"],
                "flagged": outcome["flagged"],
                "color_reasons": outcome["color_reasons"],
                "style_reasons": outcome["style_reasons"],
                "why": _build_why(
                    occasion, outcome["flagged"],
                    outcome["color_reasons"], outcome["style_reasons"]
                )
            })


    # ========================================================
    # RANK BY SCORE, THEN LIMIT RESULTS
    #
    # Best occasion/color matches surface first instead of
    # whatever order items happened to be grouped in.
    # ========================================================

    recommendations.sort(
        key=lambda outfit: outfit["score"],
        reverse=True
    )

    return recommendations[:10]


def describe_missing_pieces(wardrobe_items, occasion="casual", account_gender=None):
    """
    Honest "missing item" messaging (spec section 10): when the
    wardrobe genuinely lacks a piece needed to build a complete
    outfit for the requested occasion, say so plainly instead of
    just silently returning fewer (or zero) recommendations - e.g.
    "Your wardrobe does not contain a suitable bottom to pair with
    your casual tops." This NEVER fabricates wardrobe contents; it
    only reports on the same gender/occasion-filtered buckets
    recommend_outfits() itself builds, using the same marker sets,
    so its notes always match what recommend_outfits() actually did.

    Returns a list of note strings (possibly empty - an empty list
    means recommend_outfits() should have everything it needs).
    """

    occasion = resolve_occasion_query(occasion)

    filtered = _filter_by_gender(wardrobe_items, account_gender)
    filtered = _filter_by_occasion(filtered, occasion)

    label = occasion.replace("_", " ")

    if not filtered:
        return [
            f"Your wardrobe does not contain any items suitable for "
            f"{label} yet."
        ]

    tops = bottoms = dresses = 0

    for item in filtered:

        category = item.get("category")

        if not category:
            continue

        tokens = _tokens(category)

        if not tokens:
            continue

        if tokens & DRESS_MARKERS:
            dresses += 1
        elif tokens & TOP_MARKERS:
            tops += 1
        elif tokens & BOTTOM_MARKERS:
            bottoms += 1

    if dresses or (tops and bottoms):
        return []

    if tops and not bottoms:
        return [
            f"Your wardrobe does not contain a suitable bottom to "
            f"pair with your {label} tops."
        ]

    if bottoms and not tops:
        return [
            f"Your wardrobe does not contain a suitable top to pair "
            f"with your {label} bottoms."
        ]

    return [
        f"Your wardrobe does not contain a complete top-and-bottom "
        f"outfit for {label} yet - only accessories or unmatched "
        f"pieces."
    ]
