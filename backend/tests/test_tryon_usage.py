"""
The daily Virtual Try-On limit: five successful generations per account per day.

These are the rules that decide whether somebody can use the feature,
so they are tested against the real module with a stand-in collection
rather than mocked away. What matters most here is the race test: two
requests arriving together must not both slip past the last remaining
attempt, and the only reason they cannot is that the check and the
increment are one atomic database operation.

Run from the project root:
    python -m unittest backend.tests.test_tryon_usage -v
"""
import threading
import unittest
from datetime import datetime
from unittest import mock

from backend import config
from backend import tryon_usage as usage
from backend.tests.test_virtual_tryon import FakeCollection


# 18:25 UTC is 23:55 in India (+5:30); ten minutes later it is tomorrow.
LATE_YESTERDAY = datetime(2026, 10, 1, 18, 25)
JUST_AFTER_MIDNIGHT = datetime(2026, 10, 1, 18, 35)


class DailyLimitTests(unittest.TestCase):

    def setUp(self):
        self.rows = FakeCollection()
        patch = mock.patch.object(usage, "usage_collection", self.rows)
        patch.start()
        self.addCleanup(patch.stop)

    # -- the basic arithmetic --------------------------------------

    def test_a_new_account_starts_with_five(self):
        snap = usage.snapshot("new@example.com")
        self.assertEqual(snap["limit"], 5)
        self.assertEqual(snap["remaining"], 5)
        self.assertEqual(snap["used"], 0)

    def test_each_attempt_costs_exactly_one(self):
        for taken in range(1, 6):
            granted, snap = usage.reserve("a@example.com")
            self.assertTrue(granted, f"attempt {taken} should be granted")
            self.assertEqual(snap["remaining"], 5 - taken)

    def test_the_sixth_is_refused(self):
        for _ in range(5):
            usage.reserve("a@example.com")

        granted, snap = usage.reserve("a@example.com")

        self.assertFalse(granted)
        self.assertEqual(snap["remaining"], 0)
        # Refusing must not keep counting: a user who tries twenty more
        # times has still only used five.
        self.assertEqual(snap["used"], 5)

    def test_the_refusal_message_is_the_one_the_brief_asked_for(self):
        message = usage.limit_message(usage.snapshot("a@example.com"))
        self.assertIn("all 5 of today's virtual try-ons", message)
        self.assertIn("resets to 5 tomorrow", message)

    # -- resetting --------------------------------------------------

    def test_a_new_day_starts_over(self):
        for _ in range(5):
            usage.reserve("a@example.com", now=LATE_YESTERDAY)

        self.assertEqual(
            usage.snapshot("a@example.com", now=LATE_YESTERDAY)["remaining"], 0)
        self.assertEqual(
            usage.snapshot("a@example.com", now=JUST_AFTER_MIDNIGHT)["remaining"], 5)

    def test_the_day_turns_at_local_midnight_not_utc(self):
        self.assertEqual(usage.today(now=LATE_YESTERDAY), "2026-10-01")
        self.assertEqual(usage.today(now=JUST_AFTER_MIDNIGHT), "2026-10-02")

    def test_the_reset_time_is_reported_and_is_ahead_of_now(self):
        moment = datetime(2026, 10, 1, 12, 0)
        self.assertGreater(usage.next_reset(now=moment), moment)
        self.assertTrue(
            usage.snapshot("a@example.com", now=moment)["resets_at"].endswith("Z"))

    # -- one account's count is its own ------------------------------

    def test_accounts_do_not_share_a_counter(self):
        for _ in range(5):
            usage.reserve("a@example.com")

        self.assertEqual(usage.snapshot("b@example.com")["remaining"], 5)
        self.assertTrue(usage.reserve("b@example.com")[0])
        self.assertEqual(usage.snapshot("a@example.com")["remaining"], 0)

    def test_capitalisation_does_not_create_a_second_allowance(self):
        # Otherwise "Ganga@Gmail.com" would quietly get five more.
        usage.reserve("ganga@example.com")
        self.assertEqual(usage.snapshot("Ganga@Example.COM")["used"], 1)

    # -- the part that actually needs the database -------------------

    def test_simultaneous_requests_cannot_exceed_the_limit(self):
        """
        Forty requests at once must grant exactly five.

        This is the test that would catch a read-then-write
        implementation: with a separate "how many so far?" query, many
        of these threads would read 9 and all decide they were allowed.
        """
        results = []

        def attempt():
            results.append(usage.reserve("race@example.com")[0])

        threads = [threading.Thread(target=attempt) for _ in range(40)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(sum(1 for granted in results if granted), 5)
        self.assertEqual(usage.snapshot("race@example.com")["used"], 5)

    # -- nobody pays for a failure -----------------------------------

    def test_a_refund_returns_one_attempt(self):
        usage.reserve("c@example.com")
        usage.reserve("c@example.com")

        usage.refund("c@example.com")

        self.assertEqual(usage.snapshot("c@example.com")["used"], 1)

    def test_refunds_cannot_mint_attempts(self):
        usage.reserve("c@example.com")

        for _ in range(6):
            usage.refund("c@example.com")

        self.assertEqual(usage.snapshot("c@example.com")["used"], 0)
        self.assertEqual(usage.snapshot("c@example.com")["remaining"], 5)

    def test_a_refund_is_credited_to_the_day_it_was_taken(self):
        """
        An attempt reserved at 23:55 whose generation fails at 00:05
        belongs to yesterday - crediting it to today would hand out an
        sixth attempt.
        """
        usage.reserve("d@example.com", now=LATE_YESTERDAY)

        usage.refund("d@example.com", day=usage.today(now=LATE_YESTERDAY))

        self.assertEqual(
            usage.snapshot("d@example.com", now=LATE_YESTERDAY)["used"], 0)
        self.assertEqual(
            usage.snapshot("d@example.com", now=JUST_AFTER_MIDNIGHT)["used"], 0)

    # -- the number is configuration, not a constant in the page -----

    def test_the_limit_comes_from_configuration(self):
        with mock.patch.object(config, "TRYON_DAILY_LIMIT", 3):
            for _ in range(3):
                self.assertTrue(usage.reserve("e@example.com")[0])
            self.assertFalse(usage.reserve("e@example.com")[0])

    def test_a_database_problem_refuses_rather_than_grants(self):
        """
        An attempt that could not be recorded is an attempt that cannot
        be counted, so the safe answer is no.
        """
        broken = mock.Mock()
        broken.find_one_and_update.side_effect = RuntimeError("database down")
        broken.find_one.return_value = None

        with mock.patch.object(usage, "usage_collection", broken):
            granted, _ = usage.reserve("f@example.com")

        self.assertFalse(granted)

    # -- holds: in flight vs successful ------------------------------

    def test_a_hold_is_not_shown_as_used_but_still_blocks_the_limit(self):
        for n in range(4):
            usage.reserve("h@example.com", hold_id=f"done-{n}")
            usage.settle("h@example.com", f"done-{n}")
        granted, snap = usage.reserve("h@example.com", hold_id="running")
        self.assertTrue(granted)
        self.assertEqual(snap["successful"], 4)
        self.assertEqual(snap["remaining"], 1)   # not lowered before success
        self.assertEqual(snap["in_progress"], 1)
        # ...but a concurrent sixth reservation cannot slip in.
        self.assertFalse(usage.reserve("h@example.com", hold_id="x")[0])

    def test_release_gives_the_attempt_back_exactly_once(self):
        usage.reserve("r@example.com", hold_id="j1")
        self.assertTrue(usage.release("r@example.com", "j1"))
        self.assertFalse(usage.release("r@example.com", "j1"))
        snap = usage.snapshot("r@example.com")
        self.assertEqual((snap["successful"], snap["remaining"], snap["in_progress"]), (0, 5, 0))

    def test_settle_counts_exactly_one(self):
        usage.reserve("s@example.com", hold_id="j1")
        usage.settle("s@example.com", "j1")
        snap = usage.snapshot("s@example.com")
        self.assertEqual((snap["successful"], snap["remaining"]), (1, 4))

    def test_default_limit_is_five(self):
        self.assertEqual(config.TRYON_DAILY_LIMIT, 5)


if __name__ == "__main__":
    unittest.main()
