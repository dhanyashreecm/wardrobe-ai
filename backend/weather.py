import json
import os
import urllib.parse
import urllib.request

from backend import config


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

# Read through config so the key can live in the project's .env file
# alongside every other setting, instead of having to be exported by
# hand in each terminal window before starting the backend. config
# imports nothing from this module, so there is no import cycle, and
# an explicitly exported shell variable still wins over the file (see
# config.load_env_files).
OPENWEATHER_API_KEY = config.OPENWEATHER_API_KEY

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

# Wind/humidity thresholds - same reasoning as HOT/COLD above: a
# single shared cutoff so "windy"/"humid" mean the same thing for a
# current reading and a forecasted day. OpenWeatherMap's "metric"
# units give wind speed in m/s, which nobody thinks in, so it's
# converted to km/h (kph) for anything shown to the user or reasoned
# about here - 20 kph (~5.5 m/s) is a "you'll feel it" breeze, not a
# storm.
WINDY_THRESHOLD_KPH = 20
HUMID_THRESHOLD_PCT = 70
MPS_TO_KPH = 3.6


def get_weather(city):
    """
    Fetch current weather for a city from OpenWeatherMap.

    Returns a dict:
        {
            "city": "Bengaluru",
            "temp_c": 27.4,
            "condition": "clouds",       # OpenWeatherMap's "main" field, lowercased
            "description": "few clouds",
            "humidity_pct": 55,          # None if OpenWeatherMap didn't send one
            "wind_kph": 11.2,            # None if OpenWeatherMap didn't send one
            "is_rainy": False,
            "is_hot": False,
            "is_cold": False,
            "is_windy": False
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
                    "humidity_pct": 62,         # mean across that day's readings
                    "wind_kph": 14.4,           # max across that day's readings
                    "is_rainy": False,          # True if ANY reading that day was rainy
                    "is_hot": False,
                    "is_cold": True,
                    "is_windy": False
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
        )

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
            "humidity_pct": humidity_pct,
            "wind_kph": wind_kph,
            "is_rainy": is_rainy,
            "is_hot": temp_max_c >= HOT_THRESHOLD_C,
            "is_cold": temp_max_c <= COLD_THRESHOLD_C,
            "is_windy": (
                wind_kph is not None
                and wind_kph >= WINDY_THRESHOLD_KPH
            ),
        }

    return {
        "city": resolved_city,
        "by_date": by_date,
        "available_dates": sorted(by_date.keys()),
    }
