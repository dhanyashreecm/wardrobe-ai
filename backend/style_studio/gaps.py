"""
"What should I shop for?" - the smallest useful purchase.

Order of thinking (never reversed): the wardrobe first. For each
candidate staple we ADD A VIRTUAL COPY to an in-memory list (never to
the database), ask the existing engine which complete outfits become
possible, and count the new ones per occasion. The piece that unlocks
the most - plus any trends it completes - wins. If nothing unlocks a
meaningful number of outfits, the answer is "No purchase needed".

Virtual items have ids starting "virtual:" and are never saved, never
shown as owned, and never mixed into another user's data.
"""
from backend import shopping_links
from backend.category_gender import is_allowed_for_account
from backend.color_theory import classify_color
from backend.outfit_recommendation import effective_occasions, recommend_outfits
from backend.style_studio import recipes
from backend.style_studio.engine import ALL_OCCASIONS, OCCASION_LABEL

STAPLES = {
    "female": [
        ("Wide-Leg Pants", "beige"), ("Jeans", "blue"), ("Top", "white"), ("Shirt", "white"),
        ("Blazer", "black"), ("Skirt", "black"), ("Dress", "black"), ("Sneakers", "white"),
        ("Heels", "beige"), ("Flats", "tan"), ("Cardigan", "cream"), ("Handbag", "tan"),
        ("Kurta (Women)", "white"), ("Palazzos", "white"), ("Kurta Set (Women)", "sage"),
        ("Mojaris (Women)", "gold"), ("Saree", "emerald"), ("Earrings", "gold"),
    ],
    "male": [
        ("Chinos", "beige"), ("Jeans", "blue"), ("T-Shirt", "white"), ("Formal Shirt", "white"),
        ("Casual Shirt", "sky"), ("Blazer", "navy"), ("Formal Trousers", "grey"),
        ("Sneakers", "white"), ("Loafers", "brown"), ("Formal Shoes", "black"),
        ("Cardigan", "navy"), ("Kurta (Men)", "ivory"), ("Pajama", "white"),
        ("Nehru Jacket", "maroon"), ("Mojaris (Men)", "gold"), ("Watch", "silver"),
    ],
}
MIN_USEFUL = 3      # fewer new outfits than this isn't worth buying for
MAX_CANDIDATES = 14


def _already_owned(category, colour, items):
    want_kind = recipes.kind({"category": category})
    want = classify_color(colour)
    for item in items:
        if recipes.kind(item) != want_kind:
            continue
        have = classify_color(item.get("color"))
        if have.get("family") == want.get("family") and have.get("neutral") == want.get("neutral"):
            return True
    return False


def _virtual(category, colour, gender, n):
    return {"_id": f"virtual:{n}", "category": category, "color": colour,
            "image_path": None, "gender": gender, "virtual": True}


def _keys(items, gender, occasion, history, feedback, now):
    outfits = recommend_outfits(items, occasion, account_gender=gender, limit=60,
                                wear_history=history, feedback=feedback, now=now)
    return {o["outfit_key"]: o for o in outfits}


def analyse(ctx):
    g = ctx.gender
    candidates = []
    seen = set()
    for t in ctx.trends:          # trend gaps first: they also unlock a trend
        if t.get("inspiration_only"):
            continue
        for slot in recipes.missing_slots(t["recipe"], ctx.items):
            buy = slot.get("buy")
            if buy and (buy["category"], buy["color"]) not in seen:
                seen.add((buy["category"], buy["color"]))
                candidates.append((buy["category"], buy["color"]))
    for staple in STAPLES.get(g, []):
        if staple not in seen:
            seen.add(staple)
            candidates.append(staple)
    candidates = [c for c in candidates
                  if is_allowed_for_account(c[0], g) and not _already_owned(c[0], c[1], ctx.items)]
    candidates = candidates[:MAX_CANDIDATES]

    base = {}
    results = []
    for n, (category, colour) in enumerate(candidates):
        virtual = _virtual(category, colour, g, n)
        occasions = [o for o in effective_occasions(category) if o in ALL_OCCASIONS] or ["casual"]
        augmented = ctx.items + [virtual]
        unlocked, partners = {}, {}
        for occasion in occasions:
            if occasion not in base:
                base[occasion] = _keys(ctx.items, g, occasion, ctx.wear_history, ctx.feedback, ctx.now)
            after = _keys(augmented, g, occasion, ctx.wear_history, ctx.feedback, ctx.now)
            new = [o for key, o in after.items()
                   if key not in base[occasion] and any(i.get("_id") == virtual["_id"] for i in o["items"])]
            if new:
                unlocked[occasion] = len(new)
                for outfit in new:
                    for item in outfit["items"]:
                        if not item.get("virtual"):
                            partners[str(item["_id"])] = item
        trends_done = []
        for t in ctx.trends:
            if t.get("inspiration_only"):
                continue
            missing = recipes.missing_slots(t["recipe"], ctx.items)
            if missing and not recipes.missing_slots(t["recipe"], augmented):
                trends_done.append(t["name"])
        total = sum(unlocked.values())
        if total == 0:
            continue
        results.append({
            "category": category, "color": colour,
            "name": f"{colour.title()} {category}",
            "unlocks_total": total,
            "unlocks": [{"occasion": OCCASION_LABEL.get(o, o), "count": c}
                        for o, c in sorted(unlocked.items(), key=lambda kv: -kv[1])],
            "works_with": [{"_id": i_id, "display_name": item.get("category"), "color": item.get("color"),
                            "image_path": item.get("image_path")}
                           for i_id, item in list(partners.items())[:8]],
            "works_with_count": len(partners),
            "trends": trends_done,
            "score": total + 3 * len(trends_done),
        })
    results.sort(key=lambda r: r["score"], reverse=True)
    useful = [r for r in results if r["unlocks_total"] >= MIN_USEFUL or r["trends"]]
    for r in useful:
        r["why"] = (f"Works with {r['works_with_count']} piece{'s' if r['works_with_count'] != 1 else ''} you already own "
                    f"and unlocks {r['unlocks_total']} new outfit{'s' if r['unlocks_total'] != 1 else ''}.")
        r["shop"] = shopping_links.shopping_payload(category=r["category"], color=r["color"], gender=g)
    if not useful:
        return {"no_purchase_needed": True,
                "message": "No purchase needed - your wardrobe already covers your occasions well. Style what you have!",
                "gaps": []}
    return {"no_purchase_needed": False, "top": useful[0], "gaps": useful[:3],
            "message": "You are missing one versatile piece." if len(useful) == 1 else
                       "A few versatile pieces would add the most outfits."}
