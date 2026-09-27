"""
Cloud-account and migration safety tests.

They exercise the REAL auth.py and migrate_to_atlas.py code against a
small in-memory stand-in for MongoDB, so they never touch Atlas,
Cloudinary or anyone's data:

    python -m unittest backend.tests.test_cloud_accounts -v
"""
import os
import re
import tempfile
import unittest
from unittest import mock

try:
    import bcrypt  # noqa: F401
    import pymongo  # noqa: F401
    HAVE_DEPS = True
except ImportError:
    HAVE_DEPS = False


def _match(doc, flt):
    for key, cond in flt.items():
        if key == "$and":
            if not all(_match(doc, sub) for sub in cond):
                return False
            continue
        value = doc.get(key)
        if isinstance(cond, dict):
            if "$regex" in cond:
                flags = re.I if "i" in cond.get("$options", "") else 0
                if not isinstance(value, str) or not re.search(cond["$regex"], value, flags):
                    return False
            if "$exists" in cond and (key in doc) != cond["$exists"]:
                return False
            if "$ne" in cond and value == cond["$ne"]:
                return False
            if "$type" in cond and not isinstance(value, str):
                return False
        elif value != cond:
            return False
    return True


class FakeCollection:
    def __init__(self, unique_ci=None, unique=None):
        self.docs = []
        self.unique_ci = unique_ci
        self.unique = unique
        self._next = 0

    def _check_unique(self, doc):
        from pymongo.errors import DuplicateKeyError
        if self.unique_ci and doc.get(self.unique_ci) is not None:
            v = str(doc[self.unique_ci]).lower()
            if any(str(d.get(self.unique_ci, "")).lower() == v for d in self.docs):
                raise DuplicateKeyError("dup")
        if self.unique and isinstance(doc.get(self.unique), str):
            if any(d.get(self.unique) == doc[self.unique] for d in self.docs):
                raise DuplicateKeyError("dup")

    def insert_one(self, doc):
        self._check_unique(doc)
        doc = dict(doc)
        self._next += 1
        doc.setdefault("_id", f"id{self._next}")
        self.docs.append(doc)
        return mock.Mock(inserted_id=doc["_id"])

    def find(self, flt=None, projection=None):
        return [dict(d) for d in self.docs if _match(d, flt or {})]

    def find_one(self, flt=None, projection=None):
        found = self.find(flt)
        return found[0] if found else None

    def count_documents(self, flt):
        return len(self.find(flt))

    def update_one(self, flt, update):
        for d in self.docs:
            if _match(d, flt):
                d.update(update.get("$set", {}))
                return

    def create_index(self, *a, **k):
        return "ok"


@unittest.skipUnless(HAVE_DEPS, "bcrypt/pymongo not installed here - run with ai_env")
class CloudAccountTests(unittest.TestCase):

    def setUp(self):
        from backend import auth
        self.auth = auth
        self.users = FakeCollection(unique_ci="email")
        patcher = mock.patch.object(auth, "users_collection", self.users)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_normalize_email(self):
        from backend.identity import normalize_email
        self.assertEqual(normalize_email("  You@Gmail.COM "), "you@gmail.com")
        self.assertEqual(normalize_email(None), "")

    def test_registration_stores_normalised_email_and_hash_not_password(self):
        r = self.auth.register_user("Ganga", " Ganga@Gmail.com ", "secret123", "Female")
        self.assertTrue(r["success"])
        stored = self.users.docs[0]
        self.assertEqual(stored["email"], "ganga@gmail.com")
        self.assertNotIn("secret123", str(stored))
        self.assertTrue(bytes(stored["password_hash"]).startswith(b"$2"))

    def test_same_email_any_case_cannot_register_twice(self):
        self.auth.register_user("Ganga", "ganga@gmail.com", "secret123", "Female")
        r = self.auth.register_user("Ganga 2", "GANGA@GMAIL.COM", "other456", "Female")
        self.assertFalse(r["success"])
        self.assertEqual(len(self.users.docs), 1)

    def test_login_any_case_returns_the_one_canonical_account(self):
        self.auth.register_user("Ganga", "ganga@gmail.com", "secret123", "Female")
        for typed in ("ganga@gmail.com", "Ganga@Gmail.com", "  GANGA@gmail.com "):
            r = self.auth.verify_login(typed, "secret123")
            self.assertTrue(r["success"], typed)
            self.assertEqual(r["email"], "ganga@gmail.com")

    def test_wrong_password_rejected(self):
        self.auth.register_user("Ganga", "ganga@gmail.com", "secret123", "Female")
        r = self.auth.verify_login("ganga@gmail.com", "nope")
        self.assertFalse(r["success"])
        self.assertEqual(r["message"], "Incorrect password")

    def test_legacy_mixed_case_record_is_found_not_duplicated(self):
        import bcrypt
        self.users.docs.append({"_id": "legacy", "name": "G", "email": "Ganga@Gmail.com",
                                "password_hash": bcrypt.hashpw(b"secret123", bcrypt.gensalt())})
        self.assertTrue(self.auth.verify_login("ganga@gmail.com", "secret123")["success"])
        self.assertFalse(self.auth.register_user("G", "ganga@gmail.com", "x123456", "Female")["success"])

    def test_hash_stored_as_string_still_authenticates(self):
        import bcrypt
        self.users.docs.append({"_id": "s", "name": "G", "email": "g@x.com",
                                "password_hash": bcrypt.hashpw(b"pw1234", bcrypt.gensalt()).decode()})
        self.assertTrue(self.auth.verify_login("g@x.com", "pw1234")["success"])

    def test_corrupt_hash_is_reported_not_crashing_or_reset(self):
        self.users.docs.append({"_id": "c", "name": "G", "email": "c@x.com", "password_hash": "plain"})
        r = self.auth.verify_login("c@x.com", "plain")
        self.assertFalse(r["success"])
        self.assertIn("reset", r["message"])
        self.assertEqual(self.users.docs[0]["password_hash"], "plain")


@unittest.skipUnless(HAVE_DEPS, "bcrypt/pymongo not installed here - run with ai_env")
class MigrationTests(unittest.TestCase):

    def setUp(self):
        from backend import migrate_to_atlas as mig, storage
        self.mig = mig
        self.tmp = tempfile.mkdtemp()
        folder = os.path.join(self.tmp, "ganga_digital_wardrobe")
        os.makedirs(folder)
        self.source = {"wardrobe": FakeCollection(), "trips": FakeCollection()}
        for i in range(5):
            with open(os.path.join(folder, f"p{i}.jpg"), "wb") as fh:
                fh.write(f"photo-{i}".encode())
            self.source["wardrobe"].insert_one({
                "_id": f"local{i}", "user_email": "Ganga@Gmail.com", "category": "Saree",
                "color": "red", "image_path": f"/api/uploads/ganga_digital_wardrobe/p{i}.jpg"})
        # same photo as p0 saved twice locally -> must not double the cloud wardrobe
        self.source["wardrobe"].insert_one({
            "_id": "localdup", "user_email": "ganga@gmail.com", "category": "Saree",
            "color": "red", "image_path": "/api/uploads/ganga_digital_wardrobe/p0.jpg"})
        # image missing on this computer -> must not be inserted with a local path
        self.source["wardrobe"].insert_one({
            "_id": "localmissing", "user_email": "ganga@gmail.com", "category": "Top",
            "color": "blue", "image_path": "/api/uploads/ganga_digital_wardrobe/gone.jpg"})
        # someone else's item -> never touched in --only-email mode
        self.source["wardrobe"].insert_one({
            "_id": "other", "user_email": "someone@else.com", "category": "Top",
            "color": "blue", "image_path": "/api/uploads/ganga_digital_wardrobe/p1.jpg"})
        self.dest = {"wardrobe": FakeCollection(unique="migrated_from_id"), "trips": FakeCollection(unique="migrated_from_id")}
        self.uploads = []

        def fake_upload(path, owner, kind="wardrobe", public_id=None):
            self.uploads.append(public_id)
            return f"https://res.cloudinary.com/demo/image/upload/{public_id}.jpg"

        for target, value in ((storage, "BASE_UPLOAD_FOLDER"),):
            patcher = mock.patch.object(target, value, self.tmp)
            patcher.start()
            self.addCleanup(patcher.stop)
        p2 = mock.patch.object(storage, "upload_local_file", side_effect=fake_upload)
        p2.start()
        self.addCleanup(p2.stop)

    def run_once(self, dry_run=False):
        from backend.identity import email_match_filter
        report = self.mig.new_report()
        self.mig.migrate_collection(
            "wardrobe", self.source, self.dest, report, dry_run, True,
            lambda raw: "ganga@gmail.com", email_match_filter("ganga@gmail.com", "user_email"))
        return report

    def test_migrates_owner_items_to_cloud_urls_only(self):
        report = self.run_once()
        docs = self.dest["wardrobe"].docs
        self.assertEqual(report["wardrobe_source"], 7)
        self.assertEqual(len(docs), 5)
        self.assertEqual(report["wardrobe_duplicate_photo"], 1)
        self.assertEqual(len(report["images_missing_on_disk"]), 1)
        self.assertTrue(all(d["image_path"].startswith("https://") for d in docs))
        self.assertTrue(all(d["user_email"] == "ganga@gmail.com" for d in docs))
        self.assertTrue(all(d["category"] for d in docs))
        self.assertFalse(any("uploads" in str(d.get("image_path")) for d in docs))
        self.assertFalse(any("local_image_path" in d for d in docs))

    def test_rerun_is_idempotent(self):
        self.run_once()
        report = self.run_once()
        self.assertEqual(len(self.dest["wardrobe"].docs), 5)
        self.assertEqual(report["wardrobe_migrated"], 0)
        self.assertEqual(report["wardrobe_already_present"], 5)

    def test_dry_run_writes_nothing(self):
        report = self.run_once(dry_run=True)
        self.assertEqual(self.dest["wardrobe"].docs, [])
        self.assertEqual(self.uploads, [])
        self.assertEqual(report["images_to_upload"], 5)

    def test_photo_already_migrated_by_older_script_is_not_duplicated(self):
        # An item the OLD script copied: no fingerprint, only its laptop path.
        self.dest["wardrobe"].insert_one({
            "_id": "old1", "user_email": "ganga@gmail.com", "migrated_from_id": "elsewhere1",
            "image_path": "https://res.cloudinary.com/demo/old.jpg",
            "local_image_path": "/api/uploads/ganga_digital_wardrobe/p2.jpg"})
        report = self.run_once()
        self.assertEqual(report["wardrobe_duplicate_photo"], 2)  # p2 by name, p0 twice by hash
        self.assertEqual(len(self.dest["wardrobe"].docs), 5)     # old1 + p0,p1,p3,p4
        self.assertTrue(all(d.get("original_filename") for d in self.dest["wardrobe"].docs if d["_id"] != "old1"))

    def test_stable_cloudinary_ids(self):
        self.run_once()
        self.assertEqual(sorted(self.uploads), sorted(f"migrated_local{i}" for i in range(5)))


if __name__ == "__main__":
    unittest.main()
