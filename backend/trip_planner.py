from collections import defaultdict
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
    account_gender=None,
    activity=None
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
    _resolve_day_weather above). `activity` (see
    outfit_recommendation.CANONICAL_ACTIVITIES) is an optional,
    purely additive ranking nudge applied to every day identically -
    same one-time choice as `occasion`, not a per-day setting.

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
            limit=pool_size,
            activity=activity
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
