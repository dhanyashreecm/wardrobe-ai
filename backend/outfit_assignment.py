"""
KEEPING OCCASIONS AND ACTIVITIES DIFFERENT FROM EACH OTHER

The problem this solves: a t-shirt + jeans is a perfectly valid outfit
for casual, college, day outing AND date. When each occasion simply
showed "every valid outfit, best first", those four occasions showed
the same outfits in almost the same order.

The fix has two parts:

1. OCCASION / ACTIVITY FIT - explicit tables of which garment kinds are
   most typical for each occasion (jeans for college, shorts for a day
   out, a shirt and trousers for office...) and each activity.

2. A DRAFT - like picking teams. Occasions take turns choosing their
   best remaining outfit until every outfit has exactly one "home"
   occasion. The occasion with the fewest options picks first each
   round, so scarce occasions (interview, wedding) are never starved
   by broad ones (casual). An outfit is preferred by the occasion it is
   MOST specific to, not just any occasion it happens to be valid for.

The result: each outfit is shown under one occasion only, and every
occasion that has suitable clothes still gets its fair share.
"""

from backend import outfit_builder as ob


# ------------------------------------------------------------
# How typical each garment kind is for each occasion (0-8).
# Added up over an outfit's main garments.
# ------------------------------------------------------------
OCCASION_KIND_WEIGHT = {
    "casual": {"tshirt": 6, "shorts": 6, "jeans": 4, "palazzo": 4,
               "salwar": 3, "kurta_women": 3, "kurta": 3, "dress": 2},
    "college": {"jeans": 6, "tshirt": 4, "shirt": 4, "kurta_women": 5,
                "kurta_men": 4, "kurta": 4, "salwar": 4, "pant": 1},
    "day_outing": {"skirt": 6, "dress": 6, "shorts": 5, "palazzo": 4,
                   "tshirt": 3},
    "date": {"dress": 6, "shirt": 5, "skirt": 5, "jeans": 3, "gown": 3},
    "office": {"pant": 7, "shirt": 6, "kurta_women": 5, "kurta_men": 4,
               "kurta": 4, "palazzo": 4, "saree": 4, "salwar": 3},
    "interview": {"shirt": 7, "pant": 7},
    "party": {"gown": 7, "dress": 7, "skirt": 5, "anarkali": 4,
              "jeans": 2},
    "wedding": {"lehenga": 8, "sherwani": 8, "saree": 6, "anarkali": 6,
                "gown": 5, "dhoti": 4},
    "sports": {"tshirt": 6, "shorts": 6, "salwar": 3, "pant": 2},
    "traditional": {"dhoti": 6, "kurta_men": 5, "kurta": 5,
                    "kurta_women": 5, "salwar": 5, "saree": 5,
                    "anarkali": 5, "palazzo": 3},
}


# ------------------------------------------------------------
# Colour as an occasion signal: a black or wine dress reads "party",
# the same dress in white or pastel reads "day out". Points per main
# garment whose colour word contains one of these.
# ------------------------------------------------------------
OCCASION_COLOUR_WEIGHT = {
    "party": ({"black", "wine", "maroon", "burgundy", "gold", "silver",
               "red", "emerald", "sequin", "metallic", "navy"}, 4),
    "date": ({"red", "black", "wine", "pink", "maroon", "burgundy"}, 3),
    "day_outing": ({"white", "cream", "yellow", "light", "pastel", "mint",
                    "peach", "sky", "floral", "beige"}, 3),
    "casual": ({"white", "denim", "blue", "grey", "gray", "beige"}, 2),
    "college": ({"denim", "blue", "white", "grey", "gray"}, 2),
    "office": ({"white", "navy", "grey", "gray", "beige", "black", "light blue"}, 2),
    "interview": ({"white", "navy", "grey", "gray", "beige", "light blue"}, 3),
    "wedding": ({"red", "gold", "pink", "maroon", "green", "orange", "yellow"}, 2),
    "traditional": ({"red", "gold", "green", "yellow", "orange", "pink"}, 2),
}


def colour_weight(occasion, items):
    words, points = OCCASION_COLOUR_WEIGHT.get(occasion, (set(), 0))
    total = 0
    for item in items:
        colour = (item.get("color") or "").lower()
        if any(word in colour for word in words):
            total += points
    return total


# ------------------------------------------------------------
# ACTIVITIES - unlike before, these are real filters now.
#   core:      garment kinds allowed as the main outfit
#   layer / footwear / accessory: what may be added on top
#   weight:    how typical each kind is (for the activity draft)
# ------------------------------------------------------------
ACTIVITY_RULES = {
    "sports": {
        "label": "sports / workout",
        "core": {"tshirt", "shorts", "pant", "salwar"},
        "layer": {"jacket"},
        "footwear": {"footwear"},
        "accessory": {"watch"},
        "weight": {"tshirt": 6, "shorts": 6, "salwar": 4, "pant": 2},
    },
    "outdoor": {
        "label": "outdoor",
        "core": {"tshirt", "shirt", "jeans", "pant", "shorts",
                 "kurta", "kurta_men", "kurta_women", "salwar"},
        "layer": {"jacket", "coat"},
        "footwear": {"boots", "footwear"},
        "accessory": {"bag", "watch"},
        "weight": {"jeans": 5, "pant": 4, "shirt": 3, "tshirt": 2,
                   "shorts": 2},
    },
    "travel": {
        "label": "travel",
        "core": {"tshirt", "shirt", "jeans", "pant", "shorts", "dress",
                 "skirt", "kurta", "kurta_men", "kurta_women", "salwar",
                 "palazzo"},
        "layer": {"jacket", "coat"},
        "footwear": {"footwear", "boots"},
        "accessory": {"bag", "watch"},
        "weight": {"tshirt": 5, "palazzo": 5, "kurta_women": 4,
                   "kurta": 4, "dress": 4, "salwar": 3, "jeans": 2},
    },
    "formal_event": {
        "label": "formal event",
        "core": {"shirt", "pant", "saree", "lehenga", "sherwani", "gown",
                 "dress", "anarkali", "kurta", "kurta_men", "kurta_women",
                 "dhoti", "salwar", "palazzo", "blouse", "skirt"},
        "layer": {"blazer", "nehru", "coat"},
        "footwear": {"footwear", "mojari"},
        "accessory": None,  # anything suitable
        "weight": {"sherwani": 7, "lehenga": 7, "saree": 6, "gown": 6,
                   "pant": 5, "shirt": 5, "anarkali": 5, "dhoti": 4},
    },
}


def resolve_activity(activity):
    activity = (activity or "").strip().lower()
    return activity if activity in ACTIVITY_RULES else None


def activity_allows_core(core_kinds, activity):
    if not activity:
        return True
    allowed = ACTIVITY_RULES[activity]["core"]
    return all(kind in allowed for kind in core_kinds)


def activity_allows_extra(role, kind, activity):
    """May this layer/footwear/accessory be added for the activity?"""
    if not activity:
        return True
    allowed = ACTIVITY_RULES[activity].get(role)
    return allowed is None or kind in allowed


def eligible_activities(core_kinds):
    return {
        name for name in ACTIVITY_RULES
        if activity_allows_core(core_kinds, name)
    }


def kind_weight(table, core_kinds):
    return sum(table.get(kind, 0) for kind in core_kinds)


def draft(candidates, contexts, specificity=0.5):
    """
    Gives every candidate exactly one context (occasion or activity).

    candidates: {key: {"eligible": set_of_contexts, "fit": {context: number}}}
    contexts:   list of context names, in a fixed order (tie-breaker)

    Each round, contexts take turns (fewest remaining options first)
    choosing the remaining candidate that is most SPECIFIC to them:
    its fit here minus `specificity` x its best fit anywhere else.
    Returns {key: context}.
    """
    remaining = set(candidates)
    assigned = {}

    def options(context):
        return [key for key in remaining
                if context in candidates[key]["eligible"]]

    while remaining:
        progress = False
        order = sorted(
            contexts,
            key=lambda c: (len(options(c)), contexts.index(c)),
        )
        for context in order:
            choices = options(context)
            if not choices:
                continue

            def preference(key):
                fit = candidates[key]["fit"]
                elsewhere = [
                    fit.get(other, 0)
                    for other in candidates[key]["eligible"]
                    if other != context
                ]
                best_elsewhere = max(elsewhere) if elsewhere else 0
                here = fit.get(context, 0)
                # key reversed as the final tie-breaker keeps it stable
                return (here - specificity * best_elsewhere, here, key)

            best = max(choices, key=preference)
            assigned[best] = context
            remaining.discard(best)
            progress = True

        if not progress:
            break

    return assigned
