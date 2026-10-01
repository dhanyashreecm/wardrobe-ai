"""
END-TO-END SMOKE TEST - the real backend, over real HTTP.

Everything else in backend/tests/ exercises the code with a fake
database. This one starts the actual Flask application against an
actual MongoDB, talks to it with an HTTP client, and checks what comes
back - registration, login, uploading a real photograph, the
segmentation pipeline, the wardrobe, recommendations, account
isolation, and the try-on routes.

It is the answer to "does the thing actually run", which no amount of
unit tests can settle.

HOW TO RUN IT

    MONGODB_URI=mongodb://127.0.0.1:27017 \
    MONGODB_DB_NAME=wardrobe_smoketest \
    python -m backend.tests.smoke_run

Point MONGODB_URI at any database you do not mind it writing to. It
creates two throwaway accounts, uploads a handful of generated garment
photos, and deletes everything it made before it exits. It will refuse
to run against a database name that does not look like a test one,
so it can never touch the real wardrobe.
"""
import io
import json
import os
import sys
import threading
import time
import traceback

HOST = "127.0.0.1"
PORT = int(os.environ.get("SMOKE_PORT", "5099"))
BASE = f"http://{HOST}:{PORT}"

PASSES, FAILURES, SKIPS = [], [], []


def check(name, condition, detail=""):
    if condition:
        PASSES.append(name)
        print(f"  PASS  {name}")
    else:
        FAILURES.append((name, detail))
        print(f"  FAIL  {name}  {detail}")
    return bool(condition)


def skip(name, why):
    SKIPS.append((name, why))
    print(f"  SKIP  {name}  ({why})")


def section(title):
    print(f"\n--- {title} ---")


# ------------------------------------------------------------
# Guard rails
# ------------------------------------------------------------

def refuse_to_touch_real_data():
    name = os.environ.get("MONGODB_DB_NAME", "")
    uri = os.environ.get("MONGODB_URI", "")
    if "test" not in name.lower():
        sys.exit(
            "Refusing to run: MONGODB_DB_NAME is "
            f"{name!r}, which does not look like a test database. "
            "Set MONGODB_DB_NAME=wardrobe_smoketest."
        )
    if "mongodb+srv" in uri:
        sys.exit(
            "Refusing to run against an Atlas SRV connection string - "
            "this test writes and deletes. Point it at a local mongod."
        )


# ------------------------------------------------------------
# Test images: real photos as far as the pipeline is concerned
# ------------------------------------------------------------

def garment_photos():
    """
    (name, png bytes) for each condition worth testing. Reuses the
    labelled benchmark when it is there, and generates it when it is
    not, so this script works in a fresh clone.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    bench_dir = os.path.join(here, "segmentation_bench")
    images = os.path.join(bench_dir, "bench")

    if not os.path.isdir(images):
        sys.path.insert(0, bench_dir)
        import make_bench
        cwd = os.getcwd()
        os.chdir(bench_dir)
        try:
            make_bench.build()
        finally:
            os.chdir(cwd)

    wanted = [
        ("t-shirt on a tiled floor", "tshirt_tiled_floor"),
        ("t-shirt on a bed", "tshirt_on_bed"),
        ("garment on a patterned background", "tshirt_patterned_throw"),
        ("white garment on a light background", "white_tshirt_white_bed"),
        ("dark garment on a dark background", "black_tshirt_dark_floor"),
        ("wrinkled garment, dim light", "tshirt_dim_light"),
        ("jeans on a wooden floor", "jeans_wooden_floor"),
        ("dress on a bed", "dress_floral_bed"),
    ]
    out = []
    for label, case in wanted:
        path = os.path.join(images, f"{case}.png")
        if os.path.isfile(path):
            out.append((label, case, open(path, "rb").read()))
    return out


def person_photo():
    """
    A crude standing figure.

    NOT a photograph of a person, and it is important to be clear about
    what that means: a run of this script proves the plumbing - the
    photo uploads, the right garment and the right person image reach
    the provider, an image comes back, it is stored, shown and counted.
    It proves NOTHING about try-on realism, which can only be judged
    from a real photo of a real person.

    An earlier version of this function sent random noise. The provider
    accepted it, returned noise, and the app counted it as a successful
    generation - which is a true description of the app's behaviour and
    is reported as a limitation rather than hidden.
    """
    from PIL import Image, ImageDraw, ImageFilter
    import numpy as np

    width, height = 768, 1024
    image = Image.new("RGB", (width, height), (232, 230, 226))
    draw = ImageDraw.Draw(image)

    skin, hair, cloth = (214, 176, 148), (58, 44, 38), (86, 96, 118)
    cx = width // 2

    draw.ellipse([cx - 62, 96, cx + 62, 236], fill=skin)          # head
    draw.ellipse([cx - 66, 84, cx + 66, 168], fill=hair)          # hair
    draw.polygon([(cx - 26, 226), (cx + 26, 226),
                  (cx + 30, 288), (cx - 30, 288)], fill=skin)     # neck
    draw.polygon([(cx - 132, 300), (cx + 132, 300),
                  (cx + 112, 600), (cx - 112, 600)], fill=cloth)  # torso
    for side in (-1, 1):
        draw.polygon([(cx + side * 126, 310), (cx + side * 170, 330),
                      (cx + side * 150, 560), (cx + side * 108, 545)],
                     fill=cloth)                                   # arms
        draw.ellipse([cx + side * 168 - 24, 548,
                      cx + side * 168 + 24, 600], fill=skin)       # hands
        draw.polygon([(cx + side * 16, 600), (cx + side * 110, 600),
                      (cx + side * 96, 930), (cx + side * 30, 930)],
                     fill=(62, 68, 86))                            # legs

    array = np.asarray(image).astype(np.float32)
    array += np.random.default_rng(5).normal(0, 3, array.shape)    # grain
    image = Image.fromarray(np.clip(array, 0, 255).astype("uint8"))
    image = image.filter(ImageFilter.GaussianBlur(0.6))

    buf = io.BytesIO()
    image.save(buf, "PNG")
    return buf.getvalue()


# ------------------------------------------------------------
# The server
# ------------------------------------------------------------

def start_server():
    from backend.app import app

    def run():
        app.run(host=HOST, port=PORT, debug=False, use_reloader=False, threaded=True)

    thread = threading.Thread(target=run, daemon=True, name="smoke-server")
    thread.start()
    return thread


def wait_for_server(requests, seconds=40):
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            requests.get(f"{BASE}/api/health", timeout=3)
            return True
        except Exception:
            time.sleep(0.4)
    return False


# ------------------------------------------------------------
# The run
# ------------------------------------------------------------

def main():
    refuse_to_touch_real_data()
    import requests

    print("Starting the backend...")
    start_server()
    if not wait_for_server(requests):
        sys.exit("The backend did not come up - nothing else can be checked.")

    created_emails = []

    try:
        section("health and database")
        res = requests.get(f"{BASE}/api/health", timeout=10)
        body = res.json() if res.ok else {}
        check("health endpoint answers 200", res.status_code == 200, str(res.status_code))
        database = body.get("database") or {}
        check("health reports the database reachable",
              bool(database.get("connected")) if isinstance(database, dict)
              else database in (True, "ok", "connected"),
              json.dumps(body)[:220])

        section("authentication")
        stamp = int(time.time())
        alice = f"smoke_alice_{stamp}@example.com"
        bob = f"smoke_bob_{stamp}@example.com"
        secret = "SmokeTest!Passw0rd"

        for email in (alice, bob):
            res = requests.post(f"{BASE}/api/register", json={
                "name": email.split("@")[0], "email": email,
                "password": secret, "gender": "Female",
            }, timeout=20)
            if check(f"register {email.split('_')[1]}", res.status_code in (200, 201),
                     f"{res.status_code} {res.text[:160]}"):
                created_emails.append(email)

        tokens = {}
        for who, email in (("alice", alice), ("bob", bob)):
            res = requests.post(f"{BASE}/api/login",
                                json={"email": email, "password": secret}, timeout=20)
            token = (res.json() or {}).get("token") or (res.json() or {}).get("access_token")
            check(f"login {who} returns a token", bool(token),
                  f"{res.status_code} {res.text[:160]}")
            tokens[who] = token

        res = requests.post(f"{BASE}/api/login",
                            json={"email": alice, "password": "wrong-password"}, timeout=20)
        check("a wrong password is refused", res.status_code in (400, 401), str(res.status_code))

        head = {"alice": {"Authorization": f"Bearer {tokens['alice']}"},
                "bob": {"Authorization": f"Bearer {tokens['bob']}"}}

        section("protected routes reject anonymous callers")
        for path, method in (("/api/wardrobe", "GET"), ("/api/tryon/capability", "GET"),
                             ("/api/ai/recommend", "GET"), ("/api/tryon/generate", "POST")):
            res = requests.request(method, f"{BASE}{path}", json={}, timeout=15)
            check(f"{method} {path} needs a token", res.status_code in (401, 422),
                  str(res.status_code))

        section("clothing upload, with real photographs")
        uploaded = []
        for label, case, data in garment_photos():
            files = {"image": (f"{case}.png", io.BytesIO(data), "image/png")}
            form = {"category": "T-Shirt" if "shirt" in case else
                            ("Jeans" if "jeans" in case else "Dress"),
                    "category_explicit": "true", "color": "Blue"}
            res = requests.post(f"{BASE}/api/wardrobe/add", files=files, data=form,
                                headers=head["alice"], timeout=120)
            ok = res.status_code in (200, 201)
            body = res.json() if res.content else {}
            check(f"upload: {label}", ok, f"{res.status_code} {res.text[:200]}")
            if ok:
                uploaded.append((label, body))
                removed = body.get("background_removed")
                engine = (body.get("image_processing") or {}).get("engine", "?")
                notes = body.get("image_warnings") or []
                print(f"        background_removed={removed} engine={engine}"
                      + (f" note={notes[0][:60]!r}" if notes else ""))
                check(f"  stored category kept for {label}",
                      body.get("category") in ("T-Shirt", "Jeans", "Dress"),
                      str(body.get("category")))
                check(f"  manual colour kept for {label}",
                      body.get("color") == "Blue" and not body.get("color_auto_detected"),
                      f"{body.get('color')} auto={body.get('color_auto_detected')}")

        section("invalid uploads are refused with a reason")
        files = {"image": ("notanimage.png", io.BytesIO(b"this is not a png"), "image/png")}
        res = requests.post(f"{BASE}/api/wardrobe/add", files=files,
                            data={"category": "T-Shirt", "category_explicit": "true"},
                            headers=head["alice"], timeout=30)
        check("a corrupt file is refused", res.status_code >= 400, str(res.status_code))
        check("  and the message explains why",
              bool((res.json() or {}).get("message")), res.text[:160])

        section("the wardrobe, and account isolation")
        res = requests.get(f"{BASE}/api/wardrobe", headers=head["alice"], timeout=30)
        items = (res.json() or {}).get("items", [])
        check("alice sees the items she uploaded", len(items) == len(uploaded),
              f"{len(items)} vs {len(uploaded)}")
        check("every item carries an image url",
              all(i.get("image_path") for i in items),
              str([i.get("image_path") for i in items][:2]))

        res = requests.get(f"{BASE}/api/wardrobe", headers=head["bob"], timeout=30)
        bob_items = (res.json() or {}).get("items", [])
        check("bob's wardrobe is empty - he uploaded nothing", bob_items == [],
              f"{len(bob_items)} items")

        if items:
            victim = items[0]["_id"]
            res = requests.put(f"{BASE}/api/wardrobe/{victim}", json={"favorite": True},
                               headers=head["bob"], timeout=20)
            check("bob cannot edit alice's item", res.status_code in (403, 404),
                  str(res.status_code))
            res = requests.delete(f"{BASE}/api/wardrobe/{victim}",
                                  headers=head["bob"], timeout=20)
            check("bob cannot delete alice's item", res.status_code in (403, 404),
                  str(res.status_code))
            still = requests.get(f"{BASE}/api/wardrobe", headers=head["alice"],
                                 timeout=20).json().get("items", [])
            check("  and alice's item survived", len(still) == len(items),
                  f"{len(still)} vs {len(items)}")

        section("recommendations")
        seen = {}
        for occasion in ("Casual", "Formal", "Party", "Traditional"):
            res = requests.get(f"{BASE}/api/ai/recommend",
                               params={"occasion": occasion},
                               headers=head["alice"], timeout=60)
            ok = res.status_code == 200
            check(f"recommendations for {occasion}", ok,
                  f"{res.status_code} {res.text[:160]}")
            if ok:
                body = res.json() or {}
                outfits = body.get("outfits") or body.get("recommendations") or []
                seen[occasion] = outfits
                print(f"        {len(outfits)} outfit(s)")
        if len(seen) >= 2:
            signatures = {k: json.dumps(v, sort_keys=True, default=str)[:4000]
                          for k, v in seen.items()}
            check("different occasions do not all return the same thing",
                  len(set(signatures.values())) > 1 or all(not v for v in seen.values()),
                  "every occasion returned an identical payload")

        section("similar-clothes search")
        files = {"image": ("q.png", io.BytesIO(garment_photos()[0][2]), "image/png")}
        res = requests.post(f"{BASE}/api/ai/similar", files=files,
                            headers=head["alice"], timeout=120)
        if res.status_code == 503 and (res.json() or {}).get("code") == "similarity_unavailable":
            skip("similar-clothes search", "TensorFlow not installed on this machine")
            check("  and it fails cleanly rather than crashing the app", True)
        else:
            check("similar-clothes search answers", res.status_code == 200,
                  f"{res.status_code} {res.text[:160]}")

        section("virtual try-on")
        res = requests.get(f"{BASE}/api/tryon/capability", headers=head["alice"], timeout=30)
        cap = res.json() if res.ok else {}
        check("capability endpoint answers", res.status_code == 200, str(res.status_code))
        usage = cap.get("usage") or {}
        check("the daily allowance starts at the configured limit",
              usage.get("successful") == 0 and usage.get("remaining") == usage.get("limit"),
              json.dumps(usage))
        print(f"        provider status: {cap.get('status')} - {cap.get('message')}")

        res = requests.post(f"{BASE}/api/tryon/photo",
                            files={"image": ("me.png", io.BytesIO(person_photo()), "image/png")},
                            headers=head["alice"], timeout=60)
        check("a person photo uploads", res.status_code == 200,
              f"{res.status_code} {res.text[:200]}")

        res = requests.get(f"{BASE}/api/tryon/garments", headers=head["alice"], timeout=30)
        garments = (res.json() or {}).get("items", [])
        check("the try-on garment list is this account's wardrobe",
              res.status_code == 200 and len(garments) == len(items),
              f"{res.status_code} {len(garments)} vs {len(items)}")

        wearable = [g for g in garments if g.get("tryon", {}).get("supported")]
        if wearable:
            res = requests.post(f"{BASE}/api/tryon/generate",
                                json={"item_ids": [wearable[0]["_id"]]},
                                headers=head["alice"], timeout=60)
            code = res.status_code
            body = res.json() if res.content else {}
            if code == 503:
                skip("real try-on generation",
                     f"no provider reachable: {body.get('message', '')[:80]}")
                after = requests.get(f"{BASE}/api/tryon/capability",
                                     headers=head["alice"], timeout=30).json().get("usage", {})
                check("  a provider outage costs no attempt",
                      after.get("remaining") == usage.get("limit"),
                      json.dumps(after))
            elif code == 202:
                job = body["job_id"]
                final = None
                for _ in range(90):
                    time.sleep(2)
                    status = requests.get(f"{BASE}/api/tryon/status/{job}",
                                          headers=head["alice"], timeout=30).json()["job"]
                    if status["status"] in ("done", "failed"):
                        final = status
                        break
                check("the generation reached a terminal state", bool(final), "still running")
                if final and final["status"] == "done":
                    check("a REAL try-on image was produced and stored",
                          bool(final.get("image_url")), json.dumps(final)[:200])
                    after = requests.get(f"{BASE}/api/tryon/capability",
                                         headers=head["alice"], timeout=30).json()["usage"]
                    check("  and it counted as exactly one successful generation",
                          after.get("successful") == 1, json.dumps(after))
                elif final:
                    skip("real try-on generation",
                         f"provider failed: {str(final.get('error'))[:80]}")
                    after = requests.get(f"{BASE}/api/tryon/capability",
                                         headers=head["alice"], timeout=30).json()["usage"]
                    check("  a failed generation did not consume a successful slot",
                          after.get("successful") == 0, json.dumps(after))
            else:
                check("try-on generate answered sensibly", code in (400, 429),
                      f"{code} {res.text[:160]}")

            res = requests.post(f"{BASE}/api/tryon/generate",
                                json={"item_ids": [wearable[0]["_id"]]},
                                headers=head["bob"], timeout=60)
            check("bob cannot try on alice's clothes",
                  res.status_code in (404, 400, 503),
                  f"{res.status_code} {res.text[:120]}")
        else:
            skip("try-on generation", "no wearable garment in the test wardrobe")

        res = requests.get(f"{BASE}/api/tryon/results", headers=head["bob"], timeout=20)
        check("bob's try-on history is his own",
              res.status_code == 200 and (res.json() or {}).get("results") == [],
              res.text[:120])

    finally:
        section("cleaning up")
        try:
            from backend.db import db
            for email in created_emails:
                for name in db.list_collection_names():
                    db[name].delete_many({"user_email": email})
                db["users"].delete_many({"email": email})
            print(f"  removed {len(created_emails)} test account(s) and their data")
        except Exception as error:  # noqa: BLE001
            print(f"  database cleanup could not finish: "
                  f"{type(error).__name__}: {error}")

        # Local image storage writes a folder per account. Deleting the
        # database rows alone leaves those behind - an earlier version of
        # this script quietly accumulated 57 MB of them in the repo.
        try:
            import shutil
            from backend import storage
            removed = 0
            for email in created_emails:
                for folder in (email, email.replace("@", "_").replace(".", "_"),
                               f"{email.split('@')[0]}_digital_wardrobe"):
                    path = os.path.join(storage.BASE_UPLOAD_FOLDER, folder)
                    if os.path.isdir(path):
                        shutil.rmtree(path, ignore_errors=True)
                        removed += 1
                # whatever naming storage actually used
                root = storage.BASE_UPLOAD_FOLDER
                if os.path.isdir(root):
                    stem = email.split("@")[0]
                    for name in os.listdir(root):
                        if name.startswith(stem):
                            shutil.rmtree(os.path.join(root, name), ignore_errors=True)
                            removed += 1
            print(f"  removed {removed} uploaded-image folder(s)")
        except Exception as error:  # noqa: BLE001
            print(f"  image cleanup could not finish: "
                  f"{type(error).__name__}: {error}")

    print("\n" + "=" * 60)
    print(f"PASSED {len(PASSES)}   FAILED {len(FAILURES)}   SKIPPED {len(SKIPS)}")
    if SKIPS:
        print("\nSkipped (external things this machine could not reach):")
        for name, why in SKIPS:
            print(f"  - {name}: {why}")
    if FAILURES:
        print("\nFailures:")
        for name, detail in FAILURES:
            print(f"  - {name}: {detail}")
    print("=" * 60)
    return 1 if FAILURES else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        sys.exit(2)
