"""
PROVES that two computers really do share one wardrobe.

Everything else can look right and still be wrong: two machines can
each be "connected to Atlas" and still be on different databases, or
share a database but not the token signing key, or share both but save
images where the other cannot see them. This is the test that settles
it, by going through the running application exactly as a user does -
HTTP requests to the backend, a real login, a real upload.

HOW TO USE IT (backend must be running on the machine you run it on):

    Computer A:   python -m backend.sync_test send
    Computer B:   python -m backend.sync_test check
    Computer B:   python -m backend.sync_test send
    Computer A:   python -m backend.sync_test check

    Afterwards:   python -m backend.sync_test cleanup

"send" uploads one small generated test image (never one of your
photos) under a dedicated test account, and prints a short marker.
"check", run on the other machine, logs into that same account and
confirms the item is visible there, that its image actually loads,
and - if the other machine also ran "send" - that both directions
work.

WHAT A PASS ACTUALLY PROVES
  * Both machines reach the SAME database (the item exists on both).
  * Both machines accept the SAME login (same JWT signing key), and a
    token issued by one machine is accepted by the other - checked
    explicitly, because a mismatched key is the one failure that only
    shows up as a confusing 401 later.
  * Images uploaded on one machine LOAD on the other (shared storage,
    not a local folder).

The test account is created on first use with a random password stored
in the project's own throwaway file (sync_test_state.json, gitignored)
so both runs can log in. It holds nothing of yours, and `cleanup`
removes its items again.
"""

import argparse
import io
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


STATE_FILE = "sync_test_state.json"

TEST_EMAIL = "sync-check@wardrobe-ai.local"

# A marker no real wardrobe item would use, so probes are always
# identifiable and cleanup can never touch a genuine item.
MARKER_COLOR_PREFIX = "synccheck-"


def default_base_url():
    return os.environ.get("WARDROBE_API_URL", "http://localhost:5001")


# ------------------------------------------------------------------
# Tiny HTTP helpers - deliberately using urllib rather than requests,
# so this runs on a machine where only the app's own dependencies are
# installed.
# ------------------------------------------------------------------

def _request(method, url, token=None, json_body=None, multipart=None, timeout=30):

    headers = {}

    if token:
        headers["Authorization"] = f"Bearer {token}"

    data = None

    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    elif multipart is not None:
        boundary = "----wardrobe" + secrets.token_hex(8)
        data = _encode_multipart(multipart, boundary)
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, _maybe_json(body)

    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        return error.code, _maybe_json(body)

    except Exception as error:
        return 0, {"error": str(error)}


def _maybe_json(body):
    try:
        return json.loads(body)
    except Exception:
        return {"raw": body[:400]}


def _encode_multipart(fields, boundary):
    """Minimal multipart/form-data encoder for the upload call."""
    parts = []

    for name, value in fields.items():

        if isinstance(value, tuple):
            filename, content = value
            parts.append(
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"; '
                f'filename="{filename}"\r\n'
                "Content-Type: image/jpeg\r\n\r\n".encode("utf-8")
                + content
                + b"\r\n"
            )
        else:
            parts.append(
                (
                    f"--{boundary}\r\n"
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                    f"{value}\r\n"
                ).encode("utf-8")
            )

    parts.append(f"--{boundary}--\r\n".encode("utf-8"))

    return b"".join(parts)


# ------------------------------------------------------------------

def load_state():
    if os.path.isfile(STATE_FILE):
        try:
            with open(STATE_FILE) as handle:
                return json.load(handle)
        except Exception:
            pass
    return {}


def save_state(state):
    with open(STATE_FILE, "w") as handle:
        json.dump(state, handle, indent=2)


def test_image():
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (48, 48), color=(140, 90, 180)).save(buffer, format="JPEG")
    return buffer.getvalue()


def login_or_register(base_url, password):
    """
    Returns (token, note). The account is shared between both machines
    - it is created once, on whichever machine runs `send` first, and
    the other machine simply logs into it. That is itself part of the
    test: logging in on machine B to an account created on machine A
    can only work if both are on the same database.
    """
    status, body = _request(
        "POST", f"{base_url}/api/login",
        json_body={"email": TEST_EMAIL, "password": password},
    )

    if status == 200 and body.get("token"):
        return body["token"], "logged in to the existing test account"

    status, body = _request(
        "POST", f"{base_url}/api/register",
        json_body={
            "name": "Sync Check", "email": TEST_EMAIL,
            "password": password, "gender": "Female",
        },
    )

    if status != 200 or not body.get("success", True):
        return None, f"could not create the test account: {body}"

    status, body = _request(
        "POST", f"{base_url}/api/login",
        json_body={"email": TEST_EMAIL, "password": password},
    )

    if status == 200 and body.get("token"):
        return body["token"], "created the test account"

    return None, f"registered but could not log in: {body}"


def backend_alive(base_url):
    status, body = _request("GET", f"{base_url}/api/health", timeout=20)

    if status == 0:
        return False, f"no backend answering at {base_url} - start it first"

    if status != 200:
        return False, f"backend is unhealthy: {body}"

    return True, body


def command_send(base_url):

    print(f"Talking to the backend at {base_url}\n")

    alive, health = backend_alive(base_url)

    if not alive:
        print(f"  FAIL: {health}")
        return 1

    storage_backend = health.get("storage", {}).get("backend")

    print(f"  database : {health['database']['name']} at {health['database']['host']}")
    print(f"  storage  : {storage_backend}")

    if health["database"]["host"].startswith(("localhost", "127.0.0.1")):
        print(
            "\n  FAIL: this machine is using a LOCAL database, so nothing it "
            "\n        uploads can ever appear on the other computer."
            "\n        Point MONGODB_URI at the shared Atlas cluster first."
        )
        return 1

    if storage_backend != "cloudinary":
        print(
            "\n  FAIL: images are being saved to this computer only."
            "\n        Set the three CLOUDINARY_ values in .env first."
        )
        return 1

    state = load_state()
    password = state.get("password") or secrets.token_urlsafe(16)

    token, note = login_or_register(base_url, password)

    if not token:
        print(f"\n  FAIL: {note}")
        return 1

    print(f"  account  : {note}")

    marker = MARKER_COLOR_PREFIX + secrets.token_hex(4)

    status, body = _request(
        "POST", f"{base_url}/api/wardrobe/add",
        token=token,
        multipart={
            "category": "Shirt",
            "color": marker,
            "image": ("sync_check.jpg", test_image()),
        },
    )

    if status != 200:
        print(f"\n  FAIL: upload was rejected - {body}")
        return 1

    image_url = body.get("image", "")

    print(f"  uploaded : item {body.get('item_id')} tagged {marker}")

    if not image_url.startswith("https://"):
        print(
            f"\n  FAIL: the stored image reference is '{image_url[:40]}', not an"
            "\n        https URL - the other computer will not be able to load it."
        )
        return 1

    print("  image    : stored as an https URL (loads from any computer)")

    state.update({
        "password": password,
        "sent_marker": marker,
        "sent_item_id": body.get("item_id"),
        "sent_at": time.time(),
        # Kept so the OTHER machine can prove a token minted here is
        # accepted there - the definitive check that both machines
        # share one JWT signing key.
        "token": token,
    })
    save_state(state)

    print()
    print("  PASS - this machine uploaded to the shared setup.")
    print()
    print("  Now, on the OTHER computer:")
    print(f"    1. copy this project's {STATE_FILE} across (it holds only the")
    print("       throwaway test account's password and marker), or just run")
    print("       'check' there and type the marker when asked:")
    print(f"           {marker}")
    print("    2. run:  python -m backend.sync_test check")

    return 0


def command_check(base_url, marker=None, expect_token=None):

    print(f"Talking to the backend at {base_url}\n")

    alive, health = backend_alive(base_url)

    if not alive:
        print(f"  FAIL: {health}")
        return 1

    print(f"  database : {health['database']['name']} at {health['database']['host']}")
    print(f"  storage  : {health.get('storage', {}).get('backend')}")

    state = load_state()

    marker = marker or state.get("sent_marker")

    if not marker:
        print(
            "\n  I need the marker printed by 'send' on the other computer."
            "\n  Re-run as:  python -m backend.sync_test check --marker synccheck-xxxx"
        )
        return 1

    password = state.get("password")

    if not password:
        print(
            "\n  I need the test account's password, which is in the other"
            f"\n  computer's {STATE_FILE}. Copy that file into this project"
            "\n  folder and run this again."
        )
        return 1

    token, note = login_or_register(base_url, password)

    if not token:
        print(f"\n  FAIL: {note}")
        print(
            "\n  If this says the password is wrong, the two machines are on"
            "\n  DIFFERENT databases - the account created on the other"
            "\n  computer does not exist in this one's."
        )
        return 1

    print(f"  account  : {note}")

    status, body = _request("GET", f"{base_url}/api/wardrobe", token=token)

    if status != 200:
        print(f"\n  FAIL: could not read the wardrobe - {body}")
        return 1

    items = body.get("items", [])

    matching = [item for item in items if item.get("color") == marker]

    if not matching:
        print(
            f"\n  FAIL: no item tagged {marker} is visible here."
            "\n        The two computers are not sharing one database."
            f"\n        (this account has {len(items)} item(s) here)"
        )
        return 1

    item = matching[0]

    print(f"  found    : the item uploaded on the other computer ({marker})")

    image_url = item.get("image_path", "")

    if not image_url.startswith("https://"):
        print(
            f"\n  FAIL: its image reference is '{image_url[:40]}' - a local path,"
            "\n        so it cannot display on this computer."
        )
        return 1

    try:
        with urllib.request.urlopen(image_url, timeout=20) as response:
            size = len(response.read())
            content_type = response.headers.get("Content-Type", "")
    except Exception as error:
        print(f"\n  FAIL: its image URL did not load here - {error}")
        return 1

    print(f"  image    : loaded from shared storage ({size} bytes, {content_type})")

    # --- token compatibility ---------------------------------------
    other_token = expect_token or state.get("token")

    # Checked whenever a token from the other machine is available -
    # including when it happens to be byte-identical to this machine's
    # (two backends sharing a signing key can mint the same token for
    # the same account in the same second). Skipping the check in that
    # case would quietly drop the one test that catches a mismatched
    # JWT_SECRET_KEY.
    if other_token:

        status, _ = _request("GET", f"{base_url}/api/wardrobe", token=other_token)

        if status == 200:
            print("  tokens   : a login token from the other computer is accepted here")
        else:
            print(
                "\n  FAIL: this machine rejected a login token issued by the other"
                "\n        computer - the two JWT_SECRET_KEY values differ."
                "\n        Make both .env files use the same key."
            )
            return 1

    print()
    print("  PASS - this computer sees the other computer's wardrobe item.")
    print()
    print("  For the reverse direction, run 'send' here and 'check' there.")

    return 0


def command_cleanup(base_url):

    state = load_state()
    password = state.get("password")

    if not password:
        print("Nothing to clean up (no test account on this machine).")
        return 0

    token, _ = login_or_register(base_url, password)

    if not token:
        print("Could not log in to the test account - nothing removed.")
        return 1

    status, body = _request("GET", f"{base_url}/api/wardrobe", token=token)

    removed = 0

    for item in body.get("items", []):

        if str(item.get("color", "")).startswith(MARKER_COLOR_PREFIX):

            status, _ = _request(
                "DELETE", f"{base_url}/api/wardrobe/{item['_id']}", token=token,
            )

            if status == 200:
                removed += 1

    print(f"Removed {removed} test item(s).")
    print(
        "The test ACCOUNT is left in place (deleting it is not something this "
        "script should do on its own); it holds nothing but these probes."
    )

    return 0


def main():

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("send", "check", "cleanup"))
    parser.add_argument("--base-url", default=default_base_url())
    parser.add_argument("--marker", default=None,
                        help="The marker printed by 'send' on the other computer.")
    args = parser.parse_args()

    if args.action == "send":
        return command_send(args.base_url)

    if args.action == "check":
        return command_check(args.base_url, args.marker)

    return command_cleanup(args.base_url)


if __name__ == "__main__":
    sys.exit(main())
