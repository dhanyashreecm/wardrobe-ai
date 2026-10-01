"""
Ranking shop results and labelling HOW similar each one is.

Four labels, strongest first. A label is a claim shown to the user, so
each one needs specific evidence:

  exact          Google Lens's exact-match lookup found this very
                 picture on the product page, and the listing's title
                 doesn't name a different garment. This is the only
                 evidence strong enough to say "this is the product".
  very_similar   Google judged it visually similar AND the title agrees
                 on garment type and colour, plus at least one detail
                 (embroidery, neckline, sleeves...) when any are known.
  similar_style  Google judged it visually similar and the title
                 doesn't contradict the type or colour.
  same_category  Same kind of garment but a different colour.

A listing whose title names a DIFFERENT garment (a saree for a kurta
photo) is dropped unless Google says it's the exact picture.

No similarity PERCENTAGE is given for shop results: Google's ordering
is a ranking, not a calibrated probability, and inventing a number
would overstate it. The card shows which attributes agreed instead.
"""

import re
from urllib.parse import urlparse, urlunparse

from backend.shopping.analysis import DETAIL_FIELDS, describe_title
from backend.shopping.retailers import is_safe_product_url, is_shop_result, retailer_name

LABELS = ("exact", "very_similar", "similar_style", "same_category")
_LABEL_WEIGHT = {"exact": 3.0, "very_similar": 2.0, "similar_style": 1.0, "same_category": 0.0}

# Garments that are close enough to count as "the same type" when a
# title words it differently.
_RELATED = [
    {"kurta", "kurta set"},
    {"top", "t-shirt", "blouse"},
    {"dress", "gown"},
    {"jeans", "trousers"},
    {"jacket", "nehru jacket"},
]


def _same_type(a, b):
    if not a or not b:
        return None
    a, b = a.lower(), b.lower()
    if a == b or a in b or b in a:
        return True
    return any(a in group and b in group for group in _RELATED)


def _colour_agrees(wanted, found_colours):
    if not wanted or not found_colours:
        return None
    wanted = wanted.lower()
    return any(wanted in c or c in wanted for c in found_colours)


def canonical_url(url):
    """Same product page regardless of tracking parameters."""
    try:
        parts = urlparse(url)
    except ValueError:
        return url
    host = (parts.hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    path = re.sub(r"/+$", "", parts.path)
    return urlunparse(("https", host, path, "", "", ""))


def judge(product, analysis):
    """Adds label, score and attribute agreement to one product."""
    title_attrs = describe_title(product["title"])

    type_ok = _same_type(analysis.get("category"), title_attrs.get("category"))
    colour_ok = _colour_agrees(analysis.get("colour"), title_attrs.get("colours"))

    matched, differs = [], []
    if type_ok:
        matched.append("type")
    elif type_ok is False:
        differs.append("type")
    if colour_ok:
        matched.append("colour")
    elif colour_ok is False:
        differs.append("colour")

    details_known = 0
    for field in DETAIL_FIELDS:
        wanted = analysis.get(field)
        found = title_attrs.get(field) or []
        if wanted and found:
            details_known += 1
            (matched if wanted in found else differs).append(field)
    detail_hits = sum(1 for f in DETAIL_FIELDS if f in matched)

    if type_ok is False and not product["exact_evidence"]:
        return None

    if product["exact_evidence"]:
        label = "exact"
    elif type_ok and colour_ok and (detail_hits >= 1 or details_known == 0):
        label = "very_similar"
    elif type_ok and colour_ok is False:
        # Right garment, wrong colour: the only thing confirmed is type.
        label = "same_category"
    else:
        # Google judged it visually similar and nothing contradicts that.
        label = "similar_style"

    # Position in Google's own ordering is the visual signal (earlier =
    # closer); title agreement is the descriptive one.
    visual = 1.0 / (1 + product.get("position", 0))
    agreement = (len(matched) - 0.5 * len(differs)) / 6.0
    product = dict(product)
    product.update({
        "match": label,
        "matched_attributes": matched,
        "different_attributes": differs,
        # What the listing's own title says - used by the page's
        # category/colour filters.
        "title_category": title_attrs.get("category") or "",
        "title_colours": title_attrs.get("colours") or [],
        "score": round(_LABEL_WEIGHT[label] + visual + agreement, 4),
    })
    return product


def rank(visual, exact, analysis, limit=40):
    """
    Merge exact and visual results, keep only shops, drop duplicates,
    label and sort. Returns the products, best first.
    """
    merged, seen_urls, seen_titles = [], set(), set()

    # Exact results first so a page found by both keeps its exact flag.
    for product in list(exact) + list(visual):
        url = product.get("url") or ""
        if not product.get("title") or not is_safe_product_url(url):
            continue
        if not is_shop_result(url, product.get("price") is not None):
            continue

        key = canonical_url(url)
        platform = retailer_name(url) or product.get("source") or ""
        title_key = (platform.lower(), re.sub(r"\W+", " ", product["title"].lower()).strip())
        if key in seen_urls or title_key in seen_titles:
            continue
        seen_urls.add(key)
        seen_titles.add(title_key)

        product = dict(product, platform=platform, url=url)
        if product.get("image") and not is_safe_product_url(product["image"]):
            product["image"] = ""
        judged = judge(product, analysis)
        if judged:
            merged.append(judged)

    merged.sort(key=lambda p: -p["score"])
    for index, product in enumerate(merged[:limit]):
        product["id"] = f"p{index}"
    return merged[:limit]


# ------------------------------------------------------------------
# WARDROBE MATCH LEVELS
#
# The wardrobe search compares MobileNetV2 image features by cosine
# similarity. Those features are never negative, so even unrelated
# clothes score around 0.4-0.6; the numbers below were chosen for that
# scale. They are labels for the user, not probabilities.
# ------------------------------------------------------------------

WARDROBE_VERY_CLOSE = 0.85
WARDROBE_SIMILAR = 0.70


def wardrobe_match_level(similarity):
    if similarity is None:
        return "loose"
    if similarity >= WARDROBE_VERY_CLOSE:
        return "very_close"
    if similarity >= WARDROBE_SIMILAR:
        return "similar"
    return "loose"


def wardrobe_summary(results):
    """
    "very_close" - you probably own this already
    "similar"    - you have something like it
    "none"       - nothing suitable in the wardrobe
    """
    best = max((r.get("similarity") or 0 for r in results), default=0)
    level = wardrobe_match_level(best) if results else "loose"
    return "none" if level == "loose" else level
