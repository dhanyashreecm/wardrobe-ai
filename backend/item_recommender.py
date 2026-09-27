"""
SINGLE-ITEM RECOMMENDATIONS for one wardrobe category
("Tops for College", "Shoes for Party", "Sarees for Wedding").

Why this exists: the category tabs on the recommendations page used to
filter the OUTFIT list in the browser, so "Shoes" just showed every
outfit that happened to include a pair of shoes. Now the tab is sent to
the backend and this module ranks the user's own items of that one
category.

Pipeline (hard rules first, then scoring - a high colour or weather
score can never bring back an excluded item):

  1. category  - the item's NORMALISED group (outfit_presentation.
                 item_group, built on the garment-kind taxonomy - never
                 raw string matching) must equal the requested tab
  2. gender    - never the other gender's clothes
  3. occasion  - the item must suit the occasion (garments: category ->
                 occasion table; shoes/accessories: rules below)
  4. weather   - no coats/boots/wool in hot weather, no shorts in cold
  5. style     - if a style is chosen, the item must have that style
  6. colour    - if a colour is chosen, the item must match it or go
                 well with it (colour-harmony score)
  then SCORE: occasion fit, colour, weather, style, recent wear.

Every "why" line is produced from a score that was actually computed.
Set RECO_DEBUG=1 to log why each item was included or excluded.
"""
import os
from datetime import datetime

from backend import outfit_builder as ob
from backend import outfit_assignment
from backend import outfit_presentation as present
from backend.category_gender import is_allowed_for_account
from backend.color_theory import classify_color, color_harmony
from backend.occasion_model import occasion_fit, MAX_OCCASION_POINTS

GROUPS = ["Tops", "Bottoms", "Dresses", "Sarees", "Ethnic",
          "Outerwear", "Shoes", "Accessories"]

DEBUG = os.environ.get("RECO_DEBUG", "").strip() not in ("", "0", "false")

SPORTY_SHOE_WORDS = ob.SPORTY_SHOE_WORDS | {"flip", "slides", "crocs"}
DRESSY_SHOE_WORDS = ob.DRESSY_SHOE_WORDS
FORMAL_OCCASIONS = {"office", "interview"}
ETHNIC_OCCASIONS = {"wedding", "traditional"}


def _log(message):
    if DEBUG:
        print(f"[reco] {message}")


# ------------------------------------------------------------
# Occasion rules for shoes and accessories (garments use the
# category -> occasion table in outfit_recommendation)
# ------------------------------------------------------------

def footwear_suits(item, occasion):
    kind = ob.kind_for(item.get("category"))
    words = ob._tokens(item.get("category"))
    sporty = bool(words & SPORTY_SHOE_WORDS)
    dressy = bool(words & DRESSY_SHOE_WORDS)
    if occasion == "sports":
        # Only real sports shoes, or a plain "Footwear"/"Shoes" entry.
        return kind == "footwear" and (sporty or words <= {"footwear", "shoe", "shoes"})
    if occasion in ETHNIC_OCCASIONS:
        return not sporty and kind != "boots"
    if occasion in FORMAL_OCCASIONS:
        return not sporty and kind != "mojari" and not (words & {"flip", "slides"})
    if occasion == "party":
        return not sporty and not (words & {"flip", "slides", "crocs"})
    if occasion == "date":
        return not (words & {"flip", "slides", "crocs"})
    return True


def accessory_suits(item, occasion):
    kind = ob.kind_for(item.get("category"))
    if occasion == "sports":
        return kind == "watch"
    if kind == "head":
        return occasion in ("wedding", "traditional", "party")
    if kind == "dupatta":
        return occasion in ("wedding", "traditional", "party", "casual", "day_outing", "college", "office")
    if kind == "belt":
        return occasion not in ETHNIC_OCCASIONS
    return True


def item_suits_occasion(item, occasion, effective_occasions):
    role = ob.role_for(item.get("category"))
    if role == ob.FOOTWEAR:
        return footwear_suits(item, occasion)
    if role == ob.ACCESSORY:
        return accessory_suits(item, occasion)
    if role == ob.HIDDEN:
        return False
    return occasion in effective_occasions(item.get("category"), item.get("occasion"))


# ------------------------------------------------------------
# Weather
# ------------------------------------------------------------

WARM_WORDS = {"wool", "woolen", "woollen", "fleece", "thermal", "fur", "down",
              "puffer", "sweater", "hoodie", "cardigan", "coat"}


def weather_check(item, weather):
    """Returns (allowed, score 0-1, reason or None)."""
    if not weather:
        return True, 0.5, None
    kind = ob.kind_for(item.get("category"))
    words = ob._tokens(f"{item.get('category', '')} {item.get('material', '')}")
    warm = bool(words & WARM_WORDS) or kind in ("coat", "boots")
    if weather.get("is_hot"):
        if warm:
            return False, 0.0, None
        if kind in ("tshirt", "shorts", "skirt", "dress", "kurta", "kurta_women",
                    "kurta_men", "palazzo", "saree", "footwear"):
            return True, 1.0, "light and breathable for today's heat"
        return True, 0.6, None
    if weather.get("is_cold"):
        if kind == "shorts" or (kind == "footwear" and words & {"flip", "sandal", "sandals", "slides"}):
            return False, 0.0, None
        if warm or kind in ("jacket", "blazer", "nehru"):
            return True, 1.0, "keeps you warm today"
        return True, 0.5, None
    if weather.get("is_rainy"):
        if kind == "footwear" and words & {"suede", "canvas", "sandal", "sandals"}:
            return True, 0.2, None
        if kind in ("boots", "jacket", "coat"):
            return True, 1.0, "good cover for the rain"
    return True, 0.6, None


# ------------------------------------------------------------
# Style
# ------------------------------------------------------------

def item_style_tags(item):
    kind = ob.kind_for(item.get("category"))
    label = present.item_style_label(item)
    words = ob._tokens(item.get("category"))
    tags = set()
    if kind in ob.ETHNIC_KINDS or kind in ("mojari", "dupatta", "nehru"):
        tags.add("Ethnic")
    if label == "Casual" or kind in ("tshirt", "shorts", "jeans") or words & SPORTY_SHOE_WORDS:
        tags.add("Casual")
    if label in ("Smart", "Formal") and kind not in ("tshirt", "shorts"):
        tags.add("Smart")
    if label == "Formal" or kind in ("blazer",) or (kind in ("shirt", "pant") and label != "Casual"):
        tags.add("Formal")
    if label == "Festive" or kind in ("dress", "gown", "skirt", "lehenga") or words & DRESSY_SHOE_WORDS:
        tags.add("Party")
    if not tags:
        tags.add("Smart")
    return tags


# ------------------------------------------------------------
# Colour
# ------------------------------------------------------------

def colour_check(item, colour):
    """Returns (allowed, score 0-1, reason or None)."""
    item_colour = (item.get("color") or "").strip().lower()
    if not colour:
        return True, 0.5, None
    wanted = colour.strip().lower()
    if wanted in item_colour:
        return True, 1.0, f"matches your chosen colour ({wanted})"
    info_w, info_i = classify_color(wanted), classify_color(item_colour)
    if (info_w.get("recognized") and info_i.get("recognized")
            and not info_w.get("neutral") and info_w.get("family") == info_i.get("family")):
        return True, 0.9, f"same colour family as {wanted}"
    score, reason = color_harmony(wanted, item_colour) if item_colour else (0, "")
    if score >= 20:
        return True, score / 25, f"goes well with {wanted} ({reason})"
    return False, 0.0, None


# ------------------------------------------------------------
# Main entry point
# ------------------------------------------------------------

def recommend_items(wardrobe_items, occasion, group, account_gender=None,
                    weather=None, colour=None, style=None,
                    wear_history=None, limit=12, notes=None, debug=False,
                    effective_occasions=None, now=None):
    from backend.outfit_recommendation import (
        effective_occasions as default_effective, resolve_occasion_query,
    )
    effective_occasions = effective_occasions or default_effective
    notes = notes if notes is not None else []
    occasion = resolve_occasion_query(occasion)
    now = now or datetime.utcnow()
    label = present.occasion_label(occasion)

    last_worn = {}
    for entry in wear_history or []:
        for worn_id in entry.get("item_ids") or []:
            when = entry.get("worn_at")
            if when and (worn_id not in last_worn or when > last_worn[worn_id]):
                last_worn[worn_id] = when

    kind_weights = outfit_assignment.OCCASION_KIND_WEIGHT.get(occasion, {})
    results = []
    in_group = 0

    for item in wardrobe_items:
        name = present.display_name(item)
        item_group = present.item_group(item)
        if item_group != group or ob.role_for(item.get("category")) == ob.HIDDEN:
            continue
        in_group += 1
        if not is_allowed_for_account(item.get("category"), account_gender):
            _log(f"EXCLUDE {name}: other gender")
            continue
        if not item_suits_occasion(item, occasion, effective_occasions):
            _log(f"EXCLUDE {name}: not suitable for {occasion}")
            continue
        ok_w, weather_score, weather_reason = weather_check(item, weather)
        if not ok_w:
            _log(f"EXCLUDE {name}: wrong for the weather")
            continue
        tags = item_style_tags(item)
        if style and style.title() not in tags:
            _log(f"EXCLUDE {name}: style {sorted(tags)} != {style}")
            continue
        ok_c, colour_score, colour_reason = colour_check(item, colour)
        if not ok_c:
            _log(f"EXCLUDE {name}: colour doesn't match {colour}")
            continue

        kind = ob.kind_for(item.get("category"))
        usage_points, _ = occasion_fit([item], occasion)
        occasion_score = min(1.0, 0.6 * (usage_points / MAX_OCCASION_POINTS)
                             + 0.4 * (kind_weights.get(kind, 0) / 8)
                             + 0.15 * min(1, outfit_assignment.colour_weight(occasion, [item]) / 3))
        style_score = 1.0 if style else 0.5

        history_penalty, history_reason = 0.0, None
        worn = last_worn.get(str(item.get("_id")))
        if worn:
            days = (now - worn).total_seconds() / 86400
            if days <= 2:
                history_penalty, history_reason = 0.25, "you wore this very recently"
            elif days <= 7:
                history_penalty, history_reason = 0.1, "you wore this earlier this week"

        final = round(0.45 * occasion_score + 0.2 * colour_score + 0.2 * weather_score
                      + 0.15 * style_score - history_penalty, 3)

        why = []
        if occasion_score >= 0.5:
            why.append(f"Typical for {label.lower()}.")
        else:
            why.append(f"Suitable for {label.lower()}.")
        if style:
            why.append(f"Fits your {style.lower()} style.")
        if colour_reason:
            why.append(colour_reason[0].upper() + colour_reason[1:] + ".")
        if weather_reason:
            why.append(f"Weather: {weather_reason}.")
        if history_reason:
            why.append(f"Note: {history_reason}.")
        elif wear_history:
            why.append("Not worn this week.")
        why.append("From your own wardrobe.")

        breakdown = {"occasion": round(occasion_score, 2), "colour": round(colour_score, 2),
                     "weather": round(weather_score, 2), "style": round(style_score, 2),
                     "history_penalty": history_penalty, "final": final}
        _log(f"INCLUDE {name} [{item_group}] {breakdown}")

        entry = {
            "type": "single",
            "group": item_group,
            "occasion": occasion,
            "item": present.present_item(item),
            "title": name,
            "style_tags": sorted(tags),
            "score": final,
            "why": why,
        }
        if debug:
            entry["breakdown"] = breakdown
        results.append(entry)

    results.sort(key=lambda r: -r["score"])

    if not results:
        plural = group.lower()
        if in_group == 0:
            notes.append(f"You don't have any {plural} in your wardrobe yet.")
        else:
            notes.append(f"No suitable {plural} found for {label.lower()}"
                         + (" with these filters" if (style or colour or weather) else "") + ".")
            notes.append(f"Try another occasion or filter, or add more {plural} to your wardrobe.")
    return results[:limit]
