"""Shop-similar links: built from category/colour/gender, no local files."""
import unittest

from backend import shopping_links as s


class ShoppingLinksTest(unittest.TestCase):
    def test_query_uses_gender_colour_and_shop_words(self):
        self.assertEqual(s.build_query("Kurta (Men)", "White", "male"), "men white kurta")
        self.assertEqual(s.build_query("Kurta (Women)", "Navy", "female", True), "navy printed kurti")
        self.assertEqual(s.build_query("Jeans", "Blue", "female"), "women blue jeans")

    def test_gendered_categories_do_not_repeat_gender(self):
        self.assertEqual(s.build_query("Saree", "Red", "female"), "red saree")

    def test_unknown_category_still_gives_a_search(self):
        self.assertEqual(s.build_query(None, None, None), "clothing")

    def test_every_store_link_is_https_and_encoded(self):
        links = s.store_links("men beige shirt")
        self.assertEqual({l["store"] for l in links},
                         {"myntra", "ajio", "amazon", "flipkart", "meesho", "google"})
        for link in links:
            self.assertTrue(link["url"].startswith("https://"))
            self.assertNotIn(" ", link["url"])

    def test_lens_only_for_public_https_images(self):
        self.assertIsNone(s.lens_url("/api/uploads/me/x.jpg"))
        self.assertIsNone(s.lens_url("http://localhost:5001/x.jpg"))
        self.assertTrue(s.lens_url("https://res.cloudinary.com/a/b.jpg").startswith(
            "https://lens.google.com/uploadbyurl?url=https%3A%2F%2F"))

    def test_typed_query_wins_and_is_trimmed(self):
        payload = s.shopping_payload("Shirt", "Beige", "male", query="  green   jersey ")
        self.assertEqual(payload["query"], "green jersey")
        self.assertEqual(s.clean_query("x" * 500), "x" * 120)

    def test_budget_reaches_every_shop(self):
        links = {l["store"]: l["url"] for l in s.store_links("men beige shirt", 500, 1000)}
        self.assertIn("p_36%3A50000-100000", links["amazon"])
        self.assertIn("facets.price_range.from%3D500", links["flipkart"])
        self.assertIn("facets.price_range.to%3D1000", links["flipkart"])
        self.assertIn("ppr_min%3A500%2Cppr_max%3A1000", links["google"])
        for store in ("myntra", "ajio", "meesho"):
            self.assertIn("between", links[store])

    def test_no_budget_leaves_links_unchanged(self):
        self.assertEqual(s.store_links("red saree")[2]["url"], "https://www.amazon.in/s?k=red+saree")

    def test_bad_or_swapped_budget_is_handled(self):
        self.assertIsNone(s.clean_price("abc"))
        self.assertIsNone(s.clean_price(-5))
        url = {l["store"]: l["url"] for l in s.store_links("x", 2000, 500)}["amazon"]
        self.assertIn("p_36%3A50000-200000", url)


if __name__ == "__main__":
    unittest.main()
