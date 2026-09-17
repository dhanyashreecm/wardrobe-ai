from datetime import datetime, timedelta

from backend.outfit_recommendation import recommend_outfits


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


def plan_trip(
    wardrobe_items,
    destination,
    start_date,
    end_date,
    occasion="casual",
    weather=None,
    account_gender=None
):
    """
    Build a day-by-day outfit plan for a trip, plus a packing
    checklist of the distinct wardrobe items used across it.

    start_date / end_date: "YYYY-MM-DD" strings.

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

    # A ranked pool of outfit options, generated once and reused
    # per day (cycled if the trip is longer than the pool) so a
    # longer trip degrades to outfit repeats instead of failing.
    outfit_pool = recommend_outfits(
        wardrobe_items,
        occasion=occasion,
        weather=weather,
        account_gender=account_gender
    )

    if not outfit_pool:
        raise ValueError(
            "Not enough wardrobe items to plan outfits for this "
            "occasion yet."
        )

    schedule = []
    packing_items = {}

    for index, day in enumerate(days):

        outfit = outfit_pool[
            index % len(outfit_pool)
        ]

        schedule.append({
            "date": day.isoformat(),
            "day_number": index + 1,
            "outfit": outfit
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
