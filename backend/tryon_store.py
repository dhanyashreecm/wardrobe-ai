"""
WHERE TRY-ON PHOTOS AND RESULTS LIVE.

Two new collections, both keyed on user_email exactly like "wardrobe"
and "trips" already are, so a photo uploaded on one computer is
available on the other and the account - not the machine - owns it.

    tryon_photos    the current photo of the user. One per account:
                    uploading a new one replaces the old.
    tryon_results   one document per generation, holding its status
                    while it runs and its image URL when it finishes.

EVERY FUNCTION HERE TAKES user_email AND FILTERS ON IT.

That is not defensive habit, it is the security model. A generated
try-on is a picture of somebody's body; the id of one is a short hex
string that appears in URLs. If any query here matched on id alone,
changing one character of a URL would show you a stranger's photo.
There is deliberately no function in this module that can fetch a
document without knowing whose it is.

WHY STATUS LIVES IN THE DATABASE

Generation takes 20-60 seconds - longer for a full outfit, which is
two passes. Holding an HTTP request open that long breaks on every
proxy and looks like a hung app, so the route starts a background
thread and returns an id, and the browser polls. Putting the status in
Mongo rather than in process memory means it survives a backend
restart, and means the other computer can see the result too.
"""

import uuid
from datetime import datetime

from backend.db import db


photos_collection = db["tryon_photos"]

results_collection = db["tryon_results"]


# A job that never reached a terminal state - the backend was killed
# mid-generation, say - should not spin forever in the interface.
STALE_AFTER_SECONDS = 15 * 60

PENDING = "pending"
RUNNING = "running"
DONE = "done"
FAILED = "failed"


# ============================================================
# THE USER'S PHOTO
# ============================================================

def set_photo(user_email, image_url, details=None, width=None, height=None):
    """
    Records the user's current try-on photo, replacing any previous
    one. Returns the stored document.

    The previous document's storage id is returned to the caller so it
    can delete the old image from Cloudinary - this module does not
    touch storage itself, so that there is exactly one place (app.py)
    deciding when bytes are destroyed.
    """
    now = datetime.utcnow()

    previous = photos_collection.find_one({"user_email": user_email})

    document = {
        "user_email": user_email,
        "image_url": image_url,
        "public_id": (details or {}).get("public_id"),
        "backend": (details or {}).get("backend"),
        "local_path": (details or {}).get("local_path"),
        "width": width,
        "height": height,
        "updated_at": now,
    }

    photos_collection.replace_one(
        {"user_email": user_email}, document, upsert=True
    )

    return document, previous


def get_photo(user_email):
    """The user's current photo, or None."""
    return photos_collection.find_one({"user_email": user_email})


def delete_photo(user_email):
    """
    Forgets the user's photo and returns the document that was
    removed, so the caller can delete the image itself.
    """
    existing = photos_collection.find_one({"user_email": user_email})

    if not existing:
        return None

    photos_collection.delete_one({"user_email": user_email})

    return existing


# ============================================================
# GENERATION JOBS AND THEIR RESULTS
# ============================================================

def new_job_id():
    """
    A fresh job id, which the caller may want BEFORE the job exists -
    the daily allowance records its hold against this id, and the hold
    has to be taken before any job is created.

    A random uuid rather than a Mongo ObjectId because it goes in URLs
    the browser polls, and an ObjectId leaks roughly when it was
    created and roughly how many exist.
    """
    return uuid.uuid4().hex


def create_job(user_email, item_ids, source="manual", occasion="", label="",
               job_id=None, usage_day=None, request_id=None):
    """
    Opens a job in the PENDING state and returns its id.

    `usage_day` is the day the attempt was taken from, kept on the job
    so any later correction credits the right day.

    `request_id` is the browser's own identifier for one submission. It
    is stored so that the same submission arriving twice - a
    double-click that outran the disabled button, a retry after a
    connection dropped mid-request - finds the job it already started
    instead of beginning a second one and spending a second attempt.
    """
    job_id = job_id or new_job_id()

    document = {
        "job_id": job_id,
        "user_email": user_email,
        "usage_day": usage_day,
        "request_id": request_id,
        # True until something says otherwise. A confirmed failure sets
        # it False, which is how the page can say "this didn't use one
        # of your attempts" and mean it.
        "attempt_charged": True,
        "status": PENDING,
        "progress": "Queued",
        "step": 0,
        "total_steps": 0,
        "item_ids": [str(identifier) for identifier in item_ids],
        "source": source,
        "occasion": occasion,
        "label": label,
        "image_url": None,
        "public_id": None,
        "worn": [],
        "not_applied": [],
        "error": None,
        "created_at": datetime.utcnow(),
        "finished_at": None,
    }

    try:
        results_collection.insert_one(document)
    except Exception as error:  # noqa: BLE001
        if type(error).__name__ != "DuplicateKeyError":
            raise
        # The unique index on (user_email, request_id) just told us that
        # this exact submission created a job a fraction of a second
        # ago, in another request we had already checked for and not
        # seen. The database settles the race rather than a check that
        # could be overtaken: we return the job that won, and the
        # caller gives back the attempt it had reserved for this one.
        existing = find_by_request_id(user_email, request_id)
        if existing:
            return existing["job_id"]
        raise

    return job_id


def update_job(job_id, user_email, **fields):
    """
    Changes a job the given user owns. A job id alone is never enough.
    """
    fields["updated_at"] = datetime.utcnow()

    results_collection.update_one(
        {"job_id": job_id, "user_email": user_email},
        {"$set": fields},
    )


def mark_running(job_id, user_email, step, total, message):
    update_job(
        job_id, user_email,
        status=RUNNING, step=step, total_steps=total, progress=message,
    )


def mark_done(job_id, user_email, image_url, details, report):
    update_job(
        job_id, user_email,
        status=DONE,
        progress="Finished",
        image_url=image_url,
        public_id=(details or {}).get("public_id"),
        backend=(details or {}).get("backend"),
        local_path=(details or {}).get("local_path"),
        worn=(report or {}).get("worn", []),
        not_applied=(report or {}).get("not_applied", []),
        passes=(report or {}).get("passes", 0),
        provider=(report or {}).get("provider", ""),
        providers=(report or {}).get("providers", []),
        fallback_used=bool((report or {}).get("fallback_used")),
        finished_at=datetime.utcnow(),
    )


def mark_failed(job_id, user_email, message, code=None, charged=None,
                outcome=None):
    """
    `message` is shown to the user, so callers must pass the safe
    sentence, never a raw exception - a provider's error text can
    contain the access token that was sent with the request.

    `charged` says whether this failure cost the user an attempt, and
    `outcome` whether the failure is confirmed or merely uncertain -
    both so the page can tell the truth about the allowance instead of
    implying the day's attempts were wasted.
    """
    extra = {}
    if charged is not None:
        extra["attempt_charged"] = bool(charged)
    if outcome is not None:
        extra["outcome"] = outcome

    update_job(
        job_id, user_email,
        status=FAILED,
        progress="",
        error=message,
        **extra,
        # A state name (QUOTA_EXHAUSTED, TIMEOUT...) so the page can offer
        # the right next step. Never a provider name or raw error text.
        error_code=code,
        finished_at=datetime.utcnow(),
    )


def find_by_request_id(user_email, request_id):
    """
    The job this browser submission already started, if any.

    This is the idempotency check: the same request_id must never buy a
    second generation. Scoped to the owner like everything else here,
    so one account's identifier can never reach another's job.
    """
    if not request_id:
        return None

    return results_collection.find_one({
        "user_email": user_email, "request_id": str(request_id)
    })


def active_jobs(user_email):
    """
    The user's try-ons that are still running, abandoned ones excluded.

    Used to refuse a second simultaneous generation: one person should
    not be able to spend two of the day's attempts, and two runs of a
    shared free GPU, at the same moment from two tabs or two laptops.
    """
    running = results_collection.find({
        "user_email": user_email, "status": {"$in": [PENDING, RUNNING]}
    })

    alive = []

    for job in running:
        checked = _mark_stale_if_abandoned(job)
        if checked and checked.get("status") in (PENDING, RUNNING):
            alive.append(checked)

    return alive


def get_job(job_id, user_email):
    """
    One job belonging to this user, or None - including when the job
    exists but belongs to someone else, which is the point.
    """
    job = results_collection.find_one(
        {"job_id": job_id, "user_email": user_email}
    )

    if not job:
        return None

    return _mark_stale_if_abandoned(job)


def _mark_stale_if_abandoned(job):
    """
    Turns a job the backend died in the middle of into a failure, so
    the interface stops waiting for something that will never arrive.
    """
    if job.get("status") not in (PENDING, RUNNING):
        return job

    started = job.get("created_at")

    if not started:
        return job

    age = (datetime.utcnow() - started).total_seconds()

    if age < STALE_AFTER_SECONDS:
        return job

    mark_failed(
        job["job_id"], job["user_email"],
        "This try-on was interrupted - the server restarted while it was "
        "running. Please start it again.",
        # Uncertain, not confirmed: the model may have finished the
        # picture after this server stopped listening. The attempt is
        # still held, and tryon_usage returns it by itself once the
        # hold is older than any generation could be.
        charged=True, outcome="uncertain",
    )

    return results_collection.find_one(
        {"job_id": job["job_id"], "user_email": job["user_email"]}
    )


def list_results(user_email, limit=30, finished_only=True):
    """The user's try-ons, newest first."""
    query = {"user_email": user_email}

    if finished_only:
        query["status"] = DONE

    return list(
        results_collection.find(query).sort("created_at", -1).limit(limit)
    )


def delete_result(job_id, user_email):
    """
    Removes one of the user's try-ons and returns the document, so the
    caller can delete the image itself.
    """
    existing = results_collection.find_one(
        {"job_id": job_id, "user_email": user_email}
    )

    if not existing:
        return None

    results_collection.delete_one(
        {"job_id": job_id, "user_email": user_email}
    )

    return existing


def delete_all_for_user(user_email):
    """
    Everything this account has in both collections. Called when an
    account is deleted, alongside the wardrobe and trip equivalents -
    a deleted account must not leave photographs of a person behind.
    """
    photos = list(photos_collection.find({"user_email": user_email}))
    results = list(results_collection.find({"user_email": user_email}))

    photos_collection.delete_many({"user_email": user_email})
    results_collection.delete_many({"user_email": user_email})

    return photos + results


def public_view(document):
    """
    A job as the browser should see it: no Mongo _id, no storage
    identifiers, no local filesystem paths, and never the owner's
    email - the client already knows who it is, and echoing an address
    back into JSON is how one leaks into a log or a screenshot. Which
    provider or model produced the image is not shown either - it means
    nothing to the person looking at their outfit.
    """
    if not document:
        return None

    return {
        "job_id": document.get("job_id"),
        "status": document.get("status"),
        "progress": document.get("progress", ""),
        "step": document.get("step", 0),
        "total_steps": document.get("total_steps", 0),
        "image_url": document.get("image_url"),
        "worn": document.get("worn", []),
        "not_applied": document.get("not_applied", []),
        "passes": document.get("passes", 0),
        "source": document.get("source", ""),
        "occasion": document.get("occasion", ""),
        "label": document.get("label", ""),
        "error": document.get("error"),
        "error_code": document.get("error_code"),
        # Whether this try-on cost one of the day's attempts, and -
        # when it failed - whether the failure is confirmed or still
        # uncertain. The page needs both to avoid telling somebody
        # their attempt is gone when it isn't.
        "attempt_charged": bool(document.get("attempt_charged", True)),
        "outcome": document.get("outcome"),
        # A generic note only - which provider it was is not shown.
        "notice": (
            "Made with another available try-on service because the "
            "primary one was unavailable."
            if document.get("fallback_used") else None
        ),
        "created_at": (
            document["created_at"].isoformat()
            if document.get("created_at") else None
        ),
    }
