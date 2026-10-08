"""
Outfit Studio engine: alternatives, wardrobe ideas, trend status.

Every outfit comes from the EXISTING engine
(outfit_recommendation.recommend_outfits) and passes the existing final
validator (recommend_service.finalize), so all of the app's rules hold:
gender, occasion, ethnic and western never mixed, sensible footwear
(no sneakers with a saree), colour harmony, only real wardrobe pieces
with their real (Cloudinary) images. This module only CHOOSES among
those outfits and EXPLAINS them.
"""
from datetime import datetime, timedelta

from backend import outfit_presentation as present
from backend import recommend_service
from backend.category_catalog import normalize_gender
from backend.category_gender import is_allowed_for_account
from backend.outfit_recommendation import recommend_outfits, resolve_occasion_query
from backend.style_studio import naming, recipes, trends as trend_lib

OCCASIONS = [
    ("casual", "Casual"), ("college", "College"), ("office", "Formal / Office"),
    ("interview", "Interview"), ("day_outing", "Day Outing"), ("date", "Date Night"),
    ("party", "Party"), ("wedding", "Wedding"), ("traditional", "Traditional / Festive"),
]
OCCASION_LABEL = dict(OCCASIONS)
ALL_OCCASIONS = [key for key, _ in OCCASIONS]
REPEAT_DAYS = 14          # an exact outfit worn this recently isn't suggested again
ENGINE_POOL = 40

COLOUR_REASON_TEXT = {
    "neutral balancing": "the neutral palette keeps it clean and balanced",
    "monochromatic": "staying in one colour family makes it look intentional",
    "complementary colors": "opposite colours on the colour wheel make each other pop",
    "analogous colors": "neighbouring colours blend smoothly",
    "triadic-adjacent colors": "a bold three-colour mix that still feels planned",
    "same color": "one colour head-to-toe gives a long, elegant line",
}

TIPS = {
    "festive_grace": "Let one piece of jewellery shine - jhumkas or a statement necklace, not both.",
    "modern_heritage": "Keep jewellery simple if the outfit has embroidery; add colour with footwear.",
    "soft_heritage": "Pastels love light gold or pearl jewellery and nude or metallic footwear.",
    "midnight": "Add one shine - metallic jewellery or a glossy shoe - to lift the dark palette.",
    "quiet_luxury": "Fit is everything here: sleeves at the wrist, trousers just touching the shoe.",
    "modern_minimal": "Keep accessories to one or two clean pieces so the shapes stay sharp.",
    "city_rose": "Balance the colour with neutral shoes and a simple bag.",
    "golden_hour": "Warm tones glow with gold jewellery and tan or brown accessories.",
    "contemporary_muse": "A belt or a structured bag gives a simple dress shape and polish.",
    "urban_classic": "Roll the sleeves or cuff the denim once for an easy, styled finish.",
    "colour_pop": "Let the bright piece lead; keep everything else quiet.",
    "weekend_ease": "Tuck the front of the top in loosely to give the outfit a waist.",
    "sport_luxe": "Clean white sneakers make sporty pieces look deliberate.",
}


def _now():
    return datetime.utcnow()


def _days_ago(moment, now):
    if not moment:
        return None
    return max(0, (now - moment).days)


class Context:
    """Everything one request needs, computed once."""

    def __init__(self, user_email, wardrobe_items, gender, wear_history=None,
                 feedback=None, now=None):
        self.user_email = user_email
        self.gender = normalize_gender(gender)
        self.all_items = list(wardrobe_items or [])
        # Only pieces this account can wear (defence in depth - the
        # engine filters again).
        self.items = [i for i in self.all_items
                      if is_allowed_for_account(i.get("category"), self.gender)]
        self.wear_history = list(wear_history or [])
        self.feedback = feedback or {}
        self.now = now or _now()
        self._by_occasion = {}
        self.last_worn = {}
        self.outfit_worn = {}
        for entry in self.wear_history:
            when = entry.get("worn_at")
            for item_id in entry.get("item_ids") or []:
                if when and (item_id not in self.last_worn or when > self.last_worn[item_id]):
                    self.last_worn[item_id] = when
            key = entry.get("outfit_key")
            if key and when and (key not in self.outfit_worn or when > self.outfit_worn[key]):
                self.outfit_worn[key] = when
        self.trends, self.live_status = trend_lib.trends_for(self.gender, self.now)

    # ---------------- raw outfits ----------------

    def outfits_for(self, occasion):
        occasion = resolve_occasion_query(occasion)
        if occasion not in self._by_occasion:
            raw = recommend_outfits(
                self.all_items, occasion, account_gender=self.gender, limit=ENGINE_POOL,
                wear_history=self.wear_history, feedback=self.feedback,
                now=self.now, exclusive=False,
            )
            kept, _ = recommend_service.finalize(
                raw, self.all_items, self.gender, occasion, limit=ENGINE_POOL)
            self._by_occasion[occasion] = kept
        return self._by_occasion[occasion]

    def pool(self, occasions):
        """Unique outfits across occasions; remembers every occasion each fits."""
        seen = {}
        for occasion in occasions:
            for outfit in self.outfits_for(occasion):
                key = outfit["outfit_key"]
                if key in seen:
                    if occasion not in seen[key]["best_for"]:
                        seen[key]["best_for"].append(occasion)
                else:
                    seen[key] = dict(outfit, best_for=[occasion])
        return list(seen.values())

    def recently_worn(self, outfit):
        when = self.outfit_worn.get(outfit["outfit_key"])
        days = _days_ago(when, self.now)
        return days if days is not None and days <= REPEAT_DAYS else None


# ---------------- explanation ----------------

def _colour_sentence(outfit):
    found = []
    for reason in outfit.get("color_reasons") or []:
        kind = reason.split(":", 1)[-1].strip()
        text = COLOUR_REASON_TEXT.get(kind)
        if text and text not in found:
            found.append(text)
    if not found:
        return "The colours sit comfortably together without competing."
    return found[0][0].upper() + found[0][1:] + "."


def _shape_sentence(outfit):
    core = recipes.core_items_of(outfit)
    kinds = {recipes.kind(i) for i in core}
    if outfit.get("style") == "ethnic":
        if kinds & {"saree", "lehenga", "anarkali"}:
            return "A complete traditional piece, so the drape and detail carry the look."
        if "nehru" in kinds:
            return "The Nehru jacket over the kurta adds structure and a festive finish."
        return "A matched ethnic base keeps the proportions long and graceful."
    if kinds & {"blazer", "coat"}:
        return "The layer on top adds structure over an easy base - polished but relaxed."
    if kinds & {"dress", "gown"}:
        return "One piece does the work, so the silhouette stays clean."
    if kinds & {"jacket"}:
        return "The extra layer adds depth and texture without fuss."
    return "A simple top-and-bottom pairing with balanced proportions."


def _piece(item, role, ctx):
    days = _days_ago(ctx.last_worn.get(str(item.get("_id"))), ctx.now)
    return {
        "_id": str(item.get("_id")),
        "category": item.get("category"),
        "display_name": item.get("display_name") or item.get("category"),
        "color": item.get("color"),
        "color_display": item.get("color_display") or item.get("color"),
        "image_path": item.get("image_path"),   # the real stored (Cloudinary) image
        "role": role,
        "last_worn_days": days,
    }


FOOTWEAR_HINT = {
    ("ethnic", "female"): "mojaris, juttis or heels",
    ("ethnic", "male"): "mojaris or loafers",
    ("western", "female"): "white sneakers or block heels",
    ("western", "male"): "white sneakers or loafers",
}


def decorate(outfit, ctx, taken_names, trend=None):
    aesthetic = naming.aesthetic_for(outfit)
    name = naming.name_for(aesthetic, taken_names)
    taken_names.add(name)
    roles = outfit.get("roles") or {}
    pieces = [_piece(i, roles.get(str(i.get("_id")), "piece"), ctx) for i in outfit.get("items", [])]

    matches = []
    for t in ctx.trends:
        if t.get("inspiration_only"):
            continue
        ok, _ = recipes.outfit_matches(t["recipe"], outfit)
        if ok:
            matches.append({"id": t["id"], "name": t["name"]})
    if trend:
        matches = [m for m in matches if m["id"] == trend["id"]] + [m for m in matches if m["id"] != trend["id"]]

    why = [_colour_sentence(outfit), _shape_sentence(outfit)]
    if matches:
        lead = next(t for t in ctx.trends if t["id"] == matches[0]["id"])
        why.append(f"It connects to {lead['name']}: {lead['summary'][0].lower() + lead['summary'][1:]}")

    best_for = outfit.get("best_for") or [outfit.get("occasion")]
    footwear = [p for p in pieces if p["role"] == "footwear"]
    notes = []
    if not footwear:
        hint = FOOTWEAR_HINT.get((outfit.get("style") or "western", ctx.gender), "matching shoes")
        notes.append(f"No matching shoes in your wardrobe for this look yet - {hint} would finish it.")
    worn = ctx.recently_worn(outfit)
    if worn is not None:
        notes.append(f"You wore this exact outfit {worn} day{'s' if worn != 1 else ''} ago.")

    return {
        "id": outfit["outfit_key"],
        "name": name,
        "aesthetic": aesthetic,
        "style_label": naming.label_for(aesthetic),
        "occasion": best_for[0],
        "occasion_label": OCCASION_LABEL.get(best_for[0], best_for[0]),
        "best_for": [OCCASION_LABEL.get(o, o) for o in best_for],
        "mode": outfit.get("style"),
        "pieces": pieces,
        "item_ids": [p["_id"] for p in pieces],
        "key_item_ids": outfit.get("key_item_ids") or [],
        "footwear": [p["display_name"] for p in footwear],
        "accessories": [p["display_name"] for p in pieces if p["role"] == "accessory"],
        "why": why,
        "colour_reasoning": why[0],
        "styling_tip": TIPS.get(aesthetic, TIPS["weekend_ease"]),
        "trends": matches[:2],
        "style_tags": outfit.get("style_tags") or [],
        "notes": notes,
        "source": "your_wardrobe",
    }


def _diverse(outfits, limit):
    """Prefer outfits that don't reuse the same main pieces."""
    picked, used = [], set()
    for outfit in outfits:
        core = set(outfit.get("key_item_ids") or [])
        if core and core & used and len(picked) < limit and any(
            not (set(o.get("key_item_ids") or []) & used) for o in outfits if o not in picked
        ):
            continue
        picked.append(outfit)
        used |= core
        if len(picked) == limit:
            break
    for outfit in outfits:
        if len(picked) == limit:
            break
        if outfit not in picked:
            picked.append(outfit)
    return picked


# ---------------- public operations ----------------

def create_outfits(ctx, occasion=None, colour=None, style=None, trend_id=None, count=3):
    trend = next((t for t in ctx.trends if t["id"] == trend_id), None) if trend_id else None
    notes = []
    if trend_id and not trend:
        return {"outfits": [], "notes": ["That trend isn't available for your account."], "trend": None}

    if occasion:
        occasions = [resolve_occasion_query(occasion)]
    elif trend:
        occasions = trend.get("occasions") or ALL_OCCASIONS
    else:
        occasions = ["casual"]

    pool = ctx.pool(occasions)
    if trend:
        pool = [o for o in pool if recipes.outfit_matches(trend["recipe"], o)[0]]
    if colour:
        pool = [o for o in pool if present.matches_colour(o, colour)]
    if style:
        styled = [o for o in pool if naming.aesthetic_for(o) == style]
        if styled:
            pool = styled
        elif pool:
            notes.append(f"No {naming.label_for(style)} outfits for this choice, so here are the closest ones.")

    fresh = [o for o in pool if ctx.recently_worn(o) is None]
    if len(fresh) < len(pool):
        notes.append("Outfits you wore in the last two weeks are left out so nothing repeats.")
    chosen_pool = fresh if fresh else pool
    chosen_pool.sort(key=lambda o: o.get("score", 0), reverse=True)
    chosen = _diverse(chosen_pool, count)

    taken = set()
    outfits = [decorate(o, ctx, taken, trend) for o in chosen]
    if not outfits:
        if trend and trend.get("inspiration_only"):
            notes.append(trend.get("rule_note") or "This trend is shown as inspiration only.")
        elif trend:
            notes.append("Your wardrobe can't recreate this trend yet - see what to shop for below.")
        else:
            notes.append("No complete outfits for these choices yet. Try another occasion or colour.")
    elif len(outfits) < count:
        notes.append(f"Your wardrobe has {len(outfits)} outfit{'s' if len(outfits) != 1 else ''} for this right now - add a few pieces for more options.")
    return {"outfits": outfits, "notes": notes,
            "trend": {"id": trend["id"], "name": trend["name"]} if trend else None}


def wardrobe_ideas(ctx, count=6):
    """Combinations the user has never worn together, rotating rarely-worn pieces."""
    pool = ctx.pool(ALL_OCCASIONS)
    never = [o for o in pool if o["outfit_key"] not in ctx.outfit_worn]

    def freshness(outfit):
        unworn = sum(1 for i in outfit.get("key_item_ids") or [] if i not in ctx.last_worn)
        multi = len(outfit.get("best_for") or [])
        return outfit.get("score", 0) + 4 * unworn + 2 * min(multi, 3)

    never.sort(key=freshness, reverse=True)
    chosen = _diverse(never, count)
    taken = set()
    ideas = []
    for outfit in chosen:
        card = decorate(outfit, ctx, taken)
        unworn = [p["display_name"] for p in card["pieces"]
                  if p["_id"] in (outfit.get("key_item_ids") or []) and p["last_worn_days"] is None]
        card["fresh_note"] = (
            "You haven't worn these together yet."
            + (f" Your {', '.join(unworn[:2])} hasn't been worn at all." if unworn else "")
        )
        ideas.append(card)
    return ideas


def trend_status(ctx, trend):
    """Can the user's wardrobe recreate this trend? Returns a dict for the UI."""
    if trend.get("inspiration_only"):
        return {"status": "inspiration", "message": trend.get("rule_note") or "Shown as inspiration only.",
                "pieces_owned": 0, "missing": [], "preview": None}
    recipe = trend["recipe"]
    owned = recipes.pieces_for(recipe, ctx.items)
    matching = [o for o in ctx.pool(trend.get("occasions") or ALL_OCCASIONS)
                if recipes.outfit_matches(recipe, o)[0]]
    accessory = trend.get("accessory_gap")
    if matching:
        matching.sort(key=lambda o: o.get("score", 0), reverse=True)
        preview = decorate(matching[0], ctx, set(), trend)
        message = f"Yes - you already own {len(owned)} piece{'s' if len(owned) != 1 else ''} that can recreate this."
        if accessory:
            message += f" Add {accessory['label']} to finish it. ({accessory['note']})"
        return {"status": "yes", "message": message, "pieces_owned": len(owned),
                "missing": [], "preview": preview, "outfit_count": len(matching)}
    missing = recipes.missing_slots(recipe, ctx.items)
    if missing:
        labels = [slot["label"] for slot in missing]
        return {"status": "no" if len(missing) == len(recipe.get("slots") or []) else "partly",
                "message": "You're missing " + " and ".join(labels) + ".",
                "pieces_owned": len(owned), "missing": labels,
                "buy": [slot.get("buy") for slot in missing if slot.get("buy")], "preview": None}
    return {"status": "partly",
            "message": "You own the right kinds of pieces, but not in a combination or colour that fits this trend under your styling rules.",
            "pieces_owned": len(owned), "missing": [],
            "buy": [slot.get("buy") for slot in (recipe.get("slots") or [])[:1] if slot.get("buy")],
            "preview": None}


def wardrobe_profile(ctx):
    ethnic = sum(1 for i in ctx.items if recipes.kind(i) in
                 {"kurta", "kurta_men", "kurta_women", "saree", "lehenga", "anarkali",
                  "ethnic_set", "sherwani", "nehru", "salwar", "palazzo", "dhoti", "pajama"})
    words = set()
    for item in ctx.items:
        for w in str(item.get("color") or "").lower().split():
            words.add(w)
    return {"item_count": len(ctx.items), "ethnic_share": (ethnic / len(ctx.items)) if ctx.items else 0,
            "colour_words": sorted(words)}


def overview(ctx):
    profile = wardrobe_profile(ctx)
    cards = []
    for trend in ctx.trends:
        status = trend_status(ctx, trend)
        card = {k: v for k, v in trend.items() if k != "recipe"}
        card["your_wardrobe"] = status
        card["rank"] = trend_lib.personal_rank(trend, profile, status["status"], ctx.now)
        cards.append(card)
    cards.sort(key=lambda c: c["rank"], reverse=True)
    return {
        "gender": ctx.gender,
        "profile": {"item_count": profile["item_count"], "ethnic_share": round(profile["ethnic_share"], 2)},
        "trends": cards,
        "live": ctx.live_status,
        "curated_on": trend_lib.catalogue()["curated_on"],
        "occasions": [{"value": k, "label": v} for k, v in OCCASIONS],
        "styles": [{"value": k, "label": v} for k, v in naming.STYLE_CHOICES],
    }
