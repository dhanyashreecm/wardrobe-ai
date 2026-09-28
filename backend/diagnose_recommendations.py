"""
WHY AM I SEEING THESE RECOMMENDATIONS?

Runs the real recommendation engine over YOUR actual wardrobe, for
every occasion, and prints what comes back - plus the two things that
most often explain a disappointing result.

    python -m backend.diagnose_recommendations your@email.com

It reads the database and nothing else: no item is changed, added or
deleted.

WHAT IT ANSWERS

1. "Every occasion shows me the same outfits."
   The report prints the top five per occasion and then, explicitly,
   which pairs of occasions came back identical. If they really are
   identical, the reason is almost always visible in section 1: a
   wardrobe of six casual items has the same best answer for casual,
   college and a day out, because nothing in it is dressier. That is
   the wardrobe talking, not the ranking.

2. "It paired my jeans with something odd" / "that item is not what
   it says it is."
   Section 2 lists items whose stored category came from the old
   auto-detection, which used to overwrite what you picked. Those
   labels are still in the database - the fix stops NEW uploads being
   renamed, it cannot know what an already-renamed item really was.
   Anything listed there is worth a quick look in the wardrobe page.
"""

import sys
from collections import Counter

from backend.outfit_recommendation import (
    CANONICAL_OCCASIONS,
    infer_occasions_for_category,
    recommend_outfits,
)
from backend.occasion_model import describe_category
from backend.garment_taxonomy import role_for
from backend.wardrobe import get_user_wardrobe
from backend.auth import get_user_gender


# Categories the old auto-detection could write over a user's own
# choice (the 15 IndoFashion classes). An item sitting under one of
# these MIGHT have been renamed from something else.
ETHNIC_AUTO_LABELS = {
    "Blouse", "Dhoti Pants", "Dupatta", "Gown", "Kurta (Men)",
    "Leggings & Salwars", "Lehenga", "Mojaris (Men)", "Mojaris (Women)",
    "Nehru Jacket", "Palazzos", "Petticoat", "Saree", "Sherwani",
    "Kurta (Women)",
}


def main():

    if len(sys.argv) < 2:
        print(__doc__)
        print("Usage: python -m backend.diagnose_recommendations your@email.com")
        return 1

    email = sys.argv[1].strip()

    wardrobe = get_user_wardrobe(email)
    gender = get_user_gender(email)

    if not wardrobe:
        print(f"No wardrobe items found for {email}.")
        print("Check the email is exactly the one you log in with.")
        return 1

    print("=" * 70)
    print(f"WARDROBE REPORT for {email}")
    print("=" * 70)
    print(f"  account gender : {gender or '(not set)'}")
    print(f"  items          : {len(wardrobe)}")

    # ---------------------------------------------------------------
    print("\n" + "=" * 70)
    print("1. WHAT IS IN THE WARDROBE, AND WHAT IT IS ELIGIBLE FOR")
    print("=" * 70)

    by_category = Counter(item.get("category", "(none)") for item in wardrobe)

    eligibility = Counter()

    print(f"\n  {'category':22s} {'n':>3s}  {'role':10s} {'formality':>9s}  eligible for")
    print("  " + "-" * 92)

    for category, count in by_category.most_common():

        occasions = sorted(infer_occasions_for_category(category))

        for occasion in occasions:
            eligibility[occasion] += count

        described = describe_category(category)

        print(f"  {category:22s} {count:3d}  {role_for(category):10s} "
              f"{described['formality']:9.2f}  {', '.join(occasions) or '(none)'}")

    print("\n  How many of your items each occasion can even use:")

    for occasion in CANONICAL_OCCASIONS:
        count = eligibility.get(occasion, 0)
        bar = "#" * min(count, 40)
        note = ""
        if count == 0:
            note = "   <- nothing in your wardrobe suits this"
        elif count < 3:
            note = "   <- very little to choose from"
        print(f"    {occasion:14s} {count:3d} {bar}{note}")

    # ---------------------------------------------------------------
    print("\n" + "=" * 70)
    print("2. ITEMS THAT MAY HAVE BEEN RENAMED BY THE OLD AUTO-DETECTION")
    print("=" * 70)

    suspicious = [
        item for item in wardrobe
        if item.get("category") in ETHNIC_AUTO_LABELS
    ]

    if not suspicious:
        print("\n  None - every item sits under a category the old"
              "\n  auto-detection could not have written.")
    else:
        print(f"\n  {len(suspicious)} item(s) are under a category the old"
              "\n  auto-detection was able to apply. That does NOT mean they"
              "\n  are wrong - it means they are the ones worth checking, and"
              "\n  fixing on the wardrobe page if the label does not match the"
              "\n  photo. Newly uploaded items are protected now; these were"
              "\n  saved before the fix.\n")

        for item in suspicious:
            print(f"    - {item.get('category'):22s} {item.get('color', ''):12s} "
                  f"{item.get('image_path', '')[-40:]}")

    # ---------------------------------------------------------------
    print("\n" + "=" * 70)
    print("3. WHAT THE ENGINE ACTUALLY RETURNS, PER OCCASION")
    print("=" * 70)

    results = {}

    for occasion in CANONICAL_OCCASIONS:

        outfits = recommend_outfits(
            wardrobe, occasion=occasion, account_gender=gender, limit=5,
        )

        signatures = [
            " + ".join(
                f"{item.get('color', '')} {item.get('category', '')}".strip()
                for item in outfit["items"]
            )
            for outfit in outfits
        ]

        results[occasion] = signatures

        print(f"\n  {occasion.upper()}")

        if not signatures:
            print("    (nothing - see section 1 for how many items qualify)")
            continue

        for position, (name, outfit) in enumerate(zip(signatures, outfits), start=1):
            print(f"    {position}. [{outfit['score']:5.1f}] {name}")

    # ---------------------------------------------------------------
    print("\n" + "=" * 70)
    print("4. ARE ANY TWO OCCASIONS RETURNING THE SAME THING?")
    print("=" * 70)

    identical = []

    for index, first in enumerate(CANONICAL_OCCASIONS):
        for second in CANONICAL_OCCASIONS[index + 1:]:

            if results[first] and results[first] == results[second]:
                identical.append((first, second))

    if not identical:
        print("\n  No two occasions returned the same ranked list.")
    else:
        print(f"\n  {len(identical)} pair(s) returned an identical list:\n")
        for first, second in identical:
            print(f"    {first} == {second}")

        print(
            "\n  If those pairs are things like casual/college/day outing,"
            "\n  that is expected: they ask for the same kind of clothes, and"
            "\n  a wardrobe without dressier options genuinely has one best"
            "\n  answer for all three. If a pair like casual == wedding shows"
            "\n  up, that is a real problem - send this report."
        )

    print("\n" + "=" * 70)
    print("Nothing in your wardrobe was changed by this report.")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
