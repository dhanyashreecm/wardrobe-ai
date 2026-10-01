"""
Sets one value in .env without editing the file by hand.

    python -m backend.set_secret CLOUDINARY_API_SECRET

It prompts for the value with the input HIDDEN (like a password
prompt), so the secret never appears on screen, never lands in shell
history, and never has to be pasted into a chat window. It then
rewrites .env with exactly one line per setting, leaving every other
value untouched.

Why this exists: a .env edited by hand late at night is a .env with
terminal output accidentally pasted into it - which is exactly what
happened to this project's .env once, leaving 44 junk lines and a
duplicate of every setting. Going through this script makes that
impossible.

    python -m backend.set_secret --list       # what is set, no values
"""

import getpass
import os
import re
import shutil
import sys
from datetime import datetime


SETTINGS = [
    "MONGODB_URI",
    "MONGODB_DB_NAME",
    "JWT_SECRET_KEY",
    "CLOUDINARY_CLOUD_NAME",
    "CLOUDINARY_API_KEY",
    "CLOUDINARY_API_SECRET",
    "OPENWEATHER_API_KEY",
    # Outgoing mail - the welcome and sign-in messages. SMTP_PASSWORD
    # is a Gmail App Password, not an account password.
    "SMTP_USERNAME",
    "SMTP_PASSWORD",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_FROM_NAME",
    # Virtual try-on. The Space id is not secret; the token is.
    "TRYON_SPACE_ID",
    "HUGGINGFACE_API_TOKEN",
    # The https share link printed by spaces/tryon/colab_tryon.ipynb -
    # the self-hosted fallback provider.
    "TRYON_FALLBACK_URL",
    # "Shop this look" product search (Google Lens via SerpApi).
    "SERPAPI_API_KEY",
]

# Names this script does not manage but must not destroy when it
# rewrites the file. Anything in .env that looks like a real setting
# (an uppercase name, an "=", a value) is carried through - see
# read_extras() - so a hand-added SEND_LOGIN_EMAIL=false survives.
EXTRA_KEY = re.compile(r"^[A-Z][A-Z0-9_]*$")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(PROJECT_ROOT, ".env")


def _pairs():
    """Every KEY=VALUE line in .env, ignoring comments and junk."""
    if not os.path.isfile(ENV_PATH):
        return

    for raw in open(ENV_PATH, encoding="utf-8"):
        line = raw.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)

        yield key.strip(), value.strip()


def read_settings():
    """Current values of the settings this script manages."""
    return {key: value for key, value in _pairs() if key in SETTINGS}


def read_extras():
    """
    Settings in .env that this script does NOT manage.

    Without this, rewriting the file would quietly delete anything
    added by hand - SEND_LOGIN_EMAIL, say - and the user would be
    left wondering why a setting they set stopped taking effect. The
    uppercase-name test is what separates a real setting from the
    terminal output that once got pasted into this file.
    """
    return {
        key: value
        for key, value in _pairs()
        if key not in SETTINGS and EXTRA_KEY.match(key)
    }


def describe(value):
    """A safe description of a value - never the value itself."""
    if not value:
        return "not set"

    if set(value) <= set("*•.xX"):
        return f"{len(value)} chars - looks like a MASK, not a real value"

    return f"{len(value)} chars, set"


def write_settings(values):
    """
    Rewrites .env with one line per setting. The previous file is kept
    as a timestamped backup, because overwriting the only copy of
    someone's credentials is not a recoverable mistake.
    """
    if os.path.isfile(ENV_PATH):
        backup = f"{ENV_PATH}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.copy2(ENV_PATH, backup)
        print(f"  previous .env saved as {os.path.basename(backup)}")

    lines = [
        "# Wardrobe-AI configuration - never commit this file.",
        "# Set values with: python -m backend.set_secret <NAME>",
        "",
    ]

    for key in SETTINGS:
        lines.append(f"{key}={values.get(key, '')}")

    extras = read_extras()

    if extras:
        lines.append("")
        lines.append("# Other settings found in this file, preserved as-is.")
        for key in sorted(extras):
            lines.append(f"{key}={extras[key]}")

    with open(ENV_PATH, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def mongo_host(value):
    """
    Just the host part of a connection string - no username, no
    password. Printed back after a write so the person can confirm
    they pasted the right thing without the secret appearing on
    screen. Deliberately a local copy of config.safe_mongo_host's
    logic so this script stays runnable even when config cannot load.
    """
    remainder = value.split("://", 1)[-1]

    if "@" in remainder:
        remainder = remainder.split("@", 1)[1]

    for separator in ("/", "?"):
        remainder = remainder.split(separator, 1)[0]

    return remainder or "(unknown)"


def shape_problem(name, value):
    """
    Why this value cannot possibly be right, or "" if it might be.

    Only refuses what is definitely wrong. The point is to fail HERE,
    while the person is still looking at the prompt and knows what
    they just pasted, instead of three commands later as an
    authentication error that looks like a server problem.

    This exists because a partial copy of a connection string was
    accepted without complaint - 29 characters where 103 were needed -
    and the failure only surfaced later as a connection error.
    """
    if name == "MONGODB_URI":

        if not value.startswith(("mongodb+srv://", "mongodb://")):
            return (
                "A MongoDB connection string starts with 'mongodb+srv://' "
                "(Atlas) or 'mongodb://' (a local database). This one does "
                "not, so only part of it was copied - or something else was "
                "copied instead."
            )

        # The remaining two checks apply to Atlas strings only. A
        # local "mongodb://localhost:27017/wardrobe_db" is a perfectly
        # valid setting for solo development: it is short, and it has
        # no credentials in it, so neither test below would suit it.
        if value.startswith("mongodb+srv://"):

            if "@" not in value:
                return (
                    "This connection string has no '@' in it, so it is "
                    "missing the username and password part. Atlas gives you "
                    "the whole string under Connect -> Drivers - copy all "
                    "of it."
                )

            if len(value) < 50:
                return (
                    f"This is only {len(value)} characters. A real Atlas "
                    "connection string is around 100 - it looks like the "
                    "copy was cut short."
                )

    if name == "MONGODB_DB_NAME":

        if "/" in value or "@" in value or " " in value:
            return (
                "A database name is a single plain word, like 'ai_wardrobe' "
                "- this looks like a whole connection string or a path."
            )

    if name == "TRYON_FALLBACK_URL":

        host = value[len("https://"):].strip("/") if value.startswith("https://") else ""

        if not host or "." not in host:
            return (
                "The fallback must be the full https:// link the notebook "
                "prints, like https://abc123def456.gradio.live"
            )

    if name == "TRYON_SPACE_ID":

        # Two valid shapes, because there are two ways to host the
        # model. A Hugging Face Space is "owner/space-name". A Gradio
        # app running anywhere else - notably a free Colab GPU, which
        # is what you use when a Hugging Face account is too new to
        # get ZeroGPU - is a full https URL. gradio_client accepts
        # either, so this accepts either.
        if value.startswith("https://"):

            host = value[len("https://"):].strip("/")

            if not host or "." not in host:
                return (
                    "That is not a complete address. A Gradio share link "
                    "looks like https://abc123def456.gradio.live"
                )

            return ""

        if value.startswith("http://"):
            return (
                "Use the https:// address, not http:// - the share link "
                "Gradio prints is always https."
            )

        if value.count("/") != 1 or value.startswith("/") or value.endswith("/"):
            return (
                "This should be either a Hugging Face Space id "
                "('your-name/your-space-name') or a full https:// Gradio "
                "share link."
            )

    if name == "HUGGINGFACE_API_TOKEN" and not value.startswith("hf_"):
        return (
            "A Hugging Face access token starts with 'hf_'. Create one at "
            "huggingface.co/settings/tokens with read permission."
        )

    if name == "SMTP_USERNAME" and "@" not in value:
        return (
            "This should be the full email address the mail is sent from, "
            "including the part after the '@'."
        )

    return ""


def main():

    arguments = sys.argv[1:]

    values = read_settings()

    if not arguments or arguments[0] in ("--list", "-l"):
        print(f"\n{ENV_PATH}\n")
        for key in SETTINGS:
            print(f"  {key:24s} {describe(values.get(key, ''))}")
        print("\nSet one with:  python -m backend.set_secret CLOUDINARY_API_SECRET")
        return 0

    name = arguments[0].strip().upper()

    if name not in SETTINGS:
        print(f"'{name}' is not one of this project's settings.")
        print("Valid names: " + ", ".join(SETTINGS))
        return 1

    print(f"\nSetting {name}")
    print(f"  currently: {describe(values.get(name, ''))}")
    print("\nPaste the value and press Enter. It will NOT be shown as you type.")

    value = getpass.getpass("  value: ").strip()

    if not value:
        print("\nNothing entered - .env was not changed.")
        return 1

    if set(value) <= set("*•.xX"):
        print(
            "\nThat looks like the row of asterisks the dashboard shows to "
            "HIDE the secret, not the secret itself."
            "\nClick the reveal (eye) or copy button next to it first, then "
            "run this again. .env was not changed."
        )
        return 1

    # The other classic paste mistake: copying the label with the
    # value, as in "MONGODB_URI=mongodb+srv://...".
    #
    # This used to reject ANY value containing an "=" sign, which was
    # wrong and wasted an evening: a MongoDB Atlas connection string
    # legitimately ends in "?appName=Cluster0" or
    # "?retryWrites=true&w=majority", so the one setting most likely
    # to be pasted first was the one setting that could never be
    # accepted. Only a leading "NAME=" is the mistake being caught.
    if value.lower().startswith(name.lower() + "="):
        print(
            f"\nThat looks like it includes the '{name}=' label. Paste only "
            "the value itself. .env was not changed."
        )
        return 1

    problem = shape_problem(name, value)

    if problem:
        print(f"\n{problem}")
        print("\n.env was not changed.")
        return 1

    values[name] = value

    write_settings(values)

    print(f"\n  {name} is now {describe(value)}")

    # For a connection string, show the host it points at. No
    # credential is in this, and it is the fastest way to spot a
    # value that was pasted wrong or from the wrong cluster.
    if name == "MONGODB_URI":
        print(f"  pointing at: {mongo_host(value)}")
    print("\nDone. Check it worked with:  python -m backend.check_setup")

    return 0


if __name__ == "__main__":
    sys.exit(main())
