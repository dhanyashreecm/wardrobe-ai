import json
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
        "is_rainy": condition in (
            "rain",
            "drizzle",
            "thunderstorm"
        ),
        "is_hot": (
            temp_c is not None
            and temp_c >= 28
        ),
        "is_cold": (
            temp_c is not None
            and temp_c <= 15
        )
    }
