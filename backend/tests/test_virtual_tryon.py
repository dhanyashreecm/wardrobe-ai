"""
Virtual Try-On tests: the REAL Flask routes, the REAL tryon_store
queries (against an in-memory stand-in for the two Mongo collections)
and the REAL virtual_tryon planning / provider contract.

Replaced with stand-ins: the wardrobe lookup, Cloudinary, the heavy AI
modules, and the try-on provider itself - a fake provider that records
what it was asked to do. Nothing here calls a GPU, Atlas or Cloudinary,
so these tests prove the plumbing, security and error handling; they
do NOT prove the model produces a good picture (that needs the real
provider - see spaces/tryon/README.md).

Run on the Mac:
    source ai_env312/bin/activate
    python -m unittest backend.tests.test_virtual_tryon -v
"""
import copy
import io
import json
import os
import sys
import tempfile
import types
import unittest
from unittest import mock


try:
    import flask  # noqa: F401
    import pymongo  # noqa: F401
    import flask_jwt_extended  # noqa: F401
    HAVE_DEPS = True
except ImportError:
    HAVE_DEPS = False


SECRET_TOKEN = "hf_SUPERSECRETtoken123"
SECRET_SPACE = "private-owner/private-tryon-space"


def _png(width=600, height=900, colour=(200, 180, 170)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buf, format="PNG")
    return buf.getvalue()


def _stub(name, **attrs):
    if name in sys.modules:
        return
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module


# ------------------------------------------------------------------
# In-memory stand-in for the two pymongo collections tryon_store uses.
# Implements only what tryon_store calls, with real filter semantics
# (every key must match), so ownership filtering is genuinely tested.
# ------------------------------------------------------------------

class _Cursor(list):
    def sort(self, key, direction):
        return _Cursor(sorted(self, key=lambda d: d.get(key), reverse=direction < 0))

    def limit(self, count):
        return _Cursor(self[:count])


class FakeCollection:
    def __init__(self):
        self.docs = []

    @staticmethod
    def _match(doc, query):
        # Exact equality, plus the handful of comparison operators the
        # daily-limit code relies on. Without $lt the "take an attempt
        # only if fewer than the limit are used" filter would match
        # unconditionally, and the test would pass while the real
        # database refused - the worst kind of green.
        for key, expected in query.items():
            actual = doc.get(key)
            if isinstance(expected, dict):
                for operator, value in expected.items():
                    if operator == "$lt" and not (actual is not None and actual < value):
                        return False
                    if operator == "$gt" and not (actual is not None and actual > value):
                        return False
                    if operator == "$gte" and not (actual is not None and actual >= value):
                        return False
                    if operator == "$lte" and not (actual is not None and actual <= value):
                        return False
                    if operator == "$ne" and actual == value:
                        return False
            elif actual != expected:
                return False
        return True

    def find_one(self, query):
        for doc in self.docs:
            if self._match(doc, query):
                return copy.deepcopy(doc)
        return None

    def find(self, query):
        return _Cursor(copy.deepcopy(d) for d in self.docs if self._match(d, query))

    def insert_one(self, doc):
        self.docs.append(copy.deepcopy(doc))

    def replace_one(self, query, doc, upsert=False):
        for i, existing in enumerate(self.docs):
            if self._match(existing, query):
                self.docs[i] = copy.deepcopy(doc)
                return
        if upsert:
            self.docs.append(copy.deepcopy(doc))

    def update_one(self, query, update):
        for doc in self.docs:
            if self._match(doc, query):
                self._apply(doc, update)
                return

    @staticmethod
    def _apply(doc, update):
        doc.update(copy.deepcopy(update.get("$set", {})))
        for field, amount in (update.get("$inc") or {}).items():
            doc[field] = doc.get(field, 0) + amount

    def find_one_and_update(self, query, update, upsert=False):
        """
        Mongo's atomic check-and-change, as the daily limit uses it.

        The important part is the upsert branch: when the filter does
        not match because the row EXISTS but fails a condition (ten
        attempts already used), a real Mongo raises DuplicateKeyError
        on the _id rather than inserting a second row. Modelling that
        is what lets the test prove the eleventh request is refused.
        """
        for doc in self.docs:
            if self._match(doc, query):
                self._apply(doc, update)
                return copy.deepcopy(doc)

        if not upsert:
            return None

        identifier = query.get("_id")
        if identifier is not None and any(d.get("_id") == identifier for d in self.docs):
            from pymongo.errors import DuplicateKeyError
            raise DuplicateKeyError("row exists but did not match the filter")

        fresh = {k: v for k, v in query.items() if not isinstance(v, dict)}
        fresh.update(copy.deepcopy(update.get("$setOnInsert", {})))
        self._apply(fresh, update)
        self.docs.append(fresh)
        return copy.deepcopy(fresh)

    def delete_one(self, query):
        for i, doc in enumerate(self.docs):
            if self._match(doc, query):
                del self.docs[i]
                return

    def delete_many(self, query):
        self.docs = [d for d in self.docs if not self._match(d, query)]


class FakeProvider:
    """
    Stands in for the real try-on service. Configurable to succeed,
    fail, or never finish, and records every garment it was sent.
    """

    name = "fake"
    supported_model_categories = ("tops", "bottoms", "one-pieces")
    supports_layering = True
    calls = []
    behaviour = "succeed"         # succeed | fail | hang | raise_on_submit
    failure = RuntimeError("boom")
    output = b"GENERATED-IMAGE"

    def missing_configuration(self):
        return []

    def available(self):
        return True

    def max_passes(self):
        return 3 if self.supports_layering else 1

    def submit(self, person_bytes, garment_bytes, model_category):
        if FakeProvider.behaviour == "raise_on_submit":
            raise FakeProvider.failure
        FakeProvider.calls.append({"category": model_category, "garment": garment_bytes})
        return {"n": len(FakeProvider.calls)}

    def status(self, handle):
        if FakeProvider.behaviour == "hang":
            return "running"
        if FakeProvider.behaviour == "fail":
            return "failed"
        return "done"

    def result(self, handle):
        if FakeProvider.behaviour == "fail":
            raise FakeProvider.failure
        return FakeProvider.output + str(handle["n"]).encode()

    def cancel(self, handle):
        FakeProvider.cancelled = True


class _SyncThread:
    """Runs the background job immediately so tests can read its outcome."""

    def __init__(self, target=None, args=(), kwargs=None, **_):
        self.target, self.args, self.kwargs = target, args, kwargs or {}

    def start(self):
        self.target(*self.args, **self.kwargs)


ALICE = "alice@example.com"
BOB = "bob@example.com"

WARDROBES = {
    ALICE: [
        {"_id": "a_shirt", "user_email": ALICE, "category": "Shirt", "color": "white",
         "image_path": "https://res.cloudinary.com/demo/a_shirt.png"},
        {"_id": "a_jeans", "user_email": ALICE, "category": "Jeans", "color": "blue",
         "image_path": "https://res.cloudinary.com/demo/a_jeans.png"},
        {"_id": "a_dress", "user_email": ALICE, "category": "Dress", "color": "red",
         "image_path": "https://res.cloudinary.com/demo/a_dress.png"},
        {"_id": "a_saree", "user_email": ALICE, "category": "Saree", "color": "green",
         "image_path": "https://res.cloudinary.com/demo/a_saree.png"},
        {"_id": "a_lehenga", "user_email": ALICE, "category": "Lehenga", "color": "pink",
         "image_path": "https://res.cloudinary.com/demo/a_lehenga.png"},
        {"_id": "a_heels", "user_email": ALICE, "category": "Heels", "color": "black",
         "image_path": "https://res.cloudinary.com/demo/a_heels.png"},
        {"_id": "a_blazer", "user_email": ALICE, "category": "Blazer", "color": "black",
         "image_path": "https://res.cloudinary.com/demo/a_blazer.png"},
        {"_id": "a_kurta", "user_email": ALICE, "category": "Kurta (Women)", "color": "yellow",
         "image_path": "https://res.cloudinary.com/demo/a_kurta.png"},
        # a men's category that somehow ended up on a women's account
        {"_id": "a_sherwani", "user_email": ALICE, "category": "Sherwani", "color": "gold",
         "image_path": "https://res.cloudinary.com/demo/a_sherwani.png"},
    ],
    BOB: [
        {"_id": "b_shirt", "user_email": BOB, "category": "Shirt", "color": "navy",
         "image_path": "https://res.cloudinary.com/demo/b_shirt.png"},
        {"_id": "b_sherwani", "user_email": BOB, "category": "Sherwani", "color": "cream",
         "image_path": "https://res.cloudinary.com/demo/b_sherwani.png"},
    ],
}
GENDERS = {ALICE: "Female", BOB: "Male"}


@unittest.skipUnless(HAVE_DEPS, "Flask/pymongo not installed here - run on the Mac with ai_env")
class VirtualTryOnApiTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        _stub("backend.clothing_similarity", find_similar=lambda *a, **k: [])
        _stub("backend.indofashion_similarity", find_similar_indofashion=lambda *a, **k: [])
        _stub("backend.indofashion_classifier",
              predict_category=lambda path: {"category": "blouse", "confidence": 0.3})
        from backend import app as app_module
        from backend import virtual_tryon, tryon_store
        cls.m = app_module
        cls.vt = virtual_tryon
        cls.store = tryon_store

        from backend import tryon_usage
        cls.usage = tryon_usage
        cls.client = app_module.app.test_client()
        cls.tmp = tempfile.mkdtemp()

    def setUp(self):
        m, vt = self.m, self.vt
        FakeProvider.calls = []
        FakeProvider.behaviour = "succeed"
        FakeProvider.failure = RuntimeError("boom")
        FakeProvider.cancelled = False

        self.photos = FakeCollection()
        self.results = FakeCollection()
        self.usage_rows = FakeCollection()
        self.saved = []

        # url -> file on disk, standing in for Cloudinary downloads
        self.files = {}
        for items in WARDROBES.values():
            for item in items:
                self._file_for(item["image_path"], b"GARMENT:" + item["_id"].encode())

        def save_image(file_storage, user_email, kind="wardrobe"):
            url = f"https://res.cloudinary.com/demo/{kind}/{len(self.saved)}.png"
            file_storage.stream.seek(0)
            self._file_for(url, file_storage.stream.read())
            self.saved.append((user_email, kind, url))
            return url, {"public_id": f"pid{len(self.saved)}", "backend": "cloudinary"}

        def save_bytes(data, user_email, kind="wardrobe", filename_hint="x.png"):
            url = f"https://res.cloudinary.com/demo/{kind}/{len(self.saved)}.png"
            self._file_for(url, data)
            self.saved.append((user_email, kind, url))
            return url, {"public_id": f"pid{len(self.saved)}", "backend": "cloudinary"}

        vt._PROVIDERS["fake"] = FakeProvider

        self.patches = [
            mock.patch.object(self.store, "photos_collection", self.photos),
            mock.patch.object(self.store, "results_collection", self.results),
            mock.patch.object(self.usage, "usage_collection", self.usage_rows),
            mock.patch.object(m, "get_user_wardrobe",
                              side_effect=lambda email: copy.deepcopy(WARDROBES.get(email, []))),
            mock.patch.object(m, "get_user_gender", side_effect=lambda email: GENDERS.get(email)),
            mock.patch.object(m.storage, "save_image", side_effect=save_image),
            mock.patch.object(m.storage, "save_bytes", side_effect=save_bytes),
            mock.patch.object(m.storage, "delete_image", return_value=None),
            mock.patch.object(m.storage, "is_remote_url", side_effect=lambda u: str(u).startswith("https://")),
            mock.patch.object(m.storage, "local_copy_of", side_effect=lambda u: self.files.get(u)),
            mock.patch.object(m.threading, "Thread", _SyncThread),
            mock.patch.object(m.config, "TRYON_PROVIDER", "fake"),
            mock.patch.object(m.config, "TRYON_PROVIDERS", "", create=True),
            mock.patch.object(m.config, "TRYON_FALLBACK_URL", "", create=True),
            mock.patch.object(m.config, "TRYON_MAX_UPLOAD_MB", 2),
            mock.patch.object(vt, "POLL_SECONDS", 0),
        ]
        for p in self.patches:
            p.start()
        from backend import tryon_orchestrator
        tryon_orchestrator.health.reset()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    # ---------------- helpers ----------------

    def _file_for(self, url, data):
        path = os.path.join(self.tmp, f"f{len(self.files)}.bin")
        with open(path, "wb") as handle:
            handle.write(data)
        self.files[url] = path
        return path

    def _headers(self, email=ALICE):
        from flask_jwt_extended import create_access_token
        with self.m.app.app_context():
            return {"Authorization": f"Bearer {create_access_token(identity=email)}"}

    def _upload(self, data=None, email=ALICE, filename="me.png", content_type=None):
        body = {"image": (io.BytesIO(_png() if data is None else data), filename)}
        if content_type:
            body["image"] = (io.BytesIO(_png() if data is None else data), filename, content_type)
        return self.client.post("/api/tryon/photo", data=body, headers=self._headers(email),
                                content_type="multipart/form-data")

    def _generate(self, item_ids, email=ALICE, **extra):
        return self.client.post("/api/tryon/generate", json={"item_ids": item_ids, **extra},
                                headers=self._headers(email))

    def _status(self, job_id, email=ALICE):
        return self.client.get(f"/api/tryon/status/{job_id}", headers=self._headers(email))

    # ---------------- 1. unauthenticated ----------------

    def test_unauthenticated_requests_rejected(self):
        for method, path in [("get", "/api/tryon/capability"), ("get", "/api/tryon/garments"),
                             ("post", "/api/tryon/photo"), ("post", "/api/tryon/generate"),
                             ("get", "/api/tryon/status/abc"), ("get", "/api/tryon/results"),
                             ("delete", "/api/tryon/result/abc")]:
            res = getattr(self.client, method)(path)
            self.assertEqual(res.status_code, 401, path)
        self.assertEqual(FakeProvider.calls, [])

    # ---------------- 2 / 10 / 11. happy path ----------------

    def test_authenticated_single_garment_try_on_succeeds(self):
        self.assertEqual(self._upload().status_code, 200)

        res = self._generate(["a_shirt"])
        self.assertEqual(res.status_code, 202, res.get_json())
        job_id = res.get_json()["job_id"]

        job = self._status(job_id).get_json()["job"]
        self.assertEqual(job["status"], "done", job)
        self.assertTrue(job["image_url"].startswith("https://"))
        self.assertEqual([c["category"] for c in FakeProvider.calls], ["tops"])
        # the garment sent was Alice's own photo of that shirt
        self.assertEqual(FakeProvider.calls[0]["garment"], b"GARMENT:a_shirt")
        # the stored image is exactly what the provider generated
        with open(self.files[job["image_url"]], "rb") as handle:
            self.assertEqual(handle.read(), b"GENERATED-IMAGE1")

    def test_result_belongs_to_authenticated_user_only(self):
        self._upload()
        job_id = self._generate(["a_shirt"]).get_json()["job_id"]

        self.assertEqual(self._status(job_id, email=ALICE).status_code, 200)
        self.assertEqual(self._status(job_id, email=BOB).status_code, 404)

        bob_list = self.client.get("/api/tryon/results", headers=self._headers(BOB)).get_json()
        self.assertEqual(bob_list["results"], [])
        alice_list = self.client.get("/api/tryon/results", headers=self._headers(ALICE)).get_json()
        self.assertEqual([r["job_id"] for r in alice_list["results"]], [job_id])

        # Bob can't delete it either
        res = self.client.delete(f"/api/tryon/result/{job_id}", headers=self._headers(BOB))
        self.assertEqual(res.status_code, 404)
        self.assertIsNotNone(self.store.get_job(job_id, ALICE))

        stored = self.results.find_one({"job_id": job_id})
        self.assertEqual(stored["user_email"], ALICE)
        # the result image was stored under Alice's account
        self.assertIn((ALICE, "tryon-result"), [(e, k) for e, k, _ in self.saved])

    def test_full_outfit_is_layered_in_order(self):
        self._upload()
        res = self._generate(["a_blazer", "a_shirt", "a_jeans"])
        self.assertEqual(res.status_code, 202, res.get_json())
        self.assertEqual([c["category"] for c in FakeProvider.calls], ["bottoms", "tops", "tops"])
        self.assertEqual([c["garment"] for c in FakeProvider.calls],
                         [b"GARMENT:a_jeans", b"GARMENT:a_shirt", b"GARMENT:a_blazer"])

    def test_single_garment_provider_is_never_sent_an_outfit(self):
        self._upload()
        with mock.patch.object(FakeProvider, "supports_layering", False):
            res = self._generate(["a_shirt", "a_jeans"])
        self.assertEqual(res.status_code, 400)
        self.assertIn("one garment at a time", res.get_json()["message"])
        self.assertEqual(FakeProvider.calls, [])

    def test_shoes_are_shown_beside_not_worn(self):
        self._upload()
        res = self._generate(["a_dress", "a_heels"])
        self.assertEqual(res.status_code, 202, res.get_json())
        body = res.get_json()
        self.assertEqual([e["item_id"] for e in body["not_applied"]], ["a_heels"])
        self.assertEqual([c["category"] for c in FakeProvider.calls], ["one-pieces"])

    # ---------------- 3. other user's wardrobe ----------------

    def test_cannot_use_another_users_wardrobe_item(self):
        self._upload(email=ALICE)
        res = self._generate(["b_shirt"], email=ALICE)
        self.assertEqual(res.status_code, 404)
        self.assertEqual(FakeProvider.calls, [])
        self.assertEqual(self.results.docs, [])

    def test_client_supplied_user_id_is_ignored(self):
        self._upload(email=ALICE)
        res = self.client.post("/api/tryon/generate",
                               json={"item_ids": ["b_shirt"], "user_email": BOB},
                               headers=self._headers(ALICE))
        self.assertEqual(res.status_code, 404)
        self.assertEqual(FakeProvider.calls, [])

    def test_garment_list_contains_only_own_items(self):
        res = self.client.get("/api/tryon/garments", headers=self._headers(BOB))
        ids = [i["_id"] for i in res.get_json()["items"]]
        self.assertEqual(ids, ["b_shirt", "b_sherwani"])

    # ---------------- 4. invalid garment ----------------

    def test_invalid_garment_requests_rejected(self):
        self._upload()
        for body in ({}, {"item_ids": []}, {"item_ids": "a_shirt"}, {"item_ids": [{"$ne": 1}]},
                     {"item_ids": ["x" * 200]}):
            res = self.client.post("/api/tryon/generate", json=body, headers=self._headers())
            self.assertEqual(res.status_code, 400, body)
        res = self._generate(["does_not_exist"])
        self.assertEqual(res.status_code, 404)
        self.assertEqual(FakeProvider.calls, [])

    def test_other_gender_category_rejected_and_hidden(self):
        self._upload()
        res = self._generate(["a_sherwani"])
        self.assertEqual(res.status_code, 400)
        self.assertEqual(FakeProvider.calls, [])
        ids = [i["_id"] for i in
               self.client.get("/api/tryon/garments", headers=self._headers()).get_json()["items"]]
        self.assertNotIn("a_sherwani", ids)

    # ---------------- 5. unsupported garment ----------------

    def test_saree_and_lehenga_are_refused_not_remapped(self):
        self._upload()
        for item_id, word in (("a_saree", "saree"), ("a_lehenga", "lehenga")):
            res = self._generate([item_id])
            self.assertEqual(res.status_code, 400)
            body = res.get_json()
            self.assertEqual(body["code"], "unsupported_garment")
            self.assertIn(word, body["message"].lower())
        self.assertEqual(FakeProvider.calls, [])

    def test_sherwani_refused_on_mens_account(self):
        self._upload(email=BOB)
        res = self._generate(["b_sherwani"], email=BOB)
        self.assertEqual(res.status_code, 400)
        self.assertIn("sherwani", res.get_json()["message"].lower())
        self.assertEqual(FakeProvider.calls, [])

    def test_garment_list_labels_support(self):
        items = {i["_id"]: i for i in
                 self.client.get("/api/tryon/garments", headers=self._headers()).get_json()["items"]}
        self.assertTrue(items["a_shirt"]["tryon"]["supported"])
        self.assertEqual(items["a_shirt"]["tryon"]["slot"], "top")
        self.assertEqual(items["a_dress"]["tryon"]["slot"], "one_piece")
        self.assertEqual(items["a_kurta"]["tryon"]["slot"], "top")
        self.assertFalse(items["a_saree"]["tryon"]["supported"])
        self.assertTrue(items["a_saree"]["tryon"]["reason"])
        self.assertTrue(items["a_heels"]["tryon"]["shown_beside"])

    # ---------------- 6 / 7. invalid and oversized images ----------------

    def test_invalid_image_rejected(self):
        res = self._upload(data=b"definitely not an image", filename="notes.txt")
        self.assertEqual(res.status_code, 400)
        self.assertIn("message", res.get_json())
        self.assertEqual(self.saved, [])
        self.assertIsNone(self.photos.find_one({"user_email": ALICE}))

    def test_non_image_content_type_rejected(self):
        res = self._upload(data=b"%PDF-1.4", filename="doc.pdf", content_type="application/pdf")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(self.saved, [])

    def test_tiny_or_landscape_photo_rejected_with_reason(self):
        res = self._upload(data=_png(100, 100))
        self.assertEqual(res.status_code, 400)
        self.assertIn("too small", res.get_json()["message"])
        res = self._upload(data=_png(1600, 800))
        self.assertEqual(res.status_code, 400)
        self.assertIn("wider than it is tall", res.get_json()["message"])
        self.assertEqual(self.saved, [])

    def test_oversized_image_rejected(self):
        big = _png() + b"\0" * (3 * 1024 * 1024)   # limit patched to 2 MB
        res = self._upload(data=big)
        self.assertEqual(res.status_code, 413)
        self.assertIn("MB", res.get_json()["message"])
        self.assertEqual(self.saved, [])

    def test_generate_without_photo_asks_for_one(self):
        res = self._generate(["a_shirt"])
        self.assertEqual(res.status_code, 400)
        self.assertIn("photo", res.get_json()["message"].lower())

    # ---------------- 8. missing configuration ----------------

    def test_missing_provider_configuration_is_reported(self):
        with mock.patch.object(self.m.config, "TRYON_PROVIDER", "huggingface_space"), \
             mock.patch.object(self.m.config, "TRYON_SPACE_ID", ""), \
             mock.patch.object(self.m.config, "HUGGINGFACE_API_TOKEN", ""):
            cap = self.client.get("/api/tryon/capability", headers=self._headers()).get_json()
            self.assertFalse(cap["available"])
            self.assertEqual(cap["message"], "Virtual Try-On is not configured yet.")
            self.assertTrue(any("TRYON_SPACE_ID" in m for m in cap["missing_configuration"]))

            self._upload()
            res = self._generate(["a_shirt"])
            self.assertEqual(res.status_code, 503)
            self.assertEqual(res.get_json()["code"], "not_configured")
        self.assertEqual(FakeProvider.calls, [])

    def test_public_space_without_token_is_configured(self):
        # The token is optional: a public ZeroGPU Space answers anonymous
        # callers (smaller allowance). Only the Space id is required.
        with mock.patch.object(self.m.config, "TRYON_PROVIDER", "huggingface_space"), \
             mock.patch.object(self.m.config, "TRYON_SPACE_ID", "fashn-ai/fashn-vton-1.5"), \
             mock.patch.object(self.m.config, "HUGGINGFACE_API_TOKEN", ""), \
             mock.patch.object(self.vt, "_gradio_client_installed", lambda: True):
            self.assertEqual(self.vt.missing_configuration(), [])
            self.assertTrue(self.m.config.tryon_configured())

    def test_missing_gradio_client_is_reported(self):
        with mock.patch.object(self.m.config, "TRYON_PROVIDER", "huggingface_space"), \
             mock.patch.object(self.m.config, "TRYON_SPACE_ID", "fashn-ai/fashn-vton-1.5"), \
             mock.patch.object(self.vt, "_gradio_client_installed", lambda: False):
            missing = self.vt.missing_configuration()
        self.assertTrue(any("gradio_client" in m for m in missing))

    def test_provider_none_is_not_configured(self):
        with mock.patch.object(self.m.config, "TRYON_PROVIDER", "none"):
            cap = self.client.get("/api/tryon/capability", headers=self._headers()).get_json()
        self.assertFalse(cap["available"])

    # ---------------- 9. provider failure ----------------

    def test_provider_failure_becomes_friendly_error(self):
        self._upload()
        FakeProvider.behaviour = "fail"
        FakeProvider.failure = RuntimeError(
            f"Traceback ... 500 from https://{SECRET_SPACE}.hf.space token={SECRET_TOKEN}")
        job_id = self._generate(["a_shirt"]).get_json()["job_id"]
        job = self._status(job_id).get_json()["job"]
        self.assertEqual(job["status"], "failed")
        self.assertIsNone(job["image_url"])
        self.assertNotIn(SECRET_TOKEN, job["error"])
        self.assertNotIn(SECRET_SPACE, job["error"])
        self.assertNotIn("Traceback", job["error"])

    def test_provider_quota_and_auth_failures_explained(self):
        self._upload()
        FakeProvider.behaviour = "fail"
        for raw, expected in (("GPU quota exceeded", "allowance"),
                              ("401 Unauthorized", "credentials")):
            # Each failure puts the provider into a cooldown; clear it so
            # the second case is a fresh attempt rather than a refused one.
            from backend import tryon_orchestrator
            tryon_orchestrator.health.reset()
            FakeProvider.failure = RuntimeError(raw)
            job_id = self._generate(["a_shirt"]).get_json()["job_id"]
            self.assertIn(expected, self._status(job_id).get_json()["job"]["error"])

    def test_provider_crash_on_submit_is_contained(self):
        self._upload()
        FakeProvider.behaviour = "raise_on_submit"
        FakeProvider.failure = ConnectionError("connection refused")
        job_id = self._generate(["a_shirt"]).get_json()["job_id"]
        job = self._status(job_id).get_json()["job"]
        self.assertEqual(job["status"], "failed")
        self.assertTrue(job["error"])

    def test_provider_timeout_stops_and_cancels(self):
        self._upload()
        FakeProvider.behaviour = "hang"
        clock = iter(range(0, 10000, 100))
        with mock.patch.object(self.vt, "_now", lambda: next(clock)), \
             mock.patch.object(self.m.config, "TRYON_TIMEOUT_SECONDS", 150):
            job_id = self._generate(["a_shirt"]).get_json()["job_id"]
        job = self._status(job_id).get_json()["job"]
        self.assertEqual(job["status"], "failed")
        self.assertIn("too slow", job["error"])
        self.assertTrue(FakeProvider.cancelled)

    def test_cloudinary_failure_reported(self):
        self._upload()
        with mock.patch.object(self.m.storage, "save_bytes",
                               side_effect=self.m.storage.StorageError("cloud down")):
            job_id = self._generate(["a_shirt"]).get_json()["job_id"]
        job = self._status(job_id).get_json()["job"]
        self.assertEqual(job["status"], "failed")
        self.assertIn("couldn't be saved", job["error"])

    def test_photo_upload_storage_failure_reported(self):
        with mock.patch.object(self.m.storage, "save_image",
                               side_effect=self.m.storage.StorageError("cloud down")):
            res = self._upload()
        self.assertEqual(res.status_code, 502)
        self.assertIsNone(self.photos.find_one({"user_email": ALICE}))

    # ---------------- 12. no secrets returned ----------------

    def test_no_secret_or_provider_detail_returned_to_frontend(self):
        self._upload()
        job_id = self._generate(["a_shirt"]).get_json()["job_id"]
        with mock.patch.object(self.m.config, "TRYON_PROVIDER", "huggingface_space"), \
             mock.patch.object(self.m.config, "TRYON_SPACE_ID", SECRET_SPACE), \
             mock.patch.object(self.m.config, "HUGGINGFACE_API_TOKEN", SECRET_TOKEN), \
             mock.patch.object(self.m.config, "CLOUDINARY_API_SECRET", "cloud-secret-xyz", create=True):
            bodies = [
                self.client.get("/api/tryon/capability", headers=self._headers()).get_data(as_text=True),
                self.client.get("/api/tryon/garments", headers=self._headers()).get_data(as_text=True),
                self._status(job_id).get_data(as_text=True),
                self.client.get("/api/tryon/results", headers=self._headers()).get_data(as_text=True),
            ]
        for text in bodies:
            for secret in (SECRET_TOKEN, SECRET_SPACE, "cloud-secret-xyz", "public_id",
                           "user_email", ALICE, "fashn", "provider"):
                self.assertNotIn(secret, text)

    # ---------------- photo lifecycle ----------------

    def test_photo_replace_and_remove(self):
        self._upload()
        first = self.photos.find_one({"user_email": ALICE})["image_url"]
        self._upload(data=_png(700, 1000))
        second = self.photos.find_one({"user_email": ALICE})["image_url"]
        self.assertNotEqual(first, second)
        self.assertEqual(len(self.photos.docs), 1)

        res = self.client.delete("/api/tryon/photo", headers=self._headers())
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(self.photos.find_one({"user_email": ALICE}))

    # ---------------- provider layer (orchestrator) through the API ----------------

    def _second_provider(self, behaviour="succeed"):
        """A second, independent fake provider registered as 'fake_b'."""
        class FakeProviderB(FakeProvider):
            name = "fake_b"
            b_calls = []

            def submit(self, person_bytes, garment_bytes, model_category):
                FakeProviderB.b_calls.append(model_category)
                return {"n": 99}

            def status(self, handle):
                return "done" if behaviour == "succeed" else "failed"

            def result(self, handle):
                if behaviour != "succeed":
                    raise RuntimeError("GPU quota exceeded")
                return b"FROM-B"

        self.vt._PROVIDERS["fake_b"] = FakeProviderB
        self.addCleanup(self.vt._PROVIDERS.pop, "fake_b", None)
        return FakeProviderB

    def test_capability_ready_uses_exact_message_and_hides_provider(self):
        from backend import tryon_orchestrator as orch
        body = self.client.get("/api/tryon/capability", headers=self._headers()).get_json()
        self.assertTrue(body["available"])
        self.assertEqual(body["status"], "ready")
        self.assertEqual(body["message"], orch.MESSAGE_READY)
        self.assertEqual(body["missing_configuration"], [])
        self.assertNotIn("fake", json.dumps(body))

    def test_quota_exhausted_then_page_says_unavailable_and_nothing_is_resubmitted(self):
        from backend import tryon_orchestrator as orch
        self._upload()
        FakeProvider.behaviour = "fail"
        FakeProvider.failure = RuntimeError("You have exceeded your GPU quota (60s requested vs. 0s left). Retry in 3:00:00")
        job_id = self._generate(["a_shirt"]).get_json()["job_id"]
        job = self._status(job_id).get_json()["job"]
        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["error_code"], "QUOTA_EXHAUSTED")
        self.assertNotIn("image_url", {k for k, v in job.items() if v})
        calls_after_failure = len(FakeProvider.calls)

        cap = self.client.get("/api/tryon/capability", headers=self._headers()).get_json()
        self.assertFalse(cap["available"])
        self.assertEqual(cap["status"], "unavailable")
        self.assertEqual(cap["message"], orch.MESSAGE_NONE_AVAILABLE)
        self.assertIn("allowance", cap["reason"])

        # A second attempt is refused up front: no job, no submission.
        jobs_before = len(self.results.docs)
        res = self._generate(["a_shirt"])
        self.assertEqual(res.status_code, 503)
        self.assertEqual(res.get_json()["code"], "unavailable")
        self.assertEqual(len(FakeProvider.calls), calls_after_failure)
        self.assertEqual(len(self.results.docs), jobs_before)

    def test_failover_to_second_provider_is_announced_generically(self):
        from backend import tryon_orchestrator as orch
        B = self._second_provider()
        B.b_calls = []
        self._upload()
        FakeProvider.behaviour = "fail"
        FakeProvider.failure = RuntimeError("No GPU was available after 60s")
        with mock.patch.object(self.m.config, "TRYON_PROVIDERS", "fake,fake_b"):
            job_id = self._generate(["a_shirt"]).get_json()["job_id"]
            job = self._status(job_id).get_json()["job"]
            self.assertEqual(job["status"], "done", job)
            self.assertTrue(job["notice"])
            self.assertEqual(len([s for s in self.saved if s[1] == "tryon-result"]), 1)
            self.assertEqual(B.b_calls, ["tops"])
            # the primary was tried exactly once, never re-submitted
            self.assertEqual(len(FakeProvider.calls), 1)
            with open(self.files[job["image_url"]], "rb") as handle:
                self.assertEqual(handle.read(), b"FROM-B")
            text = json.dumps(job)
            self.assertNotIn("fake_b", text)
            self.assertNotIn('"provider', text)

            cap = self.client.get("/api/tryon/capability", headers=self._headers()).get_json()
            self.assertTrue(cap["available"])
            self.assertEqual(cap["status"], "fallback")
            self.assertEqual(cap["message"], orch.MESSAGE_FALLBACK)
            self.assertNotIn("fake_b", json.dumps(cap))

    def test_all_providers_unavailable_gives_clear_error_and_no_image(self):
        from backend import tryon_orchestrator as orch
        B = self._second_provider(behaviour="fail")
        B.b_calls = []
        self._upload()
        FakeProvider.behaviour = "fail"
        FakeProvider.failure = RuntimeError("GPU quota exceeded")
        with mock.patch.object(self.m.config, "TRYON_PROVIDERS", "fake,fake_b"):
            job_id = self._generate(["a_shirt"]).get_json()["job_id"]
            job = self._status(job_id).get_json()["job"]
        self.assertEqual(job["status"], "failed")
        self.assertIn(orch.MESSAGE_NONE_AVAILABLE, job["error"])
        self.assertFalse(job.get("image_url"))
        self.assertEqual(len(FakeProvider.calls), 1)
        self.assertEqual(B.b_calls, ["tops"])
        # nothing was saved to Cloudinary as a "result"
        self.assertEqual([s for s in self.saved if s[1] == "tryon-result"], [])

    def test_unsupported_input_does_not_fail_over(self):
        B = self._second_provider()
        B.b_calls = []
        self._upload()
        FakeProvider.behaviour = "fail"
        FakeProvider.failure = RuntimeError("NSFW content detected in the input image")
        with mock.patch.object(self.m.config, "TRYON_PROVIDERS", "fake,fake_b"):
            job_id = self._generate(["a_shirt"]).get_json()["job_id"]
            job = self._status(job_id).get_json()["job"]
        self.assertEqual(job["status"], "failed")
        self.assertEqual(B.b_calls, [])   # the other provider's allowance was not spent

    def test_unsupported_garment_answered_even_while_providers_cool_down(self):
        from backend import tryon_orchestrator as orch
        self._upload()
        orch.health.record("fake", self.vt.QUOTA_EXHAUSTED)
        res = self._generate(["a_saree"])
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "unsupported_garment")
        # a supported garment in the same state is refused as unavailable
        res = self._generate(["a_shirt"])
        self.assertEqual(res.status_code, 503)
        self.assertEqual(FakeProvider.calls, [])

    def test_not_configured_reports_setting_names_only(self):
        with mock.patch.object(self.m.config, "TRYON_PROVIDERS", "fashn_space"), \
             mock.patch.object(self.m.config, "TRYON_SPACE_ID", ""):
            cap = self.client.get("/api/tryon/capability", headers=self._headers()).get_json()
            self.assertEqual(cap["status"], "not_configured")
            self.assertIn("TRYON_SPACE_ID", cap["missing_configuration"])
            res = self._generate(["a_shirt"])
            self.assertEqual(res.status_code, 503)
            self.assertEqual(res.get_json()["code"], "not_configured")


    # ---------------- daily limit, as the browser meets it ----------
    # The counter the page shows, the 429 when it runs out, and what
    # does and does not cost an attempt. The arithmetic itself is
    # covered in test_tryon_usage.py; these are about the routes
    # honouring it.

    def test_capability_reports_the_allowance(self):
        cap = self.client.get("/api/tryon/capability",
                              headers=self._headers()).get_json()

        self.assertEqual(cap["usage"]["limit"], 10)
        self.assertEqual(cap["usage"]["remaining"], 10)
        self.assertTrue(cap["usage"]["resets_at"])

    def test_a_successful_generation_costs_one_attempt(self):
        self._upload()

        body = self._generate(["a_shirt"]).get_json()

        self.assertEqual(body["usage"]["remaining"], 9)

        cap = self.client.get("/api/tryon/capability",
                              headers=self._headers()).get_json()
        self.assertEqual(cap["usage"]["remaining"], 9)

    def test_the_eleventh_generation_is_refused_with_429(self):
        self._upload()

        for _ in range(10):
            self.assertEqual(self._generate(["a_shirt"]).status_code, 202)

        res = self._generate(["a_shirt"])
        body = res.get_json()

        self.assertEqual(res.status_code, 429)
        self.assertEqual(body["code"], "daily_limit_reached")
        self.assertIn("10 attempts", body["message"])
        self.assertEqual(body["usage"]["remaining"], 0)

    def test_a_refused_request_never_reaches_the_provider(self):
        self._upload()
        for _ in range(10):
            self._generate(["a_shirt"])

        before = len(FakeProvider.calls)
        self._generate(["a_shirt"])

        self.assertEqual(len(FakeProvider.calls), before)

    def test_another_account_has_its_own_ten(self):
        self._upload()
        for _ in range(10):
            self._generate(["a_shirt"])

        cap = self.client.get("/api/tryon/capability",
                              headers=self._headers(BOB)).get_json()

        self.assertEqual(cap["usage"]["remaining"], 10)

    def test_a_request_rejected_before_generating_costs_nothing(self):
        """
        No photo, no clothes, too many items - none of these reach the
        model, so none of them should cost an attempt.
        """
        self._generate(["a_shirt"])          # refused: no photo yet
        self._generate([])                   # refused: nothing chosen

        cap = self.client.get("/api/tryon/capability",
                              headers=self._headers()).get_json()

        self.assertEqual(cap["usage"]["remaining"], 10)



class GarmentSupportTableTests(unittest.TestCase):
    """The support table itself: no route, no Flask needed."""

    @classmethod
    def setUpClass(cls):
        from backend import virtual_tryon
        from backend import category_catalog
        cls.vt = virtual_tryon
        cls.catalog = category_catalog

    def test_every_catalogue_category_has_an_explicit_decision(self):
        for value in self.catalog.CATALOG:
            support = self.vt.garment_support(value)
            if support["supported"]:
                self.assertIn(support["model_category"], ("tops", "bottoms", "one-pieces"), value)
            else:
                self.assertTrue(support["reason"], value)
                self.assertNotIn("isn't a garment type", support["reason"], value)

    def test_traditional_draped_wear_is_never_remapped(self):
        for value in ("Saree", "Casual Saree", "Wedding Saree", "Lehenga", "Sherwani",
                      "Dhoti Pants", "Anarkali", "Salwar Suit", "Kurta Set (Men)", "Dupatta"):
            self.assertFalse(self.vt.garment_support(value)["supported"], value)
        # legacy classifier names resolve through the catalogue too
        self.assertFalse(self.vt.garment_support("sarees")["supported"])
        self.assertFalse(self.vt.garment_support("sherwanis")["supported"])
        self.assertTrue(self.vt.garment_support("kurta_men")["supported"])
        self.assertTrue(self.vt.garment_support("Denims")["supported"])

    def test_unknown_category_is_unsupported(self):
        self.assertFalse(self.vt.garment_support("Spacesuit")["supported"])
        self.assertFalse(self.vt.garment_support("")["supported"])

    def test_empty_file_and_wrong_format(self):
        self.assertTrue(self.vt.check_person_photo(b""))
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (600, 900)).save(buf, format="GIF")
        problems = self.vt.check_person_photo(buf.getvalue())
        self.assertTrue(problems and "GIF" in problems[0])


if __name__ == "__main__":
    unittest.main()


class HuggingFaceSpaceProviderContractTests(unittest.TestCase):
    """
    The real HuggingFaceSpaceProvider against a stand-in gradio_client,
    to prove the call it makes matches the Space in spaces/tryon/app.py
    (endpoint "/try_on", inputs person_image / garment_image / category)
    and that the token is used but never surfaced.
    """

    def setUp(self):
        from concurrent.futures import Future
        from backend import virtual_tryon, config
        self.vt, self.config = virtual_tryon, config
        self.sent = {}
        out_dir = tempfile.mkdtemp()
        sent = self.sent

        # The official Space's /try_on as its own API description reports
        # it (https://fashn-ai-fashn-vton-1-5.hf.space/gradio_api/info).
        official_parameters = ["person_image", "garment_image", "category",
                               "garment_photo_type", "num_timesteps",
                               "guidance_scale", "seed", "segmentation_free"]
        self.official_parameters = official_parameters

        class FakeClient:
            def __init__(self, src, token=None, verbose=True, **kwargs):
                # Mirrors gradio_client 2.x: "hf_token" is not accepted.
                if "hf_token" in kwargs:
                    raise TypeError("unexpected keyword argument 'hf_token'")
                sent["src"], sent["kwargs"] = src, dict(kwargs, token=token)

            def view_api(self, print_info=True, return_format=None):
                names = sent.get("parameters", official_parameters)
                return {"named_endpoints": {"/try_on": {
                    "parameters": [{"parameter_name": n} for n in names]}}}

            def submit(self, **kwargs):
                sent["submit"] = kwargs
                future = Future()
                if sent.get("fail"):
                    future.set_exception(RuntimeError(f"401 Unauthorized {SECRET_TOKEN}"))
                elif sent.get("fail_with"):
                    future.set_exception(RuntimeError(sent["fail_with"]))
                elif "result" in sent:
                    future.set_result(sent["result"])
                else:
                    path = os.path.join(out_dir, "result.webp")
                    with open(path, "wb") as handle:
                        handle.write(b"RESULT")
                    future.set_result(path)
                return future

        module = types.ModuleType("gradio_client")
        module.Client = FakeClient
        module.handle_file = lambda path: {"path": path}
        self.patches = [
            mock.patch.dict(sys.modules, {"gradio_client": module}),
            mock.patch.object(virtual_tryon, "_gradio_client_installed", lambda: True),
            mock.patch.object(config, "TRYON_SPACE_ID", SECRET_SPACE),
            mock.patch.object(config, "HUGGINGFACE_API_TOKEN", SECRET_TOKEN),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_calls_the_space_contract_and_returns_image(self):
        engine = self.vt.HuggingFaceSpaceProvider()
        self.assertTrue(engine.available())
        data = self.vt._run_pass(engine, _png(), b"garment", "tops", sleep=lambda s: None)
        self.assertEqual(data, b"RESULT")
        self.assertEqual(self.sent["src"], SECRET_SPACE)
        self.assertEqual(self.sent["kwargs"].get("token"), SECRET_TOKEN)
        self.assertEqual(self.sent["submit"]["api_name"], "/try_on")
        self.assertEqual(self.sent["submit"]["category"], "tops")
        # Official Space: wardrobe photos are sent as flat-lay garments;
        # every argument sent is one the endpoint declares.
        self.assertEqual(self.sent["submit"]["garment_photo_type"], "flat-lay")
        self.assertTrue(set(self.sent["submit"]) - {"api_name"} <= set(self.official_parameters))
        # temporary copies of the photos are removed afterwards
        self.assertFalse(os.path.exists(self.sent["submit"]["person_image"]["path"]))

    def test_self_hosted_space_is_not_sent_unknown_arguments(self):
        # spaces/tryon/app.py declares only three inputs.
        self.sent["parameters"] = ["person_image", "garment_image", "category"]
        engine = self.vt.HuggingFaceSpaceProvider()
        self.vt._run_pass(engine, _png(), b"garment", "bottoms", sleep=lambda s: None)
        self.assertEqual(set(self.sent["submit"]),
                         {"person_image", "garment_image", "category", "api_name"})

    def test_anonymous_call_sends_no_token(self):
        with mock.patch.object(self.config, "HUGGINGFACE_API_TOKEN", ""):
            engine = self.vt.HuggingFaceSpaceProvider()
            self.assertTrue(engine.available())
            self.vt._run_pass(engine, _png(), b"garment", "tops", sleep=lambda s: None)
        self.assertIsNone(self.sent["kwargs"].get("token"))

    def test_free_tier_failures_become_clear_messages(self):
        cases = {
            "You have exceeded your GPU quota (60s requested vs. 12s left). Try again in 3:10:00": "allowance",
            "ZeroGPU worker error: No GPU was available": "busy",
            "Queue is full! Please try again later": "busy",
            "429 Too Many Requests": "too many requests",
            "Space fashn-ai/fashn-vton-1.5 is currently sleeping": "starting up",
            "The read operation timed out": "too long",
            "Cannot find a function with api_name /try_on": "changed",
        }
        for raw, expected in cases.items():
            self.sent["fail_with"] = raw
            engine = self.vt.HuggingFaceSpaceProvider()
            with self.assertRaises(self.vt.TryOnUnavailable) as caught:
                self.vt._run_pass(engine, _png(), b"garment", "tops", sleep=lambda s: None)
            self.assertIn(expected, str(caught.exception).lower(), raw)
            self.assertNotIn("fashn-ai", str(caught.exception))

    def test_malformed_result_is_an_error_not_an_image(self):
        self.sent["result"] = {"unexpected": "shape"}
        engine = self.vt.HuggingFaceSpaceProvider()
        with self.assertRaises(self.vt.TryOnUnavailable) as caught:
            self.vt._run_pass(engine, _png(), b"garment", "tops", sleep=lambda s: None)
        self.assertIn("no image", str(caught.exception))

    def test_failure_message_never_contains_token(self):
        self.sent["fail"] = True
        engine = self.vt.HuggingFaceSpaceProvider()
        with self.assertRaises(self.vt.TryOnUnavailable) as caught:
            self.vt._run_pass(engine, _png(), b"garment", "tops", sleep=lambda s: None)
        self.assertNotIn(SECRET_TOKEN, str(caught.exception))
        self.assertNotIn(SECRET_TOKEN, caught.exception.detail)

    def test_refuses_a_category_the_model_does_not_know(self):
        engine = self.vt.HuggingFaceSpaceProvider()
        with self.assertRaises(self.vt.TryOnUnavailable):
            engine.submit(_png(), b"garment", "sarees")
        self.assertNotIn("submit", self.sent)

    def test_share_link_needs_no_token(self):
        with mock.patch.object(self.config, "TRYON_SPACE_ID", "https://abc123.gradio.live"), \
             mock.patch.object(self.config, "HUGGINGFACE_API_TOKEN", ""):
            self.assertEqual(self.vt.HuggingFaceSpaceProvider().missing_configuration(), [])


@unittest.skipUnless(HAVE_DEPS, "Flask/pymongo not installed here - run on the Mac with ai_env")
class TryOnOrchestratorTests(unittest.TestCase):
    """
    The provider layer on its own: discovery, deterministic selection,
    error classification, failover rules, cooldowns. Every provider
    here is a mock - nothing touches the network or any real quota.
    """

    @classmethod
    def setUpClass(cls):
        from backend import virtual_tryon, tryon_orchestrator, config
        cls.vt, cls.orch, cls.config = virtual_tryon, tryon_orchestrator, config

    def setUp(self):
        vt = self.vt
        self.calls = []

        def make(name, categories=("tops", "bottoms", "one-pieces")):
            class P(vt.VirtualTryOnProvider):
                supported_model_categories = categories
                supports_layering = True
                def missing_configuration(self):
                    return []
                def max_passes(self):
                    return 3
            P.name = name
            return P

        registry = dict(vt._PROVIDERS)
        registry.update({"pa": make("pa"), "pb": make("pb"), "pc": make("pc", ("tops",))})
        self.patches = [
            mock.patch.object(vt, "_PROVIDERS", registry),
            mock.patch.object(self.config, "TRYON_PROVIDERS", "pa,pb"),
            mock.patch.object(self.config, "TRYON_FALLBACK_URL", ""),
        ]
        for p in self.patches:
            p.start()
        self.orch.health.reset()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.orch.health.reset()

    def _runner(self, outcomes):
        """outcomes: provider name -> bytes to return, or an exception to raise."""
        def run(engine, person, garment, category):
            self.calls.append(engine.name)
            outcome = outcomes[engine.name]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        return run

    def _down(self, state, text="down"):
        return self.vt.TryOnUnavailable("x", detail=text, state=state)

    # --- interface & discovery ---

    def test_every_registered_provider_implements_the_interface(self):
        for name, cls in self.vt._PROVIDERS.items():
            engine = cls()
            for method in ("missing_configuration", "available", "max_passes",
                           "submit", "status", "result", "cancel"):
                self.assertTrue(callable(getattr(engine, method, None)), f"{name}.{method}")
            self.assertTrue(hasattr(engine, "supported_model_categories"), name)

    def test_discovery_order_and_legacy_settings(self):
        self.assertEqual(self.orch.configured_names(), ["pa", "pb"])
        with mock.patch.object(self.config, "TRYON_PROVIDERS", ""), \
             mock.patch.object(self.config, "TRYON_PROVIDER", "fashn_space"), \
             mock.patch.object(self.config, "TRYON_FALLBACK_URL", "https://abc.gradio.live"):
            self.assertEqual(self.orch.configured_names(), ["fashn_space", "self_hosted"])
        with mock.patch.object(self.config, "TRYON_PROVIDERS", "pa,pa,pb"):
            self.assertEqual(self.orch.configured_names(), ["pa", "pb"])

    def test_unknown_provider_name_is_a_configuration_problem(self):
        with mock.patch.object(self.config, "TRYON_PROVIDERS", "made_up_provider"):
            missing = self.orch.missing_configuration()
            self.assertTrue(missing and "TRYON_PROVIDERS" in missing[0])
            self.assertEqual(self.orch.status_summary()["status"], "not_configured")

    def test_selection_is_deterministic(self):
        for _ in range(5):
            self.assertEqual(self.orch.active().name, "pa")
        summary = self.orch.status_summary()
        self.assertEqual((summary["status"], summary["message"]), ("ready", self.orch.MESSAGE_READY))

    # --- concrete providers ---

    def test_fashn_space_provider_needs_space_id_but_token_is_optional(self):
        with mock.patch.object(self.vt, "_gradio_client_installed", lambda: True), \
             mock.patch.object(self.config, "HUGGINGFACE_API_TOKEN", ""):
            with mock.patch.object(self.config, "TRYON_SPACE_ID", ""):
                self.assertIn("TRYON_SPACE_ID", self.vt.FashnSpaceProvider().missing_configuration())
            with mock.patch.object(self.config, "TRYON_SPACE_ID", "fashn-ai/fashn-vton-1.5"):
                self.assertEqual(self.vt.FashnSpaceProvider().missing_configuration(), [])

    def test_self_hosted_provider_needs_https_link_and_never_gets_hf_token(self):
        with mock.patch.object(self.vt, "_gradio_client_installed", lambda: True), \
             mock.patch.object(self.config, "HUGGINGFACE_API_TOKEN", "hf_secret_should_not_leave"):
            with mock.patch.object(self.config, "TRYON_FALLBACK_URL", ""):
                self.assertTrue(self.vt.SelfHostedGradioProvider().missing_configuration())
            with mock.patch.object(self.config, "TRYON_FALLBACK_URL", "http://insecure.example"):
                self.assertTrue(self.vt.SelfHostedGradioProvider().missing_configuration())
            with mock.patch.object(self.config, "TRYON_FALLBACK_URL", "https://abc123.gradio.live"):
                engine = self.vt.SelfHostedGradioProvider()
                self.assertEqual(engine.missing_configuration(), [])
                self.assertEqual(engine.token, "")

    # --- classification ---

    def test_failure_classification(self):
        vt = self.vt
        cases = [
            ("You have exceeded your GPU quota (60s requested vs. 12s left)", vt.QUOTA_EXHAUSTED),
            ("429 Too Many Requests", vt.RATE_LIMITED),
            ("No GPU was available after 60s", vt.QUEUE_FULL),
            ("Queue is full", vt.QUEUE_FULL),
            ("This Space is sleeping", vt.PROVIDER_SLEEPING),
            ("Read timed out", vt.TIMEOUT),
            ("401 Client Error: Unauthorized", vt.AUTH_ERROR),
            ("Invalid token", vt.AUTH_ERROR),
            ("NSFW content detected", vt.UNSUPPORTED_INPUT),
            ("Cannot find a function with api_name /try_on", vt.CONFIGURATION_ERROR),
            ("Connection refused", vt.TEMPORARILY_UNAVAILABLE),
            ("something odd happened", vt.UNKNOWN_ERROR),
        ]
        for text, expected in cases:
            self.assertEqual(vt.classify_failure(RuntimeError(text))[0], expected, text)
        state, _, retry = vt.classify_failure(RuntimeError("GPU quota exceeded. Retry in 1:30:00"))
        self.assertEqual((state, retry), (vt.QUOTA_EXHAUSTED, 5400))

    def test_every_state_has_a_name(self):
        for state in ("AVAILABLE", "CONFIGURATION_ERROR", "QUOTA_EXHAUSTED", "RATE_LIMITED",
                      "QUEUE_FULL", "PROVIDER_SLEEPING", "TEMPORARILY_UNAVAILABLE", "AUTH_ERROR",
                      "UNSUPPORTED_INPUT", "TIMEOUT", "UNKNOWN_ERROR"):
            self.assertIn(state, self.vt.PROVIDER_STATES)

    # --- failover ---

    def test_success_uses_primary_only(self):
        image, engine = self.orch.run_pass(b"p", b"g", "tops",
                                           run=self._runner({"pa": b"IMG-A", "pb": b"IMG-B"}))
        self.assertEqual((image, engine.name, self.calls), (b"IMG-A", "pa", ["pa"]))

    def test_provider_side_failure_fails_over_once(self):
        for state in (self.vt.QUOTA_EXHAUSTED, self.vt.RATE_LIMITED, self.vt.QUEUE_FULL,
                      self.vt.PROVIDER_SLEEPING, self.vt.TEMPORARILY_UNAVAILABLE,
                      self.vt.TIMEOUT, self.vt.AUTH_ERROR, self.vt.CONFIGURATION_ERROR):
            self.orch.health.reset()
            self.calls = []
            image, engine = self.orch.run_pass(
                b"p", b"g", "tops", run=self._runner({"pa": self._down(state), "pb": b"IMG-B"}))
            self.assertEqual((image, engine.name, self.calls), (b"IMG-B", "pb", ["pa", "pb"]), state)
            self.assertEqual(self.orch.health.state_of("pa"), state)
            summary = self.orch.status_summary()
            self.assertEqual((summary["status"], summary["message"]),
                             ("fallback", self.orch.MESSAGE_FALLBACK))

    def test_input_problems_never_fail_over(self):
        for state in (self.vt.UNSUPPORTED_INPUT, self.vt.UNKNOWN_ERROR):
            self.orch.health.reset()
            self.calls = []
            with self.assertRaises(self.vt.TryOnUnavailable):
                self.orch.run_pass(b"p", b"g", "tops",
                                   run=self._runner({"pa": self._down(state), "pb": b"IMG-B"}))
            self.assertEqual(self.calls, ["pa"], state)
            self.assertEqual(self.orch.health.state_of("pa"), self.vt.AVAILABLE)

    def test_all_unavailable_raises_and_each_provider_tried_once(self):
        with self.assertRaises(self.vt.TryOnUnavailable) as caught:
            self.orch.run_pass(b"p", b"g", "tops", run=self._runner({
                "pa": self._down(self.vt.QUOTA_EXHAUSTED),
                "pb": self._down(self.vt.QUEUE_FULL)}))
        self.assertEqual(self.calls, ["pa", "pb"])
        self.assertIn(self.orch.MESSAGE_NONE_AVAILABLE, str(caught.exception))
        summary = self.orch.status_summary()
        self.assertEqual(summary["status"], "unavailable")
        self.assertIsNone(summary["engine"])
        # a new pass while both cool down submits nothing at all
        self.calls = []
        with self.assertRaises(self.vt.TryOnUnavailable):
            self.orch.run_pass(b"p", b"g", "tops", run=self._runner({"pa": b"x", "pb": b"y"}))
        self.assertEqual(self.calls, [])

    def test_empty_image_is_an_error_not_a_result(self):
        with self.assertRaises(self.vt.TryOnUnavailable):
            self.orch.run_pass(b"p", b"g", "tops", run=self._runner({"pa": b"", "pb": b"IMG-B"}))

    def test_provider_never_sent_unsupported_category(self):
        with mock.patch.object(self.config, "TRYON_PROVIDERS", "pc,pb"):
            image, engine = self.orch.run_pass(b"p", b"g", "bottoms",
                                               run=self._runner({"pc": b"C", "pb": b"B"}))
        self.assertEqual((engine.name, self.calls), ("pb", ["pb"]))

    def test_cooldown_expires_and_honours_retry_after(self):
        now = [1000.0]
        health = self.orch.ProviderHealth(clock=lambda: now[0])
        health.record("pa", self.vt.RATE_LIMITED)
        self.assertEqual(health.state_of("pa"), self.vt.RATE_LIMITED)
        now[0] += self.orch.COOLDOWN_SECONDS[self.vt.RATE_LIMITED] + 1
        self.assertEqual(health.state_of("pa"), self.vt.AVAILABLE)
        health.record("pa", self.vt.QUOTA_EXHAUSTED, retry_after=10)
        now[0] += 11
        self.assertEqual(health.state_of("pa"), self.vt.AVAILABLE)

    def test_timeout_cancels_and_is_a_timeout_state(self):
        class Hanging(self.vt.VirtualTryOnProvider):
            name = "hang"
            cancelled = False
            def submit(self, *a):
                return "h"
            def status(self, handle):
                return "running"
            def cancel(self, handle):
                Hanging.cancelled = True
        ticks = iter(range(0, 10000, 50))
        with self.assertRaises(self.vt.TryOnUnavailable) as caught:
            self.vt._run_pass(Hanging(), b"p", b"g", "tops", timeout=100,
                              sleep=lambda s: None, clock=lambda: next(ticks))
        self.assertEqual(caught.exception.state, self.vt.TIMEOUT)
        self.assertTrue(Hanging.cancelled)

    def test_raw_provider_exception_never_escapes_with_secrets(self):
        class Leaky(self.vt.VirtualTryOnProvider):
            name = "leaky"
            def submit(self, *a):
                raise RuntimeError("401 Unauthorized for token hf_SECRET123 at https://internal.example")
        with self.assertRaises(self.vt.TryOnUnavailable) as caught:
            self.vt._run_pass(Leaky(), b"p", b"g", "tops", timeout=5)
        self.assertEqual(caught.exception.state, self.vt.AUTH_ERROR)
        self.assertNotIn("hf_SECRET123", str(caught.exception))
        self.assertNotIn("internal.example", str(caught.exception))

    def test_timeout_while_still_queued_is_reported_as_queue_full(self):
        class Queued(self.vt.VirtualTryOnProvider):
            name = "queued"
            def submit(self, *a):
                return {"phase": "IN_QUEUE"}
            def status(self, handle):
                return "running"
            def phase(self, handle):
                return handle["phase"]
        ticks = iter(range(0, 10000, 50))
        with self.assertRaises(self.vt.TryOnUnavailable) as caught:
            self.vt._run_pass(Queued(), b"p", b"g", "tops", timeout=100,
                              sleep=lambda s: None, clock=lambda: next(ticks))
        self.assertEqual(caught.exception.state, self.vt.QUEUE_FULL)
