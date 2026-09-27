"""
Glue between the recommendation engine and the API routes:

  * finalize()      - Colour/Style filters, FINAL VALIDATION, titles,
                      style tags and inspiration for every outfit
  * build_home()    - the Home page, built only from the user's data
  * trip_looks()    - named looks for a trip (Sightseeing, Evening
                      Dinner...) using the destination's weather
"""
from datetime import datetime

from backend import outfit_presentation as present
from backend.outfit_recommendation import recommend_outfits

ENGINE_POOL = 40      # ask the engine for more, then filter/validate
PAGE_SIZE = 12


def finalize(recommendations, wardrobe_items, account_gender, occasion,
             colour=None, style=None, limit=PAGE_SIZE, notes=None,
             require_full=False):
    notes = notes if notes is not None else []
    by_id = {str(item.get("_id")): item for item in wardrobe_items}

    kept, rejected = [], 0
    used_titles = set()
    for outfit in recommendations:
        ok, reason = present.validate_outfit(outfit, by_id, account_gender, occasion)
        if not ok:
            rejected += 1
            print(f"[validator] rejected outfit {outfit.get('outfit_key')}: {reason}")
            continue
        if not present.matches_colour(outfit, colour):
            continue
        if not present.matches_style(outfit, style):
            continue
        # "Full Looks" = a complete outfit INCLUDING shoes. Never padded
        # with made-up pieces: if no suitable shoes exist, it isn't shown.
        if require_full and "footwear" not in outfit.get("roles", {}).values():
            continue

        outfit = dict(outfit)
        outfit["items"] = [present.present_item(item) for item in outfit["items"]]
        outfit["title"] = present.outfit_title(outfit, taken=used_titles)
        used_titles.add(outfit["title"])
        outfit["style_tags"] = present.style_tags(outfit)
        outfit["colours"] = [item.get("color") for item in outfit["items"] if item.get("color")]
        outfit["inspiration"] = present.inspiration(outfit, account_gender)
        outfit["why"] = list(outfit.get("why", [])) + ["Uses only pieces from your wardrobe."]
        kept.append(outfit)

    if require_full and recommendations and not kept:
        notes.append(
            "No complete looks for this occasion yet - your outfits here have "
            "no matching shoes. Add footwear that suits "
            f"{present.occasion_label(occasion).lower()} to see full looks."
        )
    elif recommendations and not kept and (colour or style):
        notes.append(
            "None of your outfits for this occasion match the chosen "
            + " and ".join(filter(None, [colour and f"colour ({colour})",
                                         style and f"style ({style})"]))
            + ". Try another filter."
        )
    return kept[:limit], notes


EDITS = [
    {"key": "weekend", "title": "Weekend Edit", "icon": "☀️",
     "subtitle": "Casual outfits for day outings", "occasion": "day_outing"},
    {"key": "after_dark", "title": "After Dark", "icon": "🌙",
     "subtitle": "Date night / party pieces", "occasion": "party"},
    {"key": "festive", "title": "Festive Edit", "icon": "🌸",
     "subtitle": "Sarees, ethnic wear & occasion pieces", "occasion": "traditional"},
    {"key": "campus", "title": "Campus Edit", "icon": "🎓",
     "subtitle": "College-friendly combinations", "occasion": "college"},
]


def build_home(wardrobe_items, account_gender, profile=None, weather=None,
               wear_history=None, feedback=None):
    items = [present.present_item(item) for item in wardrobe_items]

    def created(item):
        value = item.get("created_at")
        return value if isinstance(value, datetime) else datetime.min

    recent = sorted(items, key=created, reverse=True)[:8]
    favourites = [item for item in items if item.get("favorite")][:8]

    groups = {}
    for item in items:
        groups[item["group"]] = groups.get(item["group"], 0) + 1

    edits = []
    for edit in EDITS:
        outfits = recommend_outfits(
            wardrobe_items, edit["occasion"], weather=weather,
            account_gender=account_gender, limit=ENGINE_POOL,
            wear_history=wear_history, feedback=feedback, exclusive=True,
        )
        outfits, _ = finalize(outfits, wardrobe_items, account_gender,
                              edit["occasion"], limit=4)
        cover = outfits[0]["items"][0] if outfits else None
        edits.append({**edit, "count": len(outfits), "outfits": outfits,
                      "cover_image": cover.get("image_path") if cover else None})

    top_pick = next((edit["outfits"][0] for edit in edits if edit["outfits"]), None)

    return {
        "name": (profile or {}).get("name"),
        "gender": account_gender,
        "item_count": len(items),
        "group_counts": groups,
        "recent": recent,
        "favourites": favourites,
        "edits": edits,
        "top_pick": top_pick,
        "weather": weather,
        "city": (profile or {}).get("city"),
    }


TRIP_MOMENTS = [
    {"title": "Sightseeing", "occasion": "day_outing", "activity": "outdoor"},
    {"title": "Relaxed Day", "occasion": "casual", "activity": None},
    {"title": "Evening Dinner", "occasion": "date", "activity": None},
    {"title": "Night Out", "occasion": "party", "activity": None},
]


def trip_looks(wardrobe_items, account_gender, weather=None):
    """One named look per trip moment, never repeating main pieces."""
    looks, used = [], set()
    for moment in TRIP_MOMENTS:
        outfits = recommend_outfits(
            wardrobe_items, moment["occasion"], weather=weather,
            account_gender=account_gender, activity=moment["activity"],
            limit=ENGINE_POOL,
        )
        outfits, _ = finalize(outfits, wardrobe_items, account_gender,
                              moment["occasion"], limit=ENGINE_POOL)
        for outfit in outfits:
            if not used & set(outfit.get("key_item_ids", [])):
                used |= set(outfit.get("key_item_ids", []))
                looks.append({**outfit, "title": moment["title"]})
                break
    return looks
