"""
ONE consolidated patch script covering everything outstanding:
  - new wardrobe categories (Denims, Footwear, Boots, Coat, Earrings,
    Neck Chain, Finger Ring, Hand Cuff, Head Accessory)
  - the Material field showing for Coat/Jacket
  - weather-aware scoring (Coat/Boots/wool -> cold-weather credit)
  - a real bug fix: several of the new categories were being
    silently dropped from every outfit (never crashing, just never
    showing up) because outfit_recommendation.py's bucketing never
    knew about them - this patches that too
  - the new multi-day weather FORECAST for the Trip Planner, so each
    day of a trip gets its own weather-appropriate outfit instead of
    one shared reading for the whole trip

Safe to run more than once - every step checks whether it's already
applied and skips it rather than double-patching or erroring.
"""
import pathlib

OUTFIT_PY = pathlib.Path("backend/outfit_recommendation.py")
WARDROBE_JS = pathlib.Path("frontend/src/pages/Wardrobe.js")
WEATHER_PY = pathlib.Path("backend/weather.py")
TRIP_PLANNER_PY = pathlib.Path("backend/trip_planner.py")
APP_PY = pathlib.Path("backend/app.py")
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


def replace_any(text, candidates, new, label, filename):
    """
    Like replace_once, but tries several possible "old" texts in
    order and uses whichever one is actually present - for a spot
    that different machines may have reached in different partial
    states (e.g. an earlier, narrower patch already added SOME of
    what belongs here, but not all of it). `new` is both the final
    replacement for whichever candidate matched AND the idempotency
    check (if it's already in the text, every candidate is skipped).
    """
    if new in text:
        print(f"{filename}: {label} - already applied, skipping.")
        return text
    for old in candidates:
        if old in text:
            return text.replace(old, new, 1)
    require(
        False,
        f"{filename}: could not find any expected variant for "
        f"'{label}' - nothing changed here. Tell Claude this happened.",
    )


# ================================================================
# 1. backend/outfit_recommendation.py
# ================================================================

def patch_outfit_recommendation_py():
    text = OUTFIT_PY.read_text(encoding="utf-8")
    name = "outfit_recommendation.py"

    text = replace_once(
        text,
        '''    "jean": {"casual", "day_outing", "college", "date"},
    "jeans": {"casual", "day_outing", "college", "date"},''',
        '''    "jean": {"casual", "day_outing", "college", "date"},
    "jeans": {"casual", "day_outing", "college", "date"},
    "denim": {"casual", "day_outing", "college", "date"},
    "denims": {"casual", "day_outing", "college", "date"},''',
        "Denims occasion tags",
        name,
    )

    text = replace_once(
        text,
        '''    "jacket": {"office", "interview", "date", "party", "day_outing"},
    "jackets": {"office", "interview", "date", "party", "day_outing"},''',
        '''    "jacket": {"office", "interview", "date", "party", "day_outing"},
    "jackets": {"office", "interview", "date", "party", "day_outing"},
    "coat": {"office", "interview", "date", "party", "day_outing"},
    "coats": {"office", "interview", "date", "party", "day_outing"},''',
        "Coat occasion tags",
        name,
    )

    text = replace_once(
        text,
        '''BOTTOM_MARKERS = {
    "pant", "pants", "trouser", "trousers", "jean", "jeans",
    "short", "shorts", "skirt", "skirts", "bottom", "bottoms",
    "legging", "leggings", "palazzo", "palazzos", "dhoti",
    "salwar", "salwars"
}''',
        '''BOTTOM_MARKERS = {
    "pant", "pants", "trouser", "trousers", "jean", "jeans",
    "denim", "denims", "short", "shorts", "skirt", "skirts",
    "bottom", "bottoms", "legging", "leggings", "palazzo",
    "palazzos", "dhoti", "salwar", "salwars"
}''',
        "BOTTOM_MARKERS fix (Denims was being dropped from every outfit)",
        name,
    )

    text = replace_once(
        text,
        '''ACCESSORY_MARKERS = {
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
}''',
        '''ACCESSORY_MARKERS = {
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
}''',
        "ACCESSORY_MARKERS/LAYER_MARKERS fix (Footwear/Boots/Coat/jewelry "
        "categories were being dropped from every outfit)",
        name,
    )

    text = replace_once(
        text,
        '''WARM_LAYER_MARKERS = {
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

    return points / len(items)''',
        '''WARM_LAYER_MARKERS = {
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
        "weather scoring (Coat/Boots/wool material)",
        name,
    )

    OUTFIT_PY.write_text(text, encoding="utf-8")
    print(f"{name}: all patches applied.")


# ================================================================
# 2. frontend/src/pages/Wardrobe.js
# ================================================================

def patch_wardrobe_js():
    text = WARDROBE_JS.read_text(encoding="utf-8")
    name = "Wardrobe.js"

    # ---- new categories ----
    # Two known starting shapes: either NONE of the new categories
    # exist yet, or an earlier, narrower patch already added the
    # original 7 (Denims/Footwear/Earrings/Neck Chain/Finger Ring/
    # Hand Cuff/Head Accessory) but not Boots, which came later.
    text = replace_any(
        text,
        [
            '''    ["Belt", "Belt", "unisex"],
    ["Jewelry", "Jewelry", "unisex"],
    // ---- men's ----''',
            '''    ["Belt", "Belt", "unisex"],
    ["Jewelry", "Jewelry", "unisex"],
    ["Denims", "Denims", "unisex"],
    ["Footwear", "Footwear", "unisex"],
    ["Earrings", "Earrings", "unisex"],
    ["Neck Chain", "Neck Chain", "unisex"],
    ["Finger Ring", "Finger Ring", "unisex"],
    ["Hand Cuff", "Hand Cuff", "unisex"],
    ["Head Accessory", "Head Accessory", "unisex"],
    // ---- men's ----''',
        ],
        '''    ["Belt", "Belt", "unisex"],
    ["Jewelry", "Jewelry", "unisex"],
    ["Denims", "Denims", "unisex"],
    ["Footwear", "Footwear", "unisex"],
    ["Boots", "Boots", "unisex"],
    ["Earrings", "Earrings", "unisex"],
    ["Neck Chain", "Neck Chain", "unisex"],
    ["Finger Ring", "Finger Ring", "unisex"],
    ["Hand Cuff", "Hand Cuff", "unisex"],
    ["Head Accessory", "Head Accessory", "unisex"],
    // ---- men's ----''',
        "new categories (Denims/Footwear/Boots/Earrings/etc)",
        name,
    )

    # ---- Coat next to Jacket ----
    text = replace_once(
        text,
        '''    ["Jacket", "Jacket", "unisex"],
    ["Bag", "Bag", "unisex"],''',
        '''    ["Jacket", "Jacket", "unisex"],
    ["Coat", "Coat", "unisex"],
    ["Bag", "Bag", "unisex"],''',
        "Coat category",
        name,
    )

    # ---- ACCESSORY_CATEGORIES + MATERIAL_CATEGORIES ----
    # Same two-shapes situation as above: either the short original
    # 4-item list, or the narrower patch's 10-item list (7 new
    # categories added, but no Boots, no MATERIAL_CATEGORIES yet).
    text = replace_any(
        text,
        [
            '''  const ACCESSORY_CATEGORIES = [
    "Bag",
    "Watch",
    "Belt",
    "Jewelry"
  ];''',
            '''  const ACCESSORY_CATEGORIES = [
    "Bag",
    "Watch",
    "Belt",
    "Jewelry",
    "Footwear",
    "Earrings",
    "Neck Chain",
    "Finger Ring",
    "Hand Cuff",
    "Head Accessory"
  ];''',
        ],
        '''  const ACCESSORY_CATEGORIES = [
    "Bag",
    "Watch",
    "Belt",
    "Jewelry",
    "Footwear",
    "Boots",
    "Earrings",
    "Neck Chain",
    "Finger Ring",
    "Hand Cuff",
    "Head Accessory"
    // NOTE: "Denims" is deliberately NOT in this list - it's a
    // bottom-wear clothing item (like Jean/Pant), not an accessory,
    // so it doesn't get the Material input and DOES get real
    // occasion filtering (see outfit_recommendation.CATEGORY_
    // OCCASION_AFFINITY's "denim"/"denims" entry) instead of the
    // "suitable for every occasion" default every category in this
    // list gets.
  ];

  // Real garments (not accessories) where the fabric still matters
  // for WEATHER matching specifically - a wool Coat/Jacket should
  // get the same "this is genuinely warm" credit as one photographed
  // clearly enough to look like a heavy winter piece. See
  // backend.outfit_recommendation._has_warm_material /
  // WARM_MATERIAL_MARKERS, which is what actually reads this value
  // ("wool", "fleece", "fur", ...) when scoring an outfit for cold
  // weather - this list only controls whether the Material input is
  // shown for these categories, it doesn't affect occasion tagging
  // the way ACCESSORY_CATEGORIES does.
  const MATERIAL_CATEGORIES = [
    "Coat",
    "Jacket"
  ];''',
        "ACCESSORY_CATEGORIES/MATERIAL_CATEGORIES",
        name,
    )

    # ---- Add-form Material field ----
    text = replace_once(
        text,
        '''            {/* MATERIAL (accessories only) */}

            {ACCESSORY_CATEGORIES.includes(
              category
            ) && (
              <input
                placeholder="Material (e.g. leather, gold, metal)"
                value={material}
                onChange={(e) =>
                  setMaterial(e.target.value)
                }
              />''',
        '''            {/* MATERIAL (accessories, plus Coat/Jacket where the
                fabric matters for weather matching - see
                MATERIAL_CATEGORIES above) */}

            {(ACCESSORY_CATEGORIES.includes(category) ||
              MATERIAL_CATEGORIES.includes(category)) && (
              <input
                placeholder="Material (e.g. leather, gold, metal, wool)"
                value={material}
                onChange={(e) =>
                  setMaterial(e.target.value)
                }
              />''',
        "Add-form Material field",
        name,
    )

    # ---- Edit-form Material field ----
    text = replace_once(
        text,
        '''                      {ACCESSORY_CATEGORIES.includes(
                        editCategory
                      ) && (
                        <input
                          placeholder="Material"
                          value={editMaterial}''',
        '''                      {(ACCESSORY_CATEGORIES.includes(editCategory) ||
                        MATERIAL_CATEGORIES.includes(editCategory)) && (
                        <input
                          placeholder="Material"
                          value={editMaterial}''',
        "Edit-form Material field",
        name,
    )

    WARDROBE_JS.write_text(text, encoding="utf-8")
    print(f"{name}: all patches applied.")


# ================================================================
# 3. backend/weather.py - full-file write (heavily rewritten, so a
#    find-and-replace patch would be more fragile than just writing
#    the whole thing). Guarded by an idempotency check.
# ================================================================

WEATHER_PY_CONTENT = '''import json
import os
import urllib.parse
import urllib.request


# ============================================================
# WEATHER SERVICE (OpenWeatherMap)
#
# Needs OPENWEATHER_API_KEY set in the environment. Get a free
# key at https://openweathermap.org/appid, then either:
#   export OPENWEATHER_API_KEY=your_key_here
# or add it to backend/.env (already gitignored) as:
#   OPENWEATHER_API_KEY=your_key_here
# and load it with python-dotenv, or any other env-loading setup.
# ============================================================

OPENWEATHER_API_KEY = os.environ.get("OPENWEATHER_API_KEY")

OPENWEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"

# OpenWeatherMap's FREE forecast endpoint - 3-hour steps, ~5 days out.
# There's no free endpoint that reliably forecasts further than this;
# a longer-range or hyper-local forecast needs a paid plan. See
# get_weather_forecast()'s docstring for how trip_planner.py copes
# with a trip that runs longer than this window.
OPENWEATHER_FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"
MAX_FORECAST_DAYS = 5

# Shared between get_weather() and get_weather_forecast() so "hot"/
# "cold"/"rainy" mean the same thing whether it's today's weather or
# a forecasted day - a trip that starts today and a trip that starts
# in 3 days should judge "is this a cold day" identically.
RAINY_CONDITIONS = ("rain", "drizzle", "thunderstorm")
HOT_THRESHOLD_C = 28
COLD_THRESHOLD_C = 15


def get_weather(city):
    """
    Fetch current weather for a city from OpenWeatherMap.

    Returns a dict:
        {
            "city": "Bengaluru",
            "temp_c": 27.4,
            "condition": "clouds",       # OpenWeatherMap's "main" field, lowercased
            "description": "few clouds",
            "is_rainy": False,
            "is_hot": False,
            "is_cold": False
        }

    Raises RuntimeError if no API key is configured, no city was
    given, or the request itself fails (bad city name, network
    issue, OpenWeatherMap error, etc). Callers should catch this
    and degrade gracefully rather than let it crash a request.
    """

    if not OPENWEATHER_API_KEY:
        raise RuntimeError(
            "Weather isn't configured yet - set OPENWEATHER_API_KEY "
            "in your environment."
        )

    if not city:
        raise RuntimeError("City is required.")

    params = urllib.parse.urlencode({
        "q": city,
        "appid": OPENWEATHER_API_KEY,
        "units": "metric"
    })

    url = f"{OPENWEATHER_URL}?{params}"

    try:

        with urllib.request.urlopen(url, timeout=8) as response:

            data = json.loads(
                response.read().decode("utf-8")
            )

    except Exception as e:

        raise RuntimeError(
            f"Could not fetch weather for '{city}': {e}"
        )

    weather_list = data.get("weather", [{}])

    condition = (
        weather_list[0].get("main", "")
        if weather_list
        else ""
    ).lower()

    description = (
        weather_list[0].get("description", "")
        if weather_list
        else ""
    )

    temp_c = data.get("main", {}).get("temp")

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
    }


def _hours_from_midday(dt_txt):
    """
    How many hours a "YYYY-MM-DD HH:MM:SS" timestamp is from 12:00 -
    used only to pick the single forecast entry that best represents
    a day's overall condition. Anything unparseable is treated as
    maximally far from midday, so it simply loses that comparison
    rather than crashing the whole forecast lookup over one odd entry.
    """
    try:
        hour = int(dt_txt[11:13])
    except (ValueError, IndexError):
        return 99
    return abs(hour - 12)


def get_weather_forecast(city):
    """
    Multi-day weather OUTLOOK for `city`, built from OpenWeatherMap's
    free 5-day/3-hour forecast endpoint but aggregated into ONE
    summary per CALENDAR DATE (not raw 3-hour blocks) - this is what
    lets trip_planner.py look a day up directly by its "YYYY-MM-DD"
    date instead of dealing with ~8 separate readings per day itself.

    Returns:
        {
            "city": "Manali",
            "by_date": {
                "2026-12-01": {
                    "city": "Manali",
                    "temp_c": 4.2,        # mean across that day's readings
                    "temp_min_c": 1.0,
                    "temp_max_c": 8.5,
                    "condition": "clouds",      # from the reading closest to midday
                    "description": "overcast clouds",
                    "is_rainy": False,          # True if ANY reading that day was rainy
                    "is_hot": False,
                    "is_cold": True
                },
                ...
            },
            "available_dates": ["2026-12-01", "2026-12-02", ...]  # sorted
        }

    Raises RuntimeError under the same conditions as get_weather() -
    no API key configured, no city given, or the request itself
    failing (bad city name, network issue, OpenWeatherMap error).
    Callers should catch this and degrade gracefully (e.g. fall back
    to get_weather() for a single current-weather reading) rather
    than let it crash a request.

    IMPORTANT LIMITATION: OpenWeatherMap's free tier only forecasts
    about MAX_FORECAST_DAYS days out. A trip that runs longer than
    that, or one whose dates simply fall outside this window, will
    have some (or all) of its dates missing from "by_date" - this
    function does NOT pad or invent those; it only returns what the
    API actually forecasted. trip_planner.py is what decides how to
    handle a missing date (falling back to the nearest available
    forecasted day rather than no weather info at all), since only
    it knows the full trip's day list.
    """

    if not OPENWEATHER_API_KEY:
        raise RuntimeError(
            "Weather isn't configured yet - set OPENWEATHER_API_KEY "
            "in your environment."
        )

    if not city:
        raise RuntimeError("City is required.")

    params = urllib.parse.urlencode({
        "q": city,
        "appid": OPENWEATHER_API_KEY,
        "units": "metric"
    })

    url = f"{OPENWEATHER_FORECAST_URL}?{params}"

    try:

        with urllib.request.urlopen(url, timeout=8) as response:

            data = json.loads(
                response.read().decode("utf-8")
            )

    except Exception as e:

        raise RuntimeError(
            f"Could not fetch weather forecast for '{city}': {e}"
        )

    resolved_city = data.get("city", {}).get("name", city)

    # Group the raw 3-hour entries by calendar date first ("dt_txt"
    # looks like "2026-12-01 12:00:00" - the date is always its
    # first 10 characters).
    entries_by_date = {}

    for entry in data.get("list", []):

        dt_txt = entry.get("dt_txt", "")

        if len(dt_txt) < 10:
            continue

        date_key = dt_txt[:10]

        entries_by_date.setdefault(date_key, []).append(entry)

    by_date = {}

    for date_key, entries in entries_by_date.items():

        temps = [
            entry["main"]["temp"]
            for entry in entries
            if entry.get("main", {}).get("temp") is not None
        ]

        if not temps:
            continue

        temp_c = sum(temps) / len(temps)
        temp_min_c = min(temps)
        temp_max_c = max(temps)

        # The reading closest to midday represents the day's
        # "condition" best (a 3am drizzle shouldn't be what a user
        # sees as "today's weather" if the afternoon is clear) - but
        # ANY rainy reading that day still marks the whole day rainy,
        # since a trip outfit needs to survive the worst part of the
        # day, not just its midpoint.
        midday_entry = min(
            entries,
            key=lambda entry: _hours_from_midday(entry.get("dt_txt", ""))
        )

        midday_weather = (midday_entry.get("weather") or [{}])[0]

        condition = midday_weather.get("main", "").lower()
        description = midday_weather.get("description", "")

        is_rainy = any(
            (entry.get("weather") or [{}])[0]
            .get("main", "")
            .lower() in RAINY_CONDITIONS
            for entry in entries
        )

        by_date[date_key] = {
            "city": resolved_city,
            "temp_c": round(temp_c, 1),
            "temp_min_c": round(temp_min_c, 1),
            "temp_max_c": round(temp_max_c, 1),
            "condition": condition,
            "description": description,
            "is_rainy": is_rainy,
            "is_hot": temp_max_c >= HOT_THRESHOLD_C,
            "is_cold": temp_max_c <= COLD_THRESHOLD_C,
        }

    return {
        "city": resolved_city,
        "by_date": by_date,
        "available_dates": sorted(by_date.keys()),
    }
'''


def patch_weather_py():
    name = "weather.py"
    marker = "def get_weather_forecast"

    text = WEATHER_PY.read_text(encoding="utf-8") if WEATHER_PY.exists() else ""

    if marker in text:
        print(f"{name}: already patched, skipping.")
        return

    WEATHER_PY.write_text(WEATHER_PY_CONTENT, encoding="utf-8")
    print(f"{name}: rewritten with per-day forecast support.")


# ================================================================
# 4. backend/trip_planner.py - full-file write, same reasoning as
#    weather.py above.
# ================================================================

TRIP_PLANNER_PY_CONTENT = '''from collections import defaultdict
from datetime import datetime, timedelta

from backend.outfit_recommendation import recommend_outfits, _outfit_item_ids


# ============================================================
# TRIP PLANNER
# ============================================================

MAX_TRIP_DAYS = 30


def _daterange(start_date, end_date):

    days = []
    current = start_date

    while current <= end_date:
        days.append(current)
        current += timedelta(days=1)

    return days


def _resolve_day_weather(day_iso, weather_by_date, fallback_weather):
    """
    The weather to score THIS day's outfit against, plus whether it
    had to be estimated.

    Preference order:
      1. An actual forecasted reading for this exact date, if the
         caller supplied a per-day forecast (weather_by_date - see
         backend.weather.get_weather_forecast) and this date is
         within it.
      2. The CLOSEST forecasted date available, if this date falls
         outside the forecast's window (OpenWeatherMap's free tier
         only covers ~5 days - a longer trip, or one starting further
         out, will have days past that). Reusing the nearest real
         reading is a far better guess than no weather info at all,
         since consecutive days in the same place are usually close
         in climate - but it's flagged "estimated" so callers (the
         frontend) can be honest about it rather than presenting it
         as an actual forecast for that day.
      3. `fallback_weather` - a single current-weather reading applied
         to every day, for when no per-day forecast was available at
         all (e.g. get_weather_forecast() itself failed). Also
         flagged "estimated" for the same reason.
      4. None, if nothing was available - recommend_outfits() already
         treats weather=None as "no weather nudge", not an error.
    """

    if weather_by_date:

        exact = weather_by_date.get(day_iso)

        if exact is not None:
            return exact, False

        available_dates = sorted(weather_by_date.keys())

        if available_dates:

            closest_date = min(
                available_dates,
                key=lambda available: abs(
                    (
                        datetime.strptime(available, "%Y-%m-%d").date()
                        - datetime.strptime(day_iso, "%Y-%m-%d").date()
                    ).days
                )
            )

            return weather_by_date[closest_date], True

    if fallback_weather:
        return fallback_weather, True

    return None, False


def plan_trip(
    wardrobe_items,
    destination,
    start_date,
    end_date,
    occasion="casual",
    weather=None,
    weather_by_date=None,
    account_gender=None
):
    """
    Build a day-by-day outfit plan for a trip, plus a packing
    checklist of the distinct wardrobe items used across it.

    start_date / end_date: "YYYY-MM-DD" strings.

    `weather_by_date` (new): a dict of "YYYY-MM-DD" -> weather dict
    (see backend.weather.get_weather_forecast's "by_date") - when
    given, each day of the trip is scored against ITS OWN forecasted
    weather rather than one shared value, so a 5-day trip that starts
    cold and turns rainy actually recommends different outfits for
    those different days. `weather` is the older single-reading
    fallback (see backend.weather.get_weather) - still supported, and
    used for any day `weather_by_date` doesn't cover (see
    _resolve_day_weather above).

    Raises ValueError for bad input (dates, trip too long, or not
    enough wardrobe items to build even one outfit) - callers
    should turn that into a 400 response rather than a crash.
    """

    try:
        start = datetime.strptime(
            start_date, "%Y-%m-%d"
        ).date()

        end = datetime.strptime(
            end_date, "%Y-%m-%d"
        ).date()

    except (TypeError, ValueError):
        raise ValueError(
            "start_date and end_date must be in YYYY-MM-DD format."
        )

    if end < start:
        raise ValueError(
            "End date must be on or after the start date."
        )

    days = _daterange(start, end)

    if len(days) > MAX_TRIP_DAYS:
        raise ValueError(
            f"Trips longer than {MAX_TRIP_DAYS} days aren't "
            "supported yet."
        )

    # A big enough pool, per day, for that day's own weather-scored
    # ranking to have real options to diversify across - a fixed 10
    # was fine when every day shared one outfit_pool, but a small
    # pool re-requested every day (see the loop below) needs to be
    # comfortably bigger than the trip so a long trip doesn't start
    # repeating outfits before it has to.
    pool_size = max(10, len(days) * 2)

    # Cross-day usage tracking - the same idea as
    # outfit_recommendation._diversify, just applied ACROSS separate
    # per-day recommend_outfits() calls instead of within one call,
    # since each day now needs its OWN weather-ranked pool (a cold
    # day and a hot day genuinely shouldn't share a ranking) while
    # still not putting the user in the same top three days running
    # if the wardrobe has other good options.
    usage_count = defaultdict(int)

    schedule = []
    packing_items = {}

    for index, day in enumerate(days):

        day_iso = day.isoformat()

        day_weather, weather_estimated = _resolve_day_weather(
            day_iso, weather_by_date, weather
        )

        day_pool = recommend_outfits(
            wardrobe_items,
            occasion=occasion,
            weather=day_weather,
            account_gender=account_gender,
            limit=pool_size
        )

        if not day_pool:
            raise ValueError(
                "Not enough wardrobe items to plan outfits for this "
                "occasion yet."
            )

        # Least-used-so-far wins (ties broken by that day's own
        # score, which already reflects day_weather) - same
        # trade-off _diversify makes within a single call, just
        # carried across the whole trip here.
        day_pool.sort(
            key=lambda candidate: (
                sum(
                    usage_count[item_id]
                    for item_id in _outfit_item_ids(candidate)
                ),
                -candidate["score"],
            )
        )

        outfit = day_pool[0]

        for item_id in _outfit_item_ids(outfit):
            usage_count[item_id] += 1

        schedule.append({
            "date": day_iso,
            "day_number": index + 1,
            "outfit": outfit,
            "weather": day_weather,
            "weather_estimated": weather_estimated
        })

        for item in outfit["items"]:

            item_id = item.get("_id")

            if item_id:
                packing_items[item_id] = item

    return {
        "destination": destination,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "duration_days": len(days),
        "schedule": schedule,
        "packing_list": list(packing_items.values())
    }
'''


def patch_trip_planner_py():
    name = "trip_planner.py"
    marker = "weather_by_date"

    text = TRIP_PLANNER_PY.read_text(encoding="utf-8") if TRIP_PLANNER_PY.exists() else ""

    if marker in text:
        print(f"{name}: already patched, skipping.")
        return

    TRIP_PLANNER_PY.write_text(TRIP_PLANNER_PY_CONTENT, encoding="utf-8")
    print(f"{name}: rewritten for per-day weather scoring.")


# ================================================================
# 5. backend/app.py
# ================================================================

def patch_app_py():
    text = APP_PY.read_text(encoding="utf-8")
    name = "app.py"

    text = replace_once(
        text,
        "from backend.weather import get_weather",
        "from backend.weather import get_weather, get_weather_forecast",
        "import get_weather_forecast",
        name,
    )

    text = replace_once(
        text,
        '''    # Weather for the destination is optional - a lookup failure
    # (no API key configured, unknown city, etc) should never
    # block the trip plan itself.
    weather = None
    weather_error = None

    if destination:

        try:

            weather = get_weather(destination)

        except Exception as e:

            weather_error = str(e)

    if not destination or not start_date or not end_date:

        return jsonify({
            "success": False,
            "message":
                "destination, start_date and end_date are required"
        }), 400

    try:

        wardrobe_items = get_user_wardrobe(
            user_email
        )

        trip_plan = plan_trip(
            wardrobe_items,
            destination,
            start_date,
            end_date,
            occasion=occasion,
            weather=weather,
            account_gender=account_gender
        )

    except ValueError as e:

        return jsonify({
            "success": False,
            "message": str(e)
        }), 400

    except Exception as e:

        print(f"Trip planning error: {e}")

        return jsonify({
            "success": False,
            "message": str(e)
        }), 500

    trip_id = save_trip(
        user_email,
        trip_plan
    )

    return jsonify({

        "success": True,

        "trip_id": trip_id,

        "trip": trip_plan,

        "weather": weather,

        "weather_error": weather_error

    }), 200''',
        '''    # Weather for the destination is optional - a lookup failure
    # (no API key configured, unknown city, etc) should never block
    # the trip plan itself. Two separate lookups:
    #   - `weather`: a single current-weather reading, shown as the
    #     one-line summary in the sidebar and used as the fallback
    #     for any day the forecast doesn't cover.
    #   - `weather_by_date`: the actual per-day forecast (see
    #     backend.weather.get_weather_forecast) - this is what lets
    #     each day of the trip get its OWN weather-appropriate
    #     outfit instead of every day sharing one reading. Only
    #     covers ~5 days out (OpenWeatherMap's free tier); days
    #     beyond that fall back inside plan_trip() itself.
    weather = None
    weather_error = None
    weather_by_date = None
    forecast_error = None

    if destination:

        try:

            weather = get_weather(destination)

        except Exception as e:

            weather_error = str(e)

        try:

            forecast = get_weather_forecast(destination)
            weather_by_date = forecast.get("by_date") or None

        except Exception as e:

            forecast_error = str(e)

    if not destination or not start_date or not end_date:

        return jsonify({
            "success": False,
            "message":
                "destination, start_date and end_date are required"
        }), 400

    try:

        wardrobe_items = get_user_wardrobe(
            user_email
        )

        trip_plan = plan_trip(
            wardrobe_items,
            destination,
            start_date,
            end_date,
            occasion=occasion,
            weather=weather,
            weather_by_date=weather_by_date,
            account_gender=account_gender
        )

    except ValueError as e:

        return jsonify({
            "success": False,
            "message": str(e)
        }), 400

    except Exception as e:

        print(f"Trip planning error: {e}")

        return jsonify({
            "success": False,
            "message": str(e)
        }), 500

    trip_id = save_trip(
        user_email,
        trip_plan
    )

    return jsonify({

        "success": True,

        "trip_id": trip_id,

        "trip": trip_plan,

        "weather": weather,

        "weather_error": weather_error,

        "forecast_error": forecast_error

    }), 200''',
        "/api/trips per-day forecast wiring",
        name,
    )

    APP_PY.write_text(text, encoding="utf-8")
    print(f"{name}: all patches applied.")


# ================================================================
# 6. frontend/src/pages/TripPlanner.js
# ================================================================

def patch_trip_planner_js():
    text = TRIP_PLANNER_JS.read_text(encoding="utf-8")
    name = "TripPlanner.js"

    # NOTE: the em dash / en dash / degree sign are built with chr()
    # from plain ASCII digits rather than written as literal
    # characters on purpose - a literal special character here can
    # get silently mangled into mojibake by a Windows copy/paste +
    # Notepad save round trip (this has happened before), which
    # would make this patch's "old" text fail to match the real file
    # even though the real file itself is fine. chr(0x2014) etc. is
    # plain ASCII in this .py file, so it survives that round trip
    # intact and Python reconstructs the real character when it runs.
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    degree = chr(0x00B0)

    old_block = (
        '''                  <h3>
                    Day {day.day_number} ''' + em_dash + ''' {day.date}
                  </h3>'''
    )

    new_block = (
        '''                  <h3>
                    Day {day.day_number} ''' + em_dash + ''' {day.date}
                  </h3>

                  {day.weather && (
                    <p
                      style={{
                        margin: "0 0 10px",
                        color: "#8a7a6d",
                        fontSize: "13px",
                      }}
                    >
                      {day.weather.temp_c}''' + degree + '''C
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

    text = replace_once(
        text,
        old_block,
        new_block,
        "per-day weather display",
        name,
    )

    TRIP_PLANNER_JS.write_text(text, encoding="utf-8")
    print(f"{name}: all patches applied.")


if __name__ == "__main__":
    patch_outfit_recommendation_py()
    patch_wardrobe_js()
    patch_weather_py()
    patch_trip_planner_py()
    patch_app_py()
    patch_trip_planner_js()
    print("\\nDone.")