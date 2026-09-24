"""
CENTRAL CONFIGURATION for Wardrobe-AI.

Every setting that differs between machines (the database, the image
storage account, the JWT signing secret, the weather API key) is read
from the ENVIRONMENT here, in one place, instead of being hardcoded in
the module that happens to need it. That is what makes two laptops run
the SAME application against the SAME data: both read their settings
from their own .env file, and both .env files point at one shared
MongoDB Atlas database and one shared Cloudinary account.

WHY A .env FILE AND NOT hardcoded values
-----------------------------------------
Before this module existed, db.py contained
"mongodb://localhost:27017/" literally, so every machine silently used
its OWN database - which is exactly how a user could upload clothes on
one laptop and see an empty wardrobe on another. A value that differs
per machine, or that is secret, belongs in .env (never committed - see
.gitignore), with .env.example committed in its place as a template.

WHAT IS REQUIRED vs OPTIONAL
-----------------------------
REQUIRED (the app refuses to start without them - see validate()):
    MONGODB_URI, MONGODB_DB_NAME, JWT_SECRET_KEY

The refusal is deliberate. The dangerous failure mode is NOT "the app
won't start"; it's "the app quietly started against a local database
and made a second, invisible copy of the user's wardrobe". A loud
error at startup is the honest outcome.

OPTIONAL (the app starts, and says clearly what is degraded):
    CLOUDINARY_CLOUD_NAME / CLOUDINARY_API_KEY / CLOUDINARY_API_SECRET
        All three together enable shared image storage. With any of
        them missing, uploads fall back to this machine's local disk -
        which still works for a single-machine demo, but those images
        will NOT be visible from another computer. storage.py reports
        this, /api/health reports this, and startup warns about it.
    OPENWEATHER_API_KEY
        Only weather-aware recommendations need it (see weather.py);
        everything else works without it.

Reading a value here never raises - call validate() to find out what
is missing, and let the caller decide whether that is fatal.
"""

import os
from pathlib import Path


# The project root - one level above backend/, i.e. the folder holding
# backend/, frontend/, and (on a configured machine) .env
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _parse_env_file(path):
    """
    Minimal KEY=VALUE reader for a .env file.

    Deliberately dependency-free rather than using python-dotenv: this
    runs before anything else in the app, on two machines whose pip
    environments have drifted apart before, and "the config loader
    itself failed to import" is a miserable error to debug. The format
    supported is the ordinary one:

        # comments and blank lines are ignored
        MONGODB_URI=mongodb+srv://user:pass@cluster.mongodb.net
        JWT_SECRET_KEY="quotes are optional and stripped"

    Anything unparseable is skipped rather than raising - a stray line
    in .env should not take the whole application down.
    """
    values = {}

    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return values

    for raw_line in text.splitlines():

        line = raw_line.strip()

        if not line or line.startswith("#"):
            continue

        # "export FOO=bar" is a common habit from shell scripts.
        if line.startswith("export "):
            line = line[len("export "):].strip()

        if "=" not in line:
            continue

        key, value = line.split("=", 1)

        key = key.strip()
        value = value.strip()

        # Strip one matching pair of surrounding quotes, if present.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]

        if key:
            values[key] = value

    return values


def load_env_files():
    """
    Loads .env into os.environ WITHOUT overwriting anything already
    set in the real environment.

    That precedence matters: a variable exported in the shell (or set
    by a hosting platform) should always beat the file on disk, so a
    developer can override one setting for one run without editing -
    and later forgetting to un-edit - their .env.

    Both <project root>/.env and backend/.env are read, in that order,
    because either location is a reasonable guess for someone setting
    this up for the first time.
    """
    for candidate in (PROJECT_ROOT / ".env", PROJECT_ROOT / "backend" / ".env"):

        if not candidate.is_file():
            continue

        for key, value in _parse_env_file(candidate).items():
            os.environ.setdefault(key, value)


load_env_files()


def _get(name, default=""):
    return os.environ.get(name, default).strip()


# ============================================================
# DATABASE - the single shared source of truth for accounts,
# wardrobes and trips (see db.py)
# ============================================================

MONGODB_URI = _get("MONGODB_URI")

# Named explicitly rather than taken from the URI's path, so the same
# cluster can safely host a separate database for experiments without
# anyone having to retype a connection string.
MONGODB_DB_NAME = _get("MONGODB_DB_NAME", "ai_wardrobe")


# ============================================================
# AUTHENTICATION
# ============================================================

# Signs every login token (see app.py). Changing it logs everyone out,
# which is the correct behaviour if it was ever exposed. It must NOT
# be a shared constant in source control: anyone holding it can mint a
# token for any account.
JWT_SECRET_KEY = _get("JWT_SECRET_KEY")


# ============================================================
# IMAGE STORAGE
# ============================================================

CLOUDINARY_CLOUD_NAME = _get("CLOUDINARY_CLOUD_NAME")
CLOUDINARY_API_KEY = _get("CLOUDINARY_API_KEY")
CLOUDINARY_API_SECRET = _get("CLOUDINARY_API_SECRET")


def cloudinary_configured():
    """
    True only when ALL THREE Cloudinary values are present - a partial
    configuration is treated as no configuration, because a half-set
    account produces an authentication error at upload time (i.e. when
    a user is waiting) instead of at startup.
    """
    return bool(
        CLOUDINARY_CLOUD_NAME
        and CLOUDINARY_API_KEY
        and CLOUDINARY_API_SECRET
    )


def storage_backend():
    """
    Which storage this machine will actually use: "cloudinary" (shared
    across machines) or "local" (this disk only). Read by storage.py
    and reported by /api/health.
    """
    return "cloudinary" if cloudinary_configured() else "local"


# ============================================================
# WEATHER (optional - see weather.py)
# ============================================================

OPENWEATHER_API_KEY = _get("OPENWEATHER_API_KEY")


# ============================================================
# VALIDATION
# ============================================================

# Kept as data rather than inline ifs so the same list drives both the
# startup check and the README - one place to change if a new required
# setting is ever added.
REQUIRED_SETTINGS = (
    (
        "MONGODB_URI",
        "the shared MongoDB Atlas connection string "
        "(mongodb+srv://...) that every machine must point at",
    ),
    (
        "MONGODB_DB_NAME",
        "the database name inside that cluster, e.g. ai_wardrobe",
    ),
    (
        "JWT_SECRET_KEY",
        "a long random string used to sign login tokens",
    ),
)


def missing_required():
    """
    Names/descriptions of any REQUIRED setting that is absent or blank.
    Empty tuple means the app has everything it needs to start.
    """
    return tuple(
        (name, description)
        for name, description in REQUIRED_SETTINGS
        if not _get(name)
    )


def warnings():
    """
    Non-fatal problems worth printing at startup: things that let the
    app run but silently reduce what works. Returned as plain strings,
    already phrased for a human reading a terminal.
    """
    found = []

    if not cloudinary_configured():
        found.append(
            "Cloudinary is not configured - wardrobe images will be saved "
            "to THIS computer's backend/uploads/ folder only, and will not "
            "be visible from another computer. Set CLOUDINARY_CLOUD_NAME, "
            "CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET in .env to fix."
        )

    if not OPENWEATHER_API_KEY:
        found.append(
            "OPENWEATHER_API_KEY is not set - outfit recommendations and "
            "trip planning will still work, but without weather awareness."
        )

    if MONGODB_URI.startswith("mongodb://localhost") or MONGODB_URI.startswith(
        "mongodb://127.0.0.1"
    ):
        found.append(
            "MONGODB_URI points at a LOCAL database on this computer. That "
            "is fine for solo development, but two computers using local "
            "databases will NOT share accounts or wardrobes - point both at "
            "the same MongoDB Atlas cluster for that."
        )

    return tuple(found)


def describe_startup():
    """
    The human-readable startup banner (what app.py prints). Shows which
    database and storage this process will actually use, and never
    prints a credential: the Mongo URI is reduced to its host, and no
    key or secret is included anywhere.
    """
    lines = ["Wardrobe-AI configuration:"]

    lines.append(f"  Database name : {MONGODB_DB_NAME or '(not set)'}")
    lines.append(f"  Database host : {safe_mongo_host()}")
    lines.append(f"  Image storage : {storage_backend()}")
    lines.append(
        f"  Weather       : {'configured' if OPENWEATHER_API_KEY else 'not configured'}"
    )

    return "\n".join(lines)


def safe_mongo_host():
    """
    Just the HOST part of MONGODB_URI - never the username, password,
    or query string. Safe to print in a log or return from /api/health,
    where a full connection string would leak the database password to
    anyone who can see the response.
    """
    if not MONGODB_URI:
        return "(not set)"

    remainder = MONGODB_URI.split("://", 1)[-1]

    # Drop credentials ("user:pass@host" -> "host").
    if "@" in remainder:
        remainder = remainder.split("@", 1)[1]

    # Drop path and query ("host/db?opts" -> "host").
    for separator in ("/", "?"):
        remainder = remainder.split(separator, 1)[0]

    return remainder or "(unknown)"


class ConfigurationError(RuntimeError):
    """Raised by validate() when a REQUIRED setting is missing."""


def validate(strict=True):
    """
    Checks configuration at startup.

    strict=True (what app.py uses) raises ConfigurationError listing
    every missing REQUIRED setting at once - not one at a time, so a
    first-time setup takes one round trip instead of three. Warnings
    are returned either way for the caller to print.

    The error text names the variables and points at .env.example
    rather than saying something unhelpful like "configuration error",
    because the person hitting it is usually setting the project up for
    the first time on a new machine.
    """
    missing = missing_required()

    if missing and strict:

        details = "\n".join(
            f"  - {name}: {description}" for name, description in missing
        )

        raise ConfigurationError(
            "Wardrobe-AI cannot start: required configuration is missing.\n"
            f"{details}\n\n"
            "Create a .env file in the project root (copy .env.example and "
            "fill in the real values), then start the backend again.\n"
            "The app deliberately does NOT fall back to a local database, "
            "because that silently gives each computer its own separate "
            "accounts and wardrobe - the exact problem this setup avoids."
        )

    return warnings()
