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

    values[name] = value

    write_settings(values)

    print(f"\n  {name} is now {describe(value)}")
    print("\nDone. Check it worked with:  python -m backend.check_setup")

    return 0


if __name__ == "__main__":
    sys.exit(main())
