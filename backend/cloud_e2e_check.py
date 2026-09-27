"""
END-TO-END proof that an account is a CLOUD account, through the
running backend exactly as the app uses it (backend must be running):

    python -m backend.cloud_e2e_check

Uses ONLY the dedicated throwaway test account from sync_test
(sync-check@wardrobe-ai.local; its random password lives in the
gitignored sync_test_state.json) - never a real user's data. It:

  1. checks /api/health: Atlas connected, Cloudinary storage, indexes
  2. logs in as "device A" and, with different capitalisation, as
     "device B" - two independent sessions, like two laptops
  3. confirms both sessions resolve to the SAME account
  4. confirms re-registering the same email in another case is refused
  5. uploads a generated test image from device A -> https Cloudinary
     URL stored in Atlas
  6. lists the wardrobe from device B -> the same item, same URL, and
     the image actually loads
  7. runs recommendations for the account
  8. deletes the probe item again

With --probe-email it also confirms that account EXISTS in Atlas by a
login attempt with a deliberately wrong password (typed in mixed
case): the answer must be "Incorrect password", never "No account".
Nothing about that account is changed and no email is sent.
"""

import argparse
import json
import os
import secrets
import sys
import urllib.request

from backend.sync_test import (
    MARKER_COLOR_PREFIX,
    STATE_FILE,
    TEST_EMAIL,
    _request,
    default_base_url,
    load_state,
    login_or_register,
    save_state,
    test_image,
)


def swapcase_email(email):
    local, _, domain = email.partition("@")
    return f"  {local.upper()}@{domain.title()} "


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=default_base_url())
    parser.add_argument("--probe-email", default=None)
    args = parser.parse_args(argv)
    base = args.base_url
    results = []

    def record(name, ok, detail=""):
        results.append((name, ok))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))
        return ok

    status, health = _request("GET", f"{base}/api/health", timeout=20)
    if status == 0:
        print(f"No backend at {base} - start it with: python -m backend.app")
        return 1
    db_info = health.get("database", {})
    record("backend reaches Atlas", status == 200 and db_info.get("connected")
           and not str(db_info.get("host", "")).startswith(("localhost", "127.")),
           f"{db_info.get('name')} at {db_info.get('host')}")
    record("images go to Cloudinary", health.get("storage", {}).get("backend") == "cloudinary")
    record("uniqueness indexes in place", health.get("indexes") == [],
           json.dumps(health.get("indexes")))

    state = load_state()
    password = state.get("password") or secrets.token_urlsafe(16)
    token_a, note = login_or_register(base, password)
    if not token_a:
        record("test account login", False, note)
        return 1
    state["password"] = password
    save_state(state)

    status, body_b = _request("POST", f"{base}/api/login",
                              json_body={"email": swapcase_email(TEST_EMAIL), "password": password})
    token_b = body_b.get("token")
    record("login with different capitalisation (device B)", status == 200 and bool(token_b))
    record("both logins resolve to the same account",
           body_b.get("email") == TEST_EMAIL, f"device B identity: {body_b.get('email')}")

    status, reg = _request("POST", f"{base}/api/register", json_body={
        "name": "Dup", "email": TEST_EMAIL.upper(), "password": "whatever123", "gender": "Female"})
    record("duplicate registration (other case) refused", status == 400 and not reg.get("success", True),
           reg.get("message", ""))

    status, bad = _request("POST", f"{base}/api/login",
                           json_body={"email": TEST_EMAIL, "password": password + "x"})
    record("wrong password refused", status == 401)

    marker = MARKER_COLOR_PREFIX + secrets.token_hex(4)
    status, up = _request("POST", f"{base}/api/wardrobe/add", token=token_a, multipart={
        "category": "Shirt", "category_explicit": "true", "color": marker,
        "image": ("e2e_check.jpg", test_image())}, timeout=120)
    image_url = up.get("image", "") if isinstance(up, dict) else ""
    record("upload from device A accepted", status == 200 and up.get("success"),
           up.get("message", "") if status != 200 else f"item {up.get('item_id')}")
    record("stored image is an https Cloudinary URL", image_url.startswith("https://res.cloudinary.com/"),
           image_url[:60])

    status, listing = _request("GET", f"{base}/api/wardrobe", token=token_b)
    items = [i for i in listing.get("items", []) if i.get("color") == marker]
    record("device B sees device A's upload", status == 200 and len(items) == 1)
    if items:
        record("device B gets the same image URL", items[0].get("image_path") == image_url)
        record("category kept", items[0].get("category") == "Shirt", items[0].get("category"))
        try:
            with urllib.request.urlopen(image_url, timeout=20) as response:
                record("image loads from the cloud", response.status == 200,
                       response.headers.get("Content-Type", ""))
        except Exception as error:  # noqa: BLE001
            record("image loads from the cloud", False, type(error).__name__)

    status, rec = _request("GET", f"{base}/api/ai/recommend?occasion=casual&use_weather=false",
                           token=token_b, timeout=120)
    record("recommendations run on the cloud wardrobe", status == 200, f"HTTP {status}")

    if up.get("item_id"):
        status, _ = _request("DELETE", f"{base}/api/wardrobe/{up['item_id']}", token=token_b)
        record("probe item removed", status == 200)

    if args.probe_email:
        status, body = _request("POST", f"{base}/api/login", json_body={
            "email": swapcase_email(args.probe_email), "password": "definitely-not-the-password-" + secrets.token_hex(4)})
        record(f"account exists in Atlas for {args.probe_email.strip().lower()} (found case-insensitively)",
               status == 401 and body.get("message") == "Incorrect password", body.get("message", ""))

    failed = [name for name, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
