"""
WHEN THE MODEL IS ALLOWED TO DECIDE, AND WHEN IT MUST ASK.

The classifier is an IndoFashion model. It was trained on sixteen
Indian clothing classes and it has never seen a crop top, bootcut
jeans, or most Western garments at all. Asked about one, it does not
say "I don't know" - it says "Blouse, 0.88", confidently and wrongly.

So the protection cannot be the confidence number alone. These tests
pin the actual rule: a class the model confuses is never applied
silently, however sure it sounds, and the alternatives it is confused
WITH are what the user is offered.

They also pin the other half, which matters just as much: a class the
model is genuinely good at still goes straight through. A gate that
asks about everything is a gate nobody reads.
"""
import os
import unittest

os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017/test")
os.environ.setdefault("JWT_SECRET_KEY", "tests-only")

from backend import category_catalog as catalog


THRESHOLD = 0.45


def decide(label, confidence, runner_up=None, gender="Female"):
    top = [(label, confidence)]
    if runner_up:
        top.append((runner_up, round(1 - confidence, 2)))
    return catalog.classifier_decision(
        {"category": label, "confidence": confidence, "top": top},
        gender, THRESHOLD,
    )


class ConfidentlyWrongLabelsAreNotApplied(unittest.TestCase):
    """The four mistakes that were actually reaching the wardrobe."""

    def _asks(self, decision):
        self.assertNotIn("category", decision,
                         f"applied automatically: {decision.get('category')}")
        return [choice["value"] for choice in decision["choose"]]

    def test_bootcut_jeans_called_leggings_asks_instead(self):
        options = self._asks(decide("Leggings & Salwars", 0.91, "Denims"))
        self.assertIn("Jeans", options)
        self.assertIn("Leggings", options)

    def test_a_crop_top_called_a_blouse_asks_instead(self):
        options = self._asks(decide("Blouse", 0.88, "Top"))
        self.assertIn("Crop Top", options)
        self.assertIn("Blouse", options)

    def test_a_saree_called_a_lehenga_asks_instead(self):
        options = self._asks(decide("Lehenga", 0.80, "Saree"))
        self.assertIn("Saree", options)
        self.assertIn("Lehenga", options)

    def test_a_lehenga_called_a_saree_asks_instead(self):
        options = self._asks(decide("Saree", 0.84, "Lehenga"))
        self.assertIn("Lehenga", options)
        self.assertIn("Saree", options)

    def test_even_near_certainty_does_not_unlock_a_confused_class(self):
        """0.99 on a class the model cannot tell apart is still 0.99 of nothing."""
        for label in ("Blouse", "Saree", "Lehenga", "Dress", "Skirt"):
            self._asks(decide(label, 0.99))

    def test_the_user_is_offered_what_it_is_confused_WITH(self):
        """
        Offering ['Blouse'] alone would be a gate with one door. The
        point is that the real answer is among the choices.
        """
        for label, must_include in (
            ("Blouse", "Crop Top"),
            ("Lehenga", "Saree"),
            ("Saree", "Lehenga"),
            ("Leggings & Salwars", "Jeans"),
        ):
            options = self._asks(decide(label, 0.90))
            self.assertIn(must_include, options, f"{label} did not offer {must_include}")


class ClassesTheModelIsGoodAtStillGoThrough(unittest.TestCase):

    def test_a_confident_shirt_is_applied(self):
        self.assertEqual(decide("Shirt", 0.93, "T-Shirt").get("category"), "Shirt")

    def test_confident_jeans_are_applied(self):
        self.assertEqual(decide("Denims", 0.95, "Pant").get("category"), "Jeans")

    def test_low_confidence_asks_even_for_a_strong_class(self):
        decision = decide("Denims", 0.21, "Pant")
        self.assertNotIn("category", decision)
        self.assertIn("isn't sure", decision["reason"])


class GenderStillFiltersTheChoices(unittest.TestCase):

    def test_a_mens_account_is_never_offered_a_blouse_or_lehenga(self):
        for label in ("Blouse", "Lehenga", "Saree"):
            decision = decide(label, 0.9, gender="Male")
            offered = (
                [decision["category"]] if "category" in decision
                else [choice["value"] for choice in decision["choose"]]
            )
            for women_only in ("Blouse", "Lehenga", "Saree", "Crop Top"):
                self.assertNotIn(women_only, offered,
                                 f"{women_only} offered on a men's account")


class EveryOfferedValueIsRealAndWearable(unittest.TestCase):
    """A choice the rest of the app cannot store is worse than no choice."""

    def test_every_option_exists_in_the_catalog_for_that_gender(self):
        for gender in ("Female", "Male"):
            allowed = set(catalog.values_for(gender))
            for label in catalog.CLASSIFIER_FAMILIES:
                decision = decide(label, 0.9, gender=gender)
                values = (
                    [decision["category"]] if "category" in decision
                    else [choice["value"] for choice in decision["choose"]]
                )
                for value in values:
                    self.assertIn(value, allowed,
                                  f"{label} offered '{value}', not valid for {gender}")


if __name__ == "__main__":
    unittest.main()
