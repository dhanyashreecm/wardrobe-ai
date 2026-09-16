from collections import defaultdict


# ============================================================
# OUTFIT RECOMMENDATION
# ============================================================

def recommend_outfits(wardrobe_items, occasion="casual"):
    """
    Generate simple complete outfit recommendations
    from the user's wardrobe.

    Uses existing wardrobe categories and occasions.
    No additional AI training required.
    """

    if not wardrobe_items:
        return []


    # --------------------------------------------------------
    # Group wardrobe items by category
    # --------------------------------------------------------

    categories = defaultdict(list)

    for item in wardrobe_items:

        category = item.get("category")

        if not category:
            continue

        category = category.lower().strip()

        categories[category].append(item)


    # --------------------------------------------------------
    # Find tops
    # --------------------------------------------------------

    tops = []

    for category in [
        "shirt",
        "shirts",
        "tshirt",
        "t-shirt",
        "top",
        "tops",
        "blouse",
        "kurta",
        "kurti"
    ]:

        tops.extend(
            categories.get(category, [])
        )


    # --------------------------------------------------------
    # Find bottoms
    # --------------------------------------------------------

    bottoms = []

    for category in [
        "pants",
        "pant",
        "trousers",
        "jeans",
        "shorts",
        "skirt",
        "skirts",
        "bottom",
        "bottoms",
        "leggings"
    ]:

        bottoms.extend(
            categories.get(category, [])
        )


    # --------------------------------------------------------
    # Find dresses / one-piece outfits
    # --------------------------------------------------------

    dresses = []

    for category in [
        "dress",
        "dresses",
        "saree",
        "salwar",
        "lehenga"
    ]:

        dresses.extend(
            categories.get(category, [])
        )


    # --------------------------------------------------------
    # Find accessories
    # --------------------------------------------------------

    accessories = []

    for category in [
        "shoes",
        "shoe",
        "sneakers",
        "bag",
        "bags",
        "watch",
        "jewellery",
        "jewelry",
        "accessory",
        "accessories"
    ]:

        accessories.extend(
            categories.get(category, [])
        )


    recommendations = []


    # ========================================================
    # DRESS / ONE-PIECE OUTFITS
    # ========================================================

    for dress in dresses[:3]:

        outfit = {
            "occasion": occasion,
            "items": [dress],
            "type": "one-piece"
        }

        if accessories:

            outfit["items"].append(
                accessories[0]
            )

        recommendations.append(
            outfit
        )


    # ========================================================
    # TOP + BOTTOM OUTFITS
    # ========================================================

    for top in tops[:5]:

        for bottom in bottoms[:5]:

            outfit = {
                "occasion": occasion,
                "items": [
                    top,
                    bottom
                ],
                "type": "top-bottom"
            }

            if accessories:

                outfit["items"].append(
                    accessories[0]
                )

            recommendations.append(
                outfit
            )


    # ========================================================
    # LIMIT RESULTS
    # ========================================================

    return recommendations[:10]

