"""
ONE consolidated patch script for the WEATHER-AWARE-RECOMMENDATION
MODULE round (wind/humidity data, activity tagging, a saved default
city on the Profile page, and the "why this works" bullets they
feed):

  - backend/weather.py: humidity_pct, wind_kph, is_windy added to
    both get_weather() and get_weather_forecast().
  - backend/outfit_recommendation.py: _weather_score() now factors
    wind/humidity and returns honest reasons; a new, purely-additive
    activity system (_activity_bonus); _score_outfit()/_build_why()/
    recommend_outfits() extended to carry and render those reasons.
  - backend/auth.py + backend/app.py: a saved default "city" on the
    user's profile, used AUTOMATICALLY by /api/ai/recommend when no
    ?city= is given (unless ?use_weather=false), plus an optional
    ?activity= query param threaded through recommendations and the
    trip planner.
  - backend/trip_planner.py: plan_trip() accepts the same optional
    `activity`.
  - frontend/src/pages/Profile.js: an editable "Default city" field.
  - frontend/src/pages/OutfitRecommendation.js: auto-loads the saved
    city on page load, an optional Activity dropdown, and a fuller
    weather status display (humidity/wind, "using your saved city").
  - frontend/src/pages/TripPlanner.js: humidity/wind shown alongside
    the existing temperature display.

Safe to run more than once - every step checks whether it's already
applied and skips it rather than double-patching or erroring.

Run this from inside your wardrobe-ai folder (the one with both
"backend" and "frontend" folders in it), the same way as the last
patch script:

    python apply_weather_module_patches.py
"""
import pathlib

WEATHER_PY = pathlib.Path("backend/weather.py")
OUTFIT_PY = pathlib.Path("backend/outfit_recommendation.py")
AUTH_PY = pathlib.Path("backend/auth.py")
APP_PY = pathlib.Path("backend/app.py")
TRIP_PLANNER_PY = pathlib.Path("backend/trip_planner.py")
PROFILE_JS = pathlib.Path("frontend/src/pages/Profile.js")
OUTFIT_JS = pathlib.Path("frontend/src/pages/OutfitRecommendation.js")
TRIP_PLANNER_JS = pathlib.Path("frontend/src/pages/TripPlanner.js")


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def replace_once(text, old, new, label, filename):
    if new in text:
        print(f"{filename}: {label} - already applied, skipping.")
        return text
    require(
        old in text,
        f"{filename}: could not find the expected block for "
        f"'{label}' - nothing changed here. Tell Claude this happened.",
    )
    return text.replace(old, new, 1)


# ================================================================
# 1. backend/weather.py
# ================================================================

def patch_weather_py():
    text = WEATHER_PY.read_text(encoding="utf-8")
    name = "weather.py"

    text = replace_once(
        text,
        '''RAINY_CONDITIONS = ("rain", "drizzle", "thunderstorm")
HOT_THRESHOLD_C = 28
COLD_THRESHOLD_C = 15''',
        '''RAINY_CONDITIONS = ("rain", "drizzle", "thunderstorm")
HOT_THRESHOLD_C = 28
COLD_THRESHOLD_C = 15

# Wind/humidity thresholds - same reasoning as HOT/COLD above: a
# single shared cutoff so "windy"/"humid" mean the same thing for a
# current reading and a forecasted day. OpenWeatherMap's "metric"
# units give wind speed in m/s, which nobody thinks in, so it's
# converted to km/h (kph) for anything shown to the user or reasoned
# about here - 20 kph (~5.5 m/s) is a "you'll feel it" breeze, not a
# storm.
WINDY_THRESHOLD_KPH = 20
HUMID_THRESHOLD_PCT = 70
MPS_TO_KPH = 3.6''',
        "wind/humidity threshold constants",
        name,
    )

    text = replace_once(
        text,
        '''            "condition": "clouds",       # OpenWeatherMap's "main" field, lowercased
            "description": "few clouds",
            "is_rainy": False,
            "is_hot": False,
            "is_cold": False
        }''',
        '''            "condition": "clouds",       # OpenWeatherMap's "main" field, lowercased
            "description": "few clouds",
            "humidity_pct": 55,          # None if OpenWeatherMap didn't send one
            "wind_kph": 11.2,            # None if OpenWeatherMap didn't send one
            "is_rainy": False,
            "is_hot": False,
            "is_cold": False,
            "is_windy": False
        }''',
        "get_weather() docstring example",
        name,
    )

    text = replace_once(
        text,
        '''    temp_c = data.get("main", {}).get("temp")

    return {
        "city": data.get("name", city),
        "temp_c": temp_c,
        "condition": condition,
        "description": description,
        "is_rainy": condition in RAINY_CONDITIONS,
        "is_hot": (
            temp_c is not None
            and temp_c >= HOT_THRESHOLD_C
        ),
        "is_cold": (
            temp_c is not None
            and temp_c <= COLD_THRESHOLD_C
        )
    }''',
        '''    temp_c = data.get("main", {}).get("temp")
    humidity_pct = data.get("main", {}).get("humidity")

    wind_mps = data.get("wind", {}).get("speed")
    wind_kph = (
        round(wind_mps * MPS_TO_KPH, 1)
        if wind_mps is not None
        else None
    )

    return {
        "city": data.get("name", city),
        "temp_c": temp_c,
        "condition": condition,
        "description": description,
        "humidity_pct": humidity_pct,
        "wind_kph": wind_kph,
        "is_rainy": condition in RAINY_CONDITIONS,
        "is_hot": (
            temp_c is not None
            and temp_c >= HOT_THRESHOLD_C
        ),
        "is_cold": (
            temp_c is not None
            and temp_c <= COLD_THRESHOLD_C
        ),
        "is_windy": (
            wind_kph is not None
            and wind_kph >= WINDY_THRESHOLD_KPH
        )
    }''',
        "get_weather() return dict",
        name,
    )

    text = replace_once(
        text,
        '''                    "condition": "clouds",      # from the reading closest to midday
                    "description": "overcast clouds",
                    "is_rainy": False,          # True if ANY reading that day was rainy
                    "is_hot": False,
                    "is_cold": True
                },''',
        '''                    "condition": "clouds",      # from the reading closest to midday
                    "description": "overcast clouds",
                    "humidity_pct": 62,         # mean across that day's readings
                    "wind_kph": 14.4,           # max across that day's readings
                    "is_rainy": False,          # True if ANY reading that day was rainy
                    "is_hot": False,
                    "is_cold": True,
                    "is_windy": False
                },''',
        "get_weather_forecast() docstring example",
        name,
    )

    text = replace_once(
        text,
        '''        temp_c = sum(temps) / len(temps)
        temp_min_c = min(temps)
        temp_max_c = max(temps)''',
        '''        temp_c = sum(temps) / len(temps)
        temp_min_c = min(temps)
        temp_max_c = max(temps)

        humidities = [
            entry["main"]["humidity"]
            for entry in entries
            if entry.get("main", {}).get("humidity") is not None
        ]
        humidity_pct = (
            round(sum(humidities) / len(humidities))
            if humidities
            else None
        )

        # Max, not mean, for wind - like is_rainy below, an outfit
        # needs to survive the windiest part of the day, not just an
        # average that could hide one genuinely blustery afternoon.
        wind_speeds_mps = [
            entry["wind"]["speed"]
            for entry in entries
            if entry.get("wind", {}).get("speed") is not None
        ]
        wind_kph = (
            round(max(wind_speeds_mps) * MPS_TO_KPH, 1)
            if wind_speeds_mps
            else None
        )''',
        "per-day humidity/wind aggregation",
        name,
    )

    text = replace_once(
        text,
        '''        by_date[date_key] = {
            "city": resolved_city,
            "temp_c": round(temp_c, 1),
            "temp_min_c": round(temp_min_c, 1),
            "temp_max_c": round(temp_max_c, 1),
            "condition": condition,
            "description": description,
            "is_rainy": is_rainy,
            "is_hot": temp_max_c >= HOT_THRESHOLD_C,
            "is_cold": temp_max_c <= COLD_THRESHOLD_C,
        }''',
        '''        by_date[date_key] = {
            "city": resolved_city,
            "temp_c": round(temp_c, 1),
            "temp_min_c": round(temp_min_c, 1),
            "temp_max_c": round(temp_max_c, 1),
            "condition": condition,
            "description": description,
            "humidity_pct": humidity_pct,
            "wind_kph": wind_kph,
            "is_rainy": is_rainy,
            "is_hot": temp_max_c >= HOT_THRESHOLD_C,
            "is_cold": temp_max_c <= COLD_THRESHOLD_C,
            "is_windy": (
                wind_kph is not None
                and wind_kph >= WINDY_THRESHOLD_KPH
            ),
        }''',
        "by_date dict - humidity/wind/is_windy keys",
        name,
    )

    WEATHER_PY.write_text(text, encoding="utf-8")
    print(f"{name}: all patches applied.")


# ================================================================
# 2. backend/outfit_recommendation.py
# ================================================================

def patch_outfit_recommendation_py():
    text = OUTFIT_PY.read_text(encoding="utf-8")
    name = "outfit_recommendation.py"

    text = replace_once(
        text,
        '''WARM_MATERIAL_MARKERS = {
    "wool", "fleece", "thermal", "fur", "down",
    "flannel", "corduroy", "cashmere"
}


def _has_warm_material(item):
    material = (item.get("material") or "").lower()
    if not material:
        return False
    material_tokens = set(re.split(r"[^a-z]+", material))
    return bool(material_tokens & WARM_MATERIAL_MARKERS)


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
        warm_material = _has_warm_material(item)

        if weather.get("is_hot") and tokens & LIGHT_MARKERS:
            points += 25

        elif weather.get("is_cold") and (tokens & WARM_LAYER_MARKERS):
            points += 25

        elif weather.get("is_cold") and warm_material:
            # Category alone didn't mark this as a warm layer (e.g.
            # a plain "Shirt" or "Kurta"), but the user noted a warm
            # material on it - still a genuinely good cold-weather
            # pick, just a slightly smaller nudge than a category
            # that's unambiguously outerwear.
            points += 20

        elif weather.get("is_rainy") and (tokens & WARM_LAYER_MARKERS):
            points += 15

        else:
            points += 5

    return points / len(items)''',
        '''WARM_MATERIAL_MARKERS = {
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
    return min(matches * 6, 12), f"also fits well for {label}"''',
        "_weather_score rewrite + activity system",
        name,
    )

    text = replace_once(
        text,
        '''def _score_outfit(items, occasion, weather=None):
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

    return bullets''',
        '''def _score_outfit(items, occasion, weather=None, activity=None):
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

    return {
        "score": round(
            fit_points + color_points + style_points
            + weather_points + activity_points,
            1
        ),
        "flagged": flagged,
        "color_reasons": color_reasons,
        "style_reasons": style_reasons,
        "weather_reasons": weather_reasons,
        "activity_reasons": activity_reasons,
    }


def _build_why(
    occasion, flagged, color_reasons, style_reasons,
    weather_reasons=None, activity_reasons=None
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

    return bullets''',
        "_score_outfit + _build_why rewrite",
        name,
    )

    text = replace_once(
        text,
        '''def recommend_outfits(wardrobe_items, occasion="casual", weather=None, account_gender=None, limit=10):
    """
    Generate ranked complete outfit recommendations
    from the user's wardrobe.

    Uses existing wardrobe categories, colors and (automatically
    inferred) occasions - no manual occasion tagging required.
    `weather`, when provided, is the dict returned by
    backend.weather.get_weather() and nudges ranking toward
    weather-appropriate pieces. `account_gender` ("Male"/"Female"),
    when provided, is a defense-in-depth filter - see
    _filter_by_gender() above.''',
        '''def recommend_outfits(
    wardrobe_items, occasion="casual", weather=None,
    account_gender=None, limit=10, activity=None
):
    """
    Generate ranked complete outfit recommendations
    from the user's wardrobe.

    Uses existing wardrobe categories, colors and (automatically
    inferred) occasions - no manual occasion tagging required.
    `weather`, when provided, is the dict returned by
    backend.weather.get_weather() and nudges ranking toward
    weather-appropriate pieces. `account_gender` ("Male"/"Female"),
    when provided, is a defense-in-depth filter - see
    _filter_by_gender() above. `activity` (see CANONICAL_ACTIVITIES),
    when provided and recognized, is an additional, purely additive
    ranking nudge - see _activity_bonus() above; it never filters
    anything out the way `occasion` does.''',
        "recommend_outfits() signature/docstring",
        name,
    )

    text = replace_once(
        text,
        '''        outcome = _score_outfit(items, occasion, weather)

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
        })''',
        '''        outcome = _score_outfit(items, occasion, weather, activity)

        recommendations.append({
            "occasion": occasion,
            "items": items,
            "type": "one-piece",
            "score": outcome["score"],
            "flagged": outcome["flagged"],
            "color_reasons": outcome["color_reasons"],
            "style_reasons": outcome["style_reasons"],
            "weather_reasons": outcome["weather_reasons"],
            "activity_reasons": outcome["activity_reasons"],
            "why": _build_why(
                occasion, outcome["flagged"],
                outcome["color_reasons"], outcome["style_reasons"],
                outcome["weather_reasons"], outcome["activity_reasons"]
            )
        })''',
        "dress/one-piece loop scoring call",
        name,
    )

    text = replace_once(
        text,
        '''            outcome = _score_outfit(items, occasion, weather)

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
            })''',
        '''            outcome = _score_outfit(items, occasion, weather, activity)

            recommendations.append({
                "occasion": occasion,
                "items": items,
                "type": "top-bottom",
                "score": outcome["score"],
                "flagged": outcome["flagged"],
                "color_reasons": outcome["color_reasons"],
                "style_reasons": outcome["style_reasons"],
                "weather_reasons": outcome["weather_reasons"],
                "activity_reasons": outcome["activity_reasons"],
                "why": _build_why(
                    occasion, outcome["flagged"],
                    outcome["color_reasons"], outcome["style_reasons"],
                    outcome["weather_reasons"], outcome["activity_reasons"]
                )
            })''',
        "top-bottom loop scoring call",
        name,
    )

    OUTFIT_PY.write_text(text, encoding="utf-8")
    print(f"{name}: all patches applied.")


# ================================================================
# 3. backend/auth.py
# ================================================================

def patch_auth_py():
    text = AUTH_PY.read_text(encoding="utf-8")
    name = "auth.py"

    text = replace_once(
        text,
        '''    return {
        "name": user.get("name"),
        "email": user.get("email"),
        "gender": user.get("gender"),
        # Both optional and absent on most existing accounts - "" is
        # the honest "not set yet" value the frontend already treats
        # every other optional field (color, material, styling) as.
        "phone": user.get("phone", ""),
        "profile_picture": user.get("profile_picture", ""),
    }


def update_user_profile(email, name=None, phone=None):
    """
    Updates ONLY "name" and "phone" - the two fields that are
    genuinely safe to let a user change themselves.

    Email is deliberately NOT editable here: it's the account's
    permanent identifier - the JWT identity, and every wardrobe item/
    trip's user_email, are keyed on it - so changing it would orphan
    all of that account's existing data. Gender is permanently locked
    at registration (see register_user/migrate_user_gender above,
    which remain the only things that ever write "gender"). Neither
    is accepted as a parameter here at all, so there's no field name
    a caller could pass to slip past that.
    """
    set_fields = {}

    if name is not None and name.strip():
        set_fields["name"] = name.strip()

    if phone is not None:
        # "" is a meaningful value here (clearing a previously-set
        # phone number) - unlike name, which should never be blanked
        # out to empty since every account must have SOME name.
        set_fields["phone"] = phone.strip()

    if not set_fields:
        return {"success": False, "message": "Nothing to update"}

    users_collection.update_one({"email": email}, {"$set": set_fields})

    return {"success": True}''',
        '''    return {
        "name": user.get("name"),
        "email": user.get("email"),
        "gender": user.get("gender"),
        # Both optional and absent on most existing accounts - "" is
        # the honest "not set yet" value the frontend already treats
        # every other optional field (color, material, styling) as.
        "phone": user.get("phone", ""),
        "profile_picture": user.get("profile_picture", ""),
        # Default city/location for weather-aware recommendations
        # (see backend.app's /api/ai/recommend, which falls back to
        # this when the request doesn't pass an explicit ?city=) -
        # same "" not-set-yet convention as phone above.
        "city": user.get("city", ""),
    }


def update_user_profile(email, name=None, phone=None, city=None):
    """
    Updates ONLY "name", "phone" and "city" - fields that are
    genuinely safe to let a user change themselves.

    Email is deliberately NOT editable here: it's the account's
    permanent identifier - the JWT identity, and every wardrobe item/
    trip's user_email, are keyed on it - so changing it would orphan
    all of that account's existing data. Gender is permanently locked
    at registration (see register_user/migrate_user_gender above,
    which remain the only things that ever write "gender"). Neither
    is accepted as a parameter here at all, so there's no field name
    a caller could pass to slip past that.
    """
    set_fields = {}

    if name is not None and name.strip():
        set_fields["name"] = name.strip()

    if phone is not None:
        # "" is a meaningful value here (clearing a previously-set
        # phone number) - unlike name, which should never be blanked
        # out to empty since every account must have SOME name.
        set_fields["phone"] = phone.strip()

    if city is not None:
        # Same "clearing is meaningful" reasoning as phone - a user
        # who travels a lot may deliberately want to go back to
        # entering a city by hand each time instead of a stale default.
        set_fields["city"] = city.strip()

    if not set_fields:
        return {"success": False, "message": "Nothing to update"}

    users_collection.update_one({"email": email}, {"$set": set_fields})

    return {"success": True}''',
        "get_user_profile()/update_user_profile() city field",
        name,
    )

    AUTH_PY.write_text(text, encoding="utf-8")
    print(f"{name}: all patches applied.")


# ================================================================
# 4. backend/app.py
# ================================================================

def patch_app_py():
    text = APP_PY.read_text(encoding="utf-8")
    name = "app.py"

    text = replace_once(
        text,
        '''        # Optional city -> weather nudges the ranking, but is
        # never required. Any failure (no API key configured,
        # bad city name, network issue) just means recommendations
        # come back without a weather boost, not a broken request.
        city = request.args.get("city")

        weather = None
        weather_error = None

        if city:

            try:

                weather = get_weather(city)

            except Exception as e:

                weather_error = str(e)

                print(
                    f"Weather lookup skipped: {e}"
                )

        # Generate recommendations. account_gender is a
        # defense-in-depth filter (see
        # outfit_recommendation._filter_by_gender) on top of the
        # gender guards already applied at upload time - it's what
        # guarantees a Male account can never receive a Saree/
        # Lehenga/etc suggestion and vice versa, even for
        # legacy/migrated wardrobe items.
        recommendations = recommend_outfits(
            wardrobe_items,
            occasion=occasion,
            weather=weather,
            account_gender=account_gender
        )''',
        '''        # Optional city -> weather nudges the ranking, but is
        # never required. An explicit ?city= always wins; otherwise,
        # UNLESS the caller explicitly opted out with
        # ?use_weather=false (see OutfitRecommendation.js's "Consider
        # today's weather" checkbox), fall back to the user's saved
        # default city (Profile page) so weather applies
        # automatically once someone has set one - they shouldn't
        # have to retype their city every visit. Any weather-lookup
        # failure (no API key configured, bad city name, network
        # issue) just means recommendations come back without a
        # weather boost, not a broken request.
        city = request.args.get("city")
        used_saved_city = False

        use_weather = request.args.get("use_weather", "true").lower() != "false"

        if not city and use_weather:
            profile = get_user_profile(user_email)
            saved_city = (profile or {}).get("city")
            if saved_city:
                city = saved_city
                used_saved_city = True

        # Optional activity tag (see outfit_recommendation.
        # CANONICAL_ACTIVITIES) - purely additive, never required and
        # never filters anything out on its own; an unrecognized or
        # missing value is simply ignored.
        activity = request.args.get("activity")

        weather = None
        weather_error = None

        if city:

            try:

                weather = get_weather(city)

            except Exception as e:

                weather_error = str(e)

                print(
                    f"Weather lookup skipped: {e}"
                )

        # Generate recommendations. account_gender is a
        # defense-in-depth filter (see
        # outfit_recommendation._filter_by_gender) on top of the
        # gender guards already applied at upload time - it's what
        # guarantees a Male account can never receive a Saree/
        # Lehenga/etc suggestion and vice versa, even for
        # legacy/migrated wardrobe items.
        recommendations = recommend_outfits(
            wardrobe_items,
            occasion=occasion,
            weather=weather,
            account_gender=account_gender,
            activity=activity
        )''',
        "recommend route: default city + activity",
        name,
    )

    text = replace_once(
        text,
        '''        return jsonify({

            "success": True,

            "recommendations":
                recommendations,

            "notes": missing_notes,

            "weather": weather,

            "weather_error": weather_error

        }), 200''',
        '''        return jsonify({

            "success": True,

            "recommendations":
                recommendations,

            "notes": missing_notes,

            "weather": weather,

            "weather_error": weather_error,

            # Lets the frontend show "using your saved city, X" vs
            # an explicit one-off lookup, instead of guessing from
            # the query string it doesn't have direct access to.
            "used_saved_city": used_saved_city

        }), 200''',
        "recommend route: used_saved_city in response",
        name,
    )

    text = replace_once(
        text,
        '''    result = update_user_profile(
        user_email,
        name=data.get("name"),
        phone=data.get("phone"),
    )''',
        '''    result = update_user_profile(
        user_email,
        name=data.get("name"),
        phone=data.get("phone"),
        city=data.get("city"),
    )''',
        "edit_profile PUT: city field",
        name,
    )

    text = replace_once(
        text,
        '''    occasion = data.get("occasion", "casual")''',
        '''    occasion = data.get("occasion", "casual")
    activity = data.get("activity")''',
        "create_trip: activity var",
        name,
    )

    text = replace_once(
        text,
        '''            occasion=occasion,
            weather=weather,
            weather_by_date=weather_by_date,
            account_gender=account_gender
        )''',
        '''            occasion=occasion,
            weather=weather,
            weather_by_date=weather_by_date,
            account_gender=account_gender,
            activity=activity
        )''',
        "create_trip: plan_trip() activity arg",
        name,
    )

    APP_PY.write_text(text, encoding="utf-8")
    print(f"{name}: all patches applied.")


# ================================================================
# 5. backend/trip_planner.py
# ================================================================

def patch_trip_planner_py():
    text = TRIP_PLANNER_PY.read_text(encoding="utf-8")
    name = "trip_planner.py"

    text = replace_once(
        text,
        '''def plan_trip(
    wardrobe_items,
    destination,
    start_date,
    end_date,
    occasion="casual",
    weather=None,
    weather_by_date=None,
    account_gender=None
):''',
        '''def plan_trip(
    wardrobe_items,
    destination,
    start_date,
    end_date,
    occasion="casual",
    weather=None,
    weather_by_date=None,
    account_gender=None,
    activity=None
):''',
        "plan_trip() signature",
        name,
    )

    text = replace_once(
        text,
        '''    used for any day `weather_by_date` doesn't cover (see
    _resolve_day_weather above).''',
        '''    used for any day `weather_by_date` doesn't cover (see
    _resolve_day_weather above). `activity` (see
    outfit_recommendation.CANONICAL_ACTIVITIES) is an optional,
    purely additive ranking nudge applied to every day identically -
    same one-time choice as `occasion`, not a per-day setting.''',
        "plan_trip() docstring",
        name,
    )

    text = replace_once(
        text,
        '''        day_pool = recommend_outfits(
            wardrobe_items,
            occasion=occasion,
            weather=day_weather,
            account_gender=account_gender,
            limit=pool_size
        )''',
        '''        day_pool = recommend_outfits(
            wardrobe_items,
            occasion=occasion,
            weather=day_weather,
            account_gender=account_gender,
            limit=pool_size,
            activity=activity
        )''',
        "per-day recommend_outfits() call",
        name,
    )

    TRIP_PLANNER_PY.write_text(text, encoding="utf-8")
    print(f"{name}: all patches applied.")


# ================================================================
# 6. frontend/src/pages/Profile.js
# ================================================================

def patch_profile_js():
    text = PROFILE_JS.read_text(encoding="utf-8")
    name = "Profile.js"

    text = replace_once(
        text,
        '''  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState("");''',
        '''  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  // Default city, used to auto-apply weather-aware recommendations
  // (see OutfitRecommendation.js) without retyping a city every
  // visit - saving here is optional, exactly like phone.
  const [city, setCity] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState("");''',
        "city state",
        name,
    )

    text = replace_once(
        text,
        '''      if (res.data.success) {
        setProfile(res.data.profile);
        setName(res.data.profile.name || "");
        setPhone(res.data.profile.phone || "");
      } else {''',
        '''      if (res.data.success) {
        setProfile(res.data.profile);
        setName(res.data.profile.name || "");
        setPhone(res.data.profile.phone || "");
        setCity(res.data.profile.city || "");
      } else {''',
        "fetchProfile: load city",
        name,
    )

    text = replace_once(
        text,
        '''  const handleEditCancel = () => {
    setName(profile.name || "");
    setPhone(profile.phone || "");
    setEditing(false);
  };''',
        '''  const handleEditCancel = () => {
    setName(profile.name || "");
    setPhone(profile.phone || "");
    setCity(profile.city || "");
    setEditing(false);
  };''',
        "handleEditCancel: reset city",
        name,
    )

    text = replace_once(
        text,
        '''      const res = await axios.put(
        "http://localhost:5001/api/user/profile",
        { name, phone },
        { headers: { Authorization: `Bearer ${token}` } }
      );''',
        '''      const res = await axios.put(
        "http://localhost:5001/api/user/profile",
        { name, phone, city },
        { headers: { Authorization: `Bearer ${token}` } }
      );''',
        "handleEditSave: send city",
        name,
    )

    text = replace_once(
        text,
        '''              <p className="item-meta">
                <strong>Phone:</strong>{" "}
                {profile.phone || "Not added yet"}
              </p>

              <p className="item-meta">
                <strong>Wardrobe:</strong>{" "}
                {GENDER_LABELS[profile.gender] ||
                  "Not set"}
              </p>

              {saveMessage && (
                <p style={{ color: "#2f6b45", fontSize: "13px" }}>
                  {saveMessage}
                </p>
              )}

              <button
                className="btn btn-secondary btn-sm"
                onClick={handleEditStart}
                style={{ marginTop: "10px" }}
              >
                Edit Name / Phone
              </button>
            </>
          ) : (
            <>
              <label className="field-label">Name</label>
              <input
                placeholder="Your name"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />

              <label className="field-label">Phone number</label>
              <input
                placeholder="Phone number (optional)"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
              />

              <p''',
        '''              <p className="item-meta">
                <strong>Phone:</strong>{" "}
                {profile.phone || "Not added yet"}
              </p>

              <p className="item-meta">
                <strong>Default city:</strong>{" "}
                {profile.city || "Not set"}
              </p>

              <p
                style={{
                  fontSize: "12px",
                  color: "#8a7a6d",
                  marginTop: "-4px",
                }}
              >
                Used to apply today's weather to your outfit
                recommendations automatically.
              </p>

              <p className="item-meta">
                <strong>Wardrobe:</strong>{" "}
                {GENDER_LABELS[profile.gender] ||
                  "Not set"}
              </p>

              {saveMessage && (
                <p style={{ color: "#2f6b45", fontSize: "13px" }}>
                  {saveMessage}
                </p>
              )}

              <button
                className="btn btn-secondary btn-sm"
                onClick={handleEditStart}
                style={{ marginTop: "10px" }}
              >
                Edit Name / Phone / City
              </button>
            </>
          ) : (
            <>
              <label className="field-label">Name</label>
              <input
                placeholder="Your name"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />

              <label className="field-label">Phone number</label>
              <input
                placeholder="Phone number (optional)"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
              />

              <label className="field-label">Default city</label>
              <input
                placeholder="e.g. Bengaluru (optional)"
                value={city}
                onChange={(e) => setCity(e.target.value)}
              />
              <p
                style={{
                  fontSize: "12px",
                  color: "#8a7a6d",
                  marginTop: "2px",
                  marginBottom: "12px",
                }}
              >
                Recommendations will use this city's weather
                automatically. You can still type a different city
                for one-off checks.
              </p>

              <p''',
        "profile page: Default city display + edit field",
        name,
    )

    PROFILE_JS.write_text(text, encoding="utf-8")
    print(f"{name}: all patches applied.")


# ================================================================
# 7. frontend/src/pages/OutfitRecommendation.js
# ================================================================

def patch_outfit_recommendation_js():
    text = OUTFIT_JS.read_text(encoding="utf-8")
    name = "OutfitRecommendation.js"

    # A few special characters (degree sign, middle dot) need to
    # survive being pasted through Windows/Notepad without mangling -
    # see the previous patch script's TripPlanner.js step for why
    # this is built from chr() instead of typed directly.
    degree = chr(0x00B0)
    middle_dot = chr(0x00B7)

    text = replace_once(
        text,
        '''import { useState } from "react";''',
        '''import { useState, useEffect } from "react";''',
        "import useEffect",
        name,
    )

    text = replace_once(
        text,
        '''// Set at registration/login (see Register.js / Login.js). Shown here
// purely as a label so it's clear whose wardrobe these recommendations
// were built from - it never changes which items are eligible.
const GENDER_LABELS = {
  male: "Men's Wear",
  female: "Women's Wear"
};

function OutfitRecommendation() {
  const [occasion, setOccasion] = useState("casual");
  const [city, setCity] = useState("");
  const [useWeather, setUseWeather] = useState(false);
  const [weather, setWeather] = useState(null);
  const [weatherError, setWeatherError] = useState("");
  const [recommendations, setRecommendations] = useState([]);
  const [notes, setNotes] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [searched, setSearched] = useState(false);

  const genderKey = (localStorage.getItem("gender") || "").toLowerCase();
  const genderLabel = GENDER_LABELS[genderKey];

  const getRecommendations = async () => {
    setLoading(true);
    setError("");
    setWeather(null);
    setWeatherError("");
    setRecommendations([]);
    setNotes([]);
    setSearched(true);

    const token = localStorage.getItem("token");

    let url = `http://localhost:5001/api/ai/recommend?occasion=${occasion}`;

    if (useWeather && city.trim()) {
      url += `&city=${encodeURIComponent(city.trim())}`;
    }

    try {''',
        '''// Set at registration/login (see Register.js / Login.js). Shown here
// purely as a label so it's clear whose wardrobe these recommendations
// were built from - it never changes which items are eligible.
const GENDER_LABELS = {
  male: "Men's Wear",
  female: "Women's Wear"
};

// Matches backend.outfit_recommendation.CANONICAL_ACTIVITIES. Purely
// an optional ranking nudge (never a filter, unlike occasion) - so
// "None" is a perfectly normal choice, not a missing answer.
const ACTIVITIES = [
  ["", "None / not specific"],
  ["sports", "Sports / workout"],
  ["outdoor", "Outdoor"],
  ["formal_event", "Formal event"],
  ["travel", "Travel"],
];

function OutfitRecommendation() {
  const [occasion, setOccasion] = useState("casual");
  const [activity, setActivity] = useState("");
  const [city, setCity] = useState("");
  // Defaults to on once a saved profile city loads (see the
  // fetchDefaultCity effect below) - weather is meant to apply
  // automatically app-wide per the spec, not require re-opting-in
  // on every visit. Unchecking it tells the backend NOT to fall back
  // to the saved city either (?use_weather=false), so it's a real
  // opt-out, not just "don't bother filling the box for me".
  const [useWeather, setUseWeather] = useState(false);
  const [usedSavedCity, setUsedSavedCity] = useState(false);
  const [weather, setWeather] = useState(null);
  const [weatherError, setWeatherError] = useState("");
  const [recommendations, setRecommendations] = useState([]);
  const [notes, setNotes] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [searched, setSearched] = useState(false);

  const genderKey = (localStorage.getItem("gender") || "").toLowerCase();
  const genderLabel = GENDER_LABELS[genderKey];

  // On first load, pull the user's saved default city (Profile page)
  // so weather-aware recommendations work automatically without
  // making them retype a city every visit - still fully editable/
  // overridable below, and harmless (silently does nothing) if the
  // profile fetch fails or no city has been saved yet.
  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) {
      return;
    }

    axios
      .get("http://localhost:5001/api/user/profile", {
        headers: { Authorization: `Bearer ${token}` },
      })
      .then((res) => {
        const savedCity = res.data?.profile?.city;
        if (savedCity) {
          setCity(savedCity);
          setUseWeather(true);
        }
      })
      .catch((err) => {
        // Non-fatal - the page works fine with weather simply off
        // by default, same as before this default-city lookup existed.
        console.error("Could not load default city:", err);
      });
  }, []);

  const getRecommendations = async () => {
    setLoading(true);
    setError("");
    setWeather(null);
    setWeatherError("");
    setUsedSavedCity(false);
    setRecommendations([]);
    setNotes([]);
    setSearched(true);

    const token = localStorage.getItem("token");

    let url = `http://localhost:5001/api/ai/recommend?occasion=${occasion}`;

    if (activity) {
      url += `&activity=${encodeURIComponent(activity)}`;
    }

    if (useWeather) {
      if (city.trim()) {
        url += `&city=${encodeURIComponent(city.trim())}`;
      }
      // else: leave city unset so the backend can fall back to the
      // saved profile city on its own (see /api/ai/recommend).
    } else {
      // Explicit opt-out - without this the backend would still
      // fall back to the saved profile city on its own.
      url += "&use_weather=false";
    }

    try {''',
        "state hooks + auto default-city effect + URL building",
        name,
    )

    text = replace_once(
        text,
        '''        setWeather(res.data.weather || null);
        setWeatherError(res.data.weather_error || "");''',
        '''        setWeather(res.data.weather || null);
        setWeatherError(res.data.weather_error || "");
        setUsedSavedCity(!!res.data.used_saved_city);''',
        "response handling: used_saved_city",
        name,
    )

    text = replace_once(
        text,
        '''          {OCCASIONS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>

          {/* WEATHER */}''',
        '''          {OCCASIONS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>

          {/* ACTIVITY (optional, additive only - see ACTIVITIES) */}

          <label className="field-label">Activity (optional)</label>

          <select
            value={activity}
            onChange={(e) => setActivity(e.target.value)}
          >
            {ACTIVITIES.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>

          {/* WEATHER */}''',
        "activity dropdown",
        name,
    )

    old_weather_status = (
        '''          {!loading && weather && (
            <p
              style={{
                marginTop: "15px",
                color: "#c1694f",
                fontSize: "13px",
              }}
            >
              {weather.city}: {weather.temp_c}''' + degree + '''C,{" "}
              {weather.description}
            </p>
          )}'''
    )

    new_weather_status = (
        '''          {!loading && weather && (
            <div style={{ marginTop: "15px" }}>
              <p
                style={{
                  color: "#c1694f",
                  fontSize: "13px",
                  margin: 0,
                }}
              >
                {weather.city}: {weather.temp_c}''' + degree + '''C,{" "}
                {weather.description}
              </p>
              <p
                style={{
                  color: "#8a7a6d",
                  fontSize: "12px",
                  margin: "3px 0 0",
                }}
              >
                {weather.humidity_pct != null &&
                  `Humidity ${weather.humidity_pct}%`}
                {weather.humidity_pct != null &&
                  weather.wind_kph != null &&
                  " ''' + middle_dot + ''' "}
                {weather.wind_kph != null &&
                  `Wind ${weather.wind_kph} km/h`}
              </p>
              {usedSavedCity && (
                <p
                  style={{
                    color: "#8a7a6d",
                    fontSize: "11px",
                    margin: "3px 0 0",
                    fontStyle: "italic",
                  }}
                >
                  Using your saved default city (change it in My
                  Profile, or type a different city here for a
                  one-off check).
                </p>
              )}
            </div>
          )}'''
    )

    text = replace_once(
        text,
        old_weather_status,
        new_weather_status,
        "weather status display (humidity/wind/saved-city note)",
        name,
    )

    OUTFIT_JS.write_text(text, encoding="utf-8")
    print(f"{name}: all patches applied.")


# ================================================================
# 8. frontend/src/pages/TripPlanner.js
# ================================================================

def patch_trip_planner_js():
    text = TRIP_PLANNER_JS.read_text(encoding="utf-8")
    name = "TripPlanner.js"

    degree = chr(0x00B0)
    en_dash = chr(0x2013)
    em_dash = chr(0x2014)
    middle_dot = chr(0x00B7)

    old_day_line = (
        '''                      {day.weather.temp_c}''' + degree + '''C
                      {day.weather.temp_min_c !== undefined &&
                        day.weather.temp_max_c !== undefined &&
                        ` (${day.weather.temp_min_c}''' + en_dash + '''${day.weather.temp_max_c}''' + degree + '''C)`}
                      {day.weather.description
                        ? `, ${day.weather.description}`
                        : ""}
                      {day.weather_estimated &&
                        " ''' + em_dash + ''' estimated (beyond the 5-day forecast)"}
                    </p>
                  )}'''
    )

    new_day_line = (
        '''                      {day.weather.temp_c}''' + degree + '''C
                      {day.weather.temp_min_c !== undefined &&
                        day.weather.temp_max_c !== undefined &&
                        ` (${day.weather.temp_min_c}''' + en_dash + '''${day.weather.temp_max_c}''' + degree + '''C)`}
                      {day.weather.description
                        ? `, ${day.weather.description}`
                        : ""}
                      {day.weather.humidity_pct != null &&
                        `, humidity ${day.weather.humidity_pct}%`}
                      {day.weather.wind_kph != null &&
                        `, wind ${day.weather.wind_kph} km/h`}
                      {day.weather_estimated &&
                        " ''' + em_dash + ''' estimated (beyond the 5-day forecast)"}
                    </p>
                  )}'''
    )

    text = replace_once(
        text,
        old_day_line,
        new_day_line,
        "per-day weather line: humidity/wind",
        name,
    )

    old_summary_line = (
        '''              {weather.city}: {weather.temp_c}''' + degree + '''C, {weather.description}
            </p>
          )}'''
    )

    new_summary_line = (
        '''              {weather.city}: {weather.temp_c}''' + degree + '''C, {weather.description}
              {weather.humidity_pct != null &&
                ` ''' + middle_dot + ''' humidity ${weather.humidity_pct}%`}
              {weather.wind_kph != null &&
                ` ''' + middle_dot + ''' wind ${weather.wind_kph} km/h`}
            </p>
          )}'''
    )

    text = replace_once(
        text,
        old_summary_line,
        new_summary_line,
        "top summary weather line: humidity/wind",
        name,
    )

    TRIP_PLANNER_JS.write_text(text, encoding="utf-8")
    print(f"{name}: all patches applied.")


if __name__ == "__main__":
    patch_weather_py()
    patch_outfit_recommendation_py()
    patch_auth_py()
    patch_app_py()
    patch_trip_planner_py()
    patch_profile_js()
    patch_outfit_recommendation_js()
    patch_trip_planner_js()
    print("\nDone.")