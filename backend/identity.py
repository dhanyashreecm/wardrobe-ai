"""
ONE definition of "which account is this?".

An account is identified globally by its email address, and the same
address can arrive typed in many ways: "You@Gmail.com",
" you@gmail.com ", "YOU@GMAIL.COM". Before this
module each route used the string exactly as typed, so:

  * a login typed with a capital letter produced a login token whose
    identity did not match the wardrobe rows' user_email, and the user
    saw an EMPTY wardrobe on that device;
  * registering with different capitalisation created a SECOND account
    for the same mailbox.

Every place that reads or writes an email (register, login, password
reset, JWT identity, wardrobe/trip ownership, migration) now goes
through normalize_email(), so one mailbox is always one account, on
every device.
"""

import re


def normalize_email(value):
    """
    Canonical form of an email address: surrounding whitespace removed
    and lower-cased. Returns "" for None/blank.

    Lower-casing the whole address (not just the domain) is deliberate:
    every mainstream provider, Gmail included, treats the local part
    case-insensitively, and two accounts differing only by case are
    always a mistake in this app.
    """
    if value is None:
        return ""
    return str(value).strip().lower()


def email_match_filter(value, field="email"):
    """
    A MongoDB filter matching `field` against the address regardless of
    case or stray surrounding whitespace. Used only as a fallback for
    records written before normalisation existed; new records are
    always stored normalised and are found by exact match first.
    """
    canonical = normalize_email(value)
    return {
        field: {
            "$regex": r"^\s*" + re.escape(canonical) + r"\s*$",
            "$options": "i",
        }
    }
