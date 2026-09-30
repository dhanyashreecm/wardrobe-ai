"""
TEN TRY-ONS A DAY, PER ACCOUNT.

WHAT THIS IS NOT
----------------
This is NOT the GPU allowance. The model runs on a free Hugging Face
Space with its own daily quota (see tryon_orchestrator), and that quota
belongs to the Space's account, not to any one user of this app. This
module adds a SEPARATE, app-level fairness limit on top of it: no
single account can spend the whole shared GPU allowance before anybody
else gets a turn. Raising the number here does not buy more GPU time.

WHY THE COUNT LIVES IN MONGO
----------------------------
Anywhere else and it would be trivially bypassed. In process memory it
resets when the backend restarts and differs between the two laptops.
In the browser it is editable by anyone who opens the developer tools.
In Mongo it is the same count whichever machine the user logs in from,
survives logout, restart and a change of device, and is read from the
JWT identity rather than anything the client sends.

HOW A RACE IS PREVENTED
-----------------------
Two simultaneous requests must not both see "9 used" and both proceed.
`reserve()` does the check and the increment in ONE atomic
find_one_and_update: the filter says "this day's row, with used < the
limit", and the update increments. The database applies those one at a
time, so the eleventh request matches nothing and is refused - there is
no window between reading and writing for a second request to slip
through. The document _id is derived from the account and the day, so
the upsert cannot create two rows for the same day either.

WHEN A DAY ENDS
---------------
At midnight in the application's own timezone, which is a fixed offset
from UTC (config.TRYON_RESET_OFFSET_HOURS, default +5:30 for India).

A fixed offset rather than a named zone on purpose: zoneinfo needs the
`tzdata` package on Windows and raises ZoneInfoNotFoundError without
it, so a named zone would work on the Mac and fail on the Windows
laptop - the two machines would disagree about what day it is, and the
user's count would appear to change when they switched computers. An
offset needs nothing installed and is identical everywhere.

NOBODY IS CHARGED FOR A FAILURE
-------------------------------
An attempt is reserved when the job starts and refunded whenever the
job ends in failure - a GPU quota refusal, a timeout, a sleeping Space,
a storage error, an unusable photo, anything. Only a try-on that
actually produced an image costs an attempt. That is both fairer and
simpler to explain than a list of which errors are the user's fault.
"""

from datetime import datetime, timedelta

from backend import config
from backend.db import db


usage_collection = db["tryon_usage"]


def _offset():
    return timedelta(hours=config.TRYON_RESET_OFFSET_HOURS)


def today(now=None):
    """
    The day this moment falls in, as "YYYY-MM-DD", in the application's
    timezone. `now` is UTC and exists so tests can pin it.
    """
    return ((now or datetime.utcnow()) + _offset()).strftime("%Y-%m-%d")


def next_reset(now=None):
    """
    When the current day's count resets, as a UTC datetime - so the
    browser can show a real time rather than a vague "tomorrow".
    """
    now = now or datetime.utcnow()
    local = now + _offset()
    midnight = (local + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return midnight - _offset()


def _key(user_email, day):
    # A deterministic _id is what makes the upsert safe: two concurrent
    # upserts for the same account and day contend for one document
    # instead of quietly creating two rows that each count separately.
    return f"{(user_email or '').strip().lower()}|{day}"


def snapshot(user_email, now=None):
    """
    What the interface should display. Never changes anything.
    """
    day = today(now)
    document = usage_collection.find_one({"_id": _key(user_email, day)})
    used = int((document or {}).get("used", 0))
    limit = config.TRYON_DAILY_LIMIT

    return {
        "used": min(used, limit),
        "limit": limit,
        "remaining": max(0, limit - used),
        "day": day,
        "resets_at": next_reset(now).isoformat() + "Z",
    }


def reserve(user_email, now=None):
    """
    Takes one attempt if the account has any left today.

    Returns (granted, snapshot). The snapshot always reflects the state
    AFTER the attempt, so a caller can hand it straight to the browser.

    The whole check-and-take is one database operation - see the
    docstring at the top for why that matters.
    """
    day = today(now)
    limit = config.TRYON_DAILY_LIMIT

    try:
        usage_collection.find_one_and_update(
            {"_id": _key(user_email, day), "used": {"$lt": limit}},
            {
                "$inc": {"used": 1},
                "$setOnInsert": {
                    "user_email": user_email,
                    "day": day,
                },
                "$set": {"updated_at": datetime.utcnow()},
            },
            upsert=True,
        )
    except Exception as error:  # noqa: BLE001
        # A duplicate-key error here is not a fault: it is Mongo saying
        # the row already exists but did NOT match "used < limit" - in
        # other words, the limit is reached. Any other database problem
        # is treated the same way, refusing rather than granting, since
        # an attempt we could not record is an attempt we cannot count.
        if type(error).__name__ != "DuplicateKeyError":
            print(f"Try-on usage could not be recorded: {type(error).__name__}")
        return False, snapshot(user_email, now)

    return True, snapshot(user_email, now)


def refund(user_email, day=None, now=None):
    """
    Gives back an attempt whose try-on failed.

    `day` is the day the attempt was TAKEN, stored on the job, so an
    attempt reserved at 23:59 and refunded at 00:01 is credited back to
    the day it came from rather than handed to the new day as a bonus.

    Guarded at zero: a refund can never take a count below nothing, so
    a double refund (a retry of the same failure, say) cannot mint
    attempts out of thin air.
    """
    day = day or today(now)

    try:
        usage_collection.update_one(
            {"_id": _key(user_email, day), "used": {"$gt": 0}},
            {"$inc": {"used": -1}, "$set": {"updated_at": datetime.utcnow()}},
        )
    except Exception as error:  # noqa: BLE001 - never break a failing job
        print(f"Try-on usage refund failed: {type(error).__name__}")


def limit_message(snap):
    """The sentence shown when the day's attempts are gone."""
    return (
        f"You've reached your daily Virtual Try-On limit of "
        f"{snap['limit']} attempts. Your attempts will reset tomorrow."
    )
