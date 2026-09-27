"""
The single database connection every other backend module shares.

This used to be three lines pointing at "mongodb://localhost:27017/",
which meant each computer running this project talked to its OWN
database: an account registered on one laptop did not exist on the
other, and a wardrobe uploaded on one laptop was invisible from the
other. Both machines now read MONGODB_URI/MONGODB_DB_NAME from their
own .env (see config.py) and point at one shared MongoDB Atlas
cluster, so the account - not the computer - owns the wardrobe.

The collection names and document shapes are unchanged: "users",
"wardrobe" and "trips" behave exactly as before, so nothing that reads
or writes them needed to change.
"""

from pymongo import MongoClient

from backend import config

# Fail loudly and early if this machine has not been configured -
# see config.validate()'s docstring for why a silent fallback to a
# local database is the one outcome worth refusing.
config.validate(strict=True)

def _connection_options():
    """
    Extra MongoClient options this machine needs, decided at runtime.

    serverSelectionTimeoutMS: without it, an unreachable cluster
    (wrong password, IP not allow-listed in Atlas, laptop offline)
    leaves the first request hanging for ~30 seconds with no
    explanation. 8s is long enough for a slow connection to Atlas and
    short enough that a misconfiguration shows up as an error rather
    than as "the app is frozen".

    tlsCAFile: macOS ships Python with a TLS library that does not
    carry the certificate authorities Atlas presents, so connecting
    fails with

        SSL handshake failed: ... [SSL: TLSV1_ALERT_INTERNAL_ERROR]

    even though the URI, password and network access are all correct -
    which makes it look like an Atlas problem when it is a local
    certificate-store problem. Pointing pymongo at certifi's CA bundle
    (already installed here as a dependency) fixes it. Only applied
    for TLS connections, so a plain local mongodb:// URI is untouched,
    and skipped silently if certifi is missing rather than taking the
    app down over an optional import.
    """
    options = {"serverSelectionTimeoutMS": 8000}

    uri = config.MONGODB_URI or ""

    uses_tls = uri.startswith("mongodb+srv://") or "tls=true" in uri.lower() \
        or "ssl=true" in uri.lower()

    if uses_tls:
        try:
            import certifi
            options["tlsCAFile"] = certifi.where()
        except ImportError:
            print(
                "Note: certifi is not installed. If connecting to Atlas fails "
                "with an SSL handshake error, run: pip install certifi"
            )

    return options


client = MongoClient(config.MONGODB_URI, **_connection_options())

db = client[config.MONGODB_DB_NAME]

users_collection = db["users"]


def ping():
    """
    Checks the database is actually reachable RIGHT NOW, returning
    (ok, detail).

    MongoClient connects lazily, so merely constructing it above
    proves nothing - this is what /api/health calls to tell "the
    backend is running" apart from "the backend is running but cannot
    reach the database", which are very different problems to debug.

    The detail string is safe to show: it never contains the
    connection string, and therefore never the database password.
    """
    try:
        client.admin.command("ping")
        return True, "connected"
    except Exception as error:
        return False, f"{type(error).__name__}: {error}"


# ------------------------------------------------------------------
# INDEXES - the database-level guarantees behind "one email, one
# account" and "a migration never duplicates an item".
#
# Created by the running app at startup (see app.py's __main__) and by
# the migration/doctor scripts - never at import time, so importing
# this module (tests, scripts) never needs the network.
#
#   users.email            UNIQUE, case-insensitive (collation strength
#                          2): "Ganga@Gmail.com" and "ganga@gmail.com"
#                          can never be two accounts, even if two
#                          registrations race each other.
#   wardrobe.user_email    ordinary index for the per-account wardrobe
#   trips.user_email       and trip lookups every page makes.
#   wardrobe.migrated_from_id
#                          UNIQUE where present: a local item copied by
#                          migrate_to_atlas can exist at most once, even
#                          if the migration is re-run or run twice at once.
#
# Returns a list of human-readable problems (empty = all in place).
# An index that cannot be built because existing data violates it
# (e.g. two accounts already differ only by case) is reported, not
# forced - backend.account_doctor explains and repairs that safely.
# ------------------------------------------------------------------

EMAIL_INDEX_NAME = "email_unique_ci"


def ensure_indexes():
    problems = []

    specs = [
        (
            "users",
            [("email", 1)],
            {
                "name": EMAIL_INDEX_NAME,
                "unique": True,
                "collation": {"locale": "en", "strength": 2},
            },
        ),
        ("wardrobe", [("user_email", 1)], {"name": "user_email_1"}),
        ("trips", [("user_email", 1)], {"name": "user_email_1"}),
        (
            "wardrobe",
            [("migrated_from_id", 1)],
            {
                "name": "migrated_from_id_unique",
                "unique": True,
                "partialFilterExpression": {"migrated_from_id": {"$type": "string"}},
            },
        ),
    ]

    for collection, keys, options in specs:
        try:
            db[collection].create_index(keys, **options)
        except Exception as error:
            problems.append(
                f"{collection}.{options['name']}: {type(error).__name__}: "
                f"{str(error)[:200]}"
            )

    return problems
