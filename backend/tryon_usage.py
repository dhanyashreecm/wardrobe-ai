"""
FIVE SUCCESSFUL TRY-ONS A DAY, PER ACCOUNT.

Counted against the authenticated account (the JWT identity), never a
device, browser or anything the client sends. Only a generation that
produced a stored, viewable image is counted; every failure - provider
error, quota, cold start, timeout, network error, invalid input,
unusable response, our own storage - gives the attempt back.

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

WHO PAYS FOR A FAILURE: NOBODY, BUT NOT ALWAYS INSTANTLY
--------------------------------------------------------
Every reservation is also recorded as a HOLD: a small entry in the
day's row naming the job it belongs to. What happens to the hold
depends on what the server actually learned.

  settle()   The image exists. The hold is removed and the attempt
             stands as used. This is the only way an attempt is spent.

  release()  The failure is CONFIRMED and nothing was produced - the
             GPU allowance was refused, the Space is asleep, the photo
             is unusable, the garment unsupported, our own storage
             broke. The hold is removed and the count goes back down,
             in one atomic operation so it cannot credit twice.

  (nothing)  The outcome is UNCERTAIN: the request timed out, the
             connection broke, or the backend was killed in the middle.
             The model may well have finished the picture at the other
             end, so releasing immediately would let somebody collect
             images while paying for none of them. The hold simply
             stays, and release_stale_holds() gives the attempt back
             once the hold is older than
             config.TRYON_UNCERTAIN_HOLD_SECONDS - an hour by default,
             many times longer than any generation can take. By then
             the answer is in: no image came.

That last branch is also what saves an attempt when the backend
restarts mid-generation. The thread that would have released it is
gone, but the hold it left behind expires on its own.

A KNOWN LIMITATION
------------------
The provider (a Gradio Space) offers no "what happened to request X"
lookup and no idempotency key, so an uncertain outcome genuinely cannot
be resolved by asking it - the hold-and-expire above is the safe
substitute, not a reconciliation. If a provider that does support
status checks is added later, the right place to use it is here, before
release_stale_holds gives the attempt back.
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
    holds = len((document or {}).get("holds") or [])
    limit = config.TRYON_DAILY_LIMIT

    successful = max(0, used - holds)

    return {
        # Successful, stored images today. This is what the limit counts.
        "successful": min(successful, limit),
        "used": min(successful, limit),
        "limit": limit,
        # What the page shows ("4/5 try-ons remaining today"). Derived
        # from successful images only, so a generation that is still
        # running - or that fails - never decrements it.
        "remaining": max(0, limit - successful),
        # Attempts reserved for generations still running. reserve()
        # counts them (so the limit can never be exceeded by concurrent
        # requests), but they are not shown as used.
        "in_progress": holds,
        "day": day,
        "resets_at": next_reset(now).isoformat() + "Z",
    }


def reserve(user_email, now=None, hold_id=None):
    """
    Takes one attempt if the account has any left today.

    Returns (granted, snapshot). The snapshot always reflects the state
    AFTER the attempt, so a caller can hand it straight to the browser.

    `hold_id` is the job the attempt belongs to. Passing it records the
    attempt as a HOLD in the same operation, which is what later lets
    settle() confirm it, release() give it back, or - if the server
    never finds out what happened - release_stale_holds() expire it.
    Omitting it charges the attempt outright, which is what the older
    tests do.

    The whole check-and-take is one database operation - see the
    docstring at the top for why that matters.
    """
    day = today(now)
    limit = config.TRYON_DAILY_LIMIT

    update = {
        "$inc": {"used": 1},
        "$setOnInsert": {
            "user_email": user_email,
            "day": day,
        },
        "$set": {"updated_at": datetime.utcnow()},
    }

    if hold_id:
        update["$push"] = {
            "holds": {"job_id": str(hold_id), "at": now or datetime.utcnow()}
        }

    try:
        usage_collection.find_one_and_update(
            {"_id": _key(user_email, day), "used": {"$lt": limit}},
            update,
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


def settle(user_email, hold_id, day=None, now=None):
    """
    Confirms a hold: an image exists, so the attempt is genuinely spent.

    Only the hold entry is removed; `used` stays where it is. Called
    once a generation has finished and the image is stored, so that the
    expiry sweep below never hands the attempt back afterwards.
    """
    day = day or today(now)

    try:
        usage_collection.update_one(
            {"_id": _key(user_email, day), "holds.job_id": str(hold_id)},
            {
                "$pull": {"holds": {"job_id": str(hold_id)}},
                "$set": {"updated_at": datetime.utcnow()},
            },
        )
    except Exception as error:  # noqa: BLE001 - never break a finished job
        print(f"Try-on usage could not be settled: {type(error).__name__}")


def release(user_email, hold_id, day=None, now=None):
    """
    Gives an attempt back, for a CONFIRMED failure that produced nothing.

    Removing the hold and decrementing the count are one operation, and
    the filter requires the hold to still be there. So a second release
    of the same job - a retried error path, two threads, a sweep racing
    a thread - matches nothing and changes nothing. That is what stops
    attempts being minted out of thin air.

    Returns True if this call was the one that gave it back.
    """
    day = day or today(now)

    try:
        result = usage_collection.update_one(
            {
                "_id": _key(user_email, day),
                "holds.job_id": str(hold_id),
                "used": {"$gt": 0},
            },
            {
                "$pull": {"holds": {"job_id": str(hold_id)}},
                "$inc": {"used": -1},
                "$set": {"updated_at": datetime.utcnow()},
            },
        )
    except Exception as error:  # noqa: BLE001 - never break a failing job
        print(f"Try-on usage release failed: {type(error).__name__}")
        return False

    return bool(getattr(result, "modified_count", 0))


def release_stale_holds(user_email, now=None, day=None):
    """
    Gives back every attempt whose outcome was never learned and whose
    hold is now older than config.TRYON_UNCERTAIN_HOLD_SECONDS.

    This is the safe recovery for the cases nothing else can resolve: a
    timeout, a broken connection, a backend killed mid-generation. It
    waits long enough that a slow-but-alive generation is never
    cancelled out from under the user, and it touches no provider and
    costs no API call - just one indexed read and, only when something
    has actually expired, one small write each.

    Returns the number of attempts handed back.
    """
    now = now or datetime.utcnow()

    if day is None:
        # Both days, because a hold taken at 23:50 expires at 00:50 the
        # next day - by which time "today" is a different row, and the
        # attempt belongs to the day it came from.
        yesterday = today(now - timedelta(days=1))
        days = [today(now)]
        if yesterday not in days:
            days.append(yesterday)
        return sum(
            release_stale_holds(user_email, now=now, day=one) for one in days
        )

    cutoff = now - timedelta(seconds=config.TRYON_UNCERTAIN_HOLD_SECONDS)

    try:
        document = usage_collection.find_one({"_id": _key(user_email, day)})
    except Exception as error:  # noqa: BLE001
        print(f"Try-on usage sweep could not read: {type(error).__name__}")
        return 0

    given_back = 0

    for entry in (document or {}).get("holds") or []:
        taken_at = entry.get("at")
        if not isinstance(taken_at, datetime) or taken_at > cutoff:
            continue
        if release(user_email, entry.get("job_id"), day=day):
            given_back += 1

    if given_back:
        print(
            f"Returned {given_back} held try-on attempt(s) whose outcome "
            f"never arrived."
        )

    return given_back


def limit_message(snap):
    """The sentence shown when the day's attempts are gone."""
    return (
        f"You've used all {snap['limit']} of today's virtual try-ons. "
        f"Your allowance resets to {snap['limit']} tomorrow."
    )
