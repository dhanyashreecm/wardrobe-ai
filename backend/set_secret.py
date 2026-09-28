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
]

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(PROJECT_ROOT, ".env")


def read_settings():
    """Current values, ignoring comments, blanks and anything malformed."""
    values = {}

    if not os.path.isfile(ENV_PATH):
        return values

    for raw in open(ENV_PATH, encoding="utf-8"):
        line = raw.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()

        if key in SETTINGS:
            values[key] = value

    return values


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

    # The other classic paste mistake: copying the label with the value.
    if "=" in value or value.lower().startswith(name.lower()):
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
