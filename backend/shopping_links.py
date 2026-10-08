"""
"Shop similar" links for the Find Similar page.

Why this exists
---------------
The page used to show pictures from the DeepFashion and IndoFashion
datasets. Those pictures live only in dataset/ on one laptop (the
folders are shortcuts into that laptop's Downloads and are git-ignored),
so on any other computer, any phone, or any other teammate's machine
they could never load - and even where they did, they were dataset
photos, not anything a user could buy.

This module instead turns what the AI saw (category, colour, pattern)
plus the account's gender into live search links on real stores. The
links are plain URLs: no API keys, no scraping, nothing stored on a
particular machine - so they work for every account, on every device,
and always show the stores' CURRENT stock.

If the query photo has a public https URL (Cloudinary), a Google Lens
link is added too: that one searches by the picture itself, so it finds
the closest-looking products across the whole web.
"""

import re
from urllib.parse import quote, quote_plus

from backend import category_catalog
from backend.category_catalog import FEMALE, MALE, normalize_gender


# Words that read better in a shop's search box than the catalogue
# label does ("Saree / Lehenga Blouse" -> "saree blouse").
_SEARCH_TERMS = {
    "Kurta (Men)": "kurta",
    "Kurta Set (Men)": "kurta pajama set",
    "Kurta (Women)": "kurti",
    "Kurta Set (Women)": "kurta set",
    "Blouse": "saree blouse",
    "Mojaris (Men)": "mojari jutti",
    "Mojaris (Women)": "jutti",
    "Jeans": "jeans",
    "Trousers": "trousers",
    "Cardigan": "sweater",
    "Clutch": "clutch",
    "Bangles": "bangles",
    "Necklace": "necklace",
    "Cap": "cap",
    "Slides": "sliders",
    "Salwar": "salwar",
    "Pajama": "churidar pajama",
    "Track Jacket": "track jacket",
}

# Categories that already say who they are for - adding "women" to
# "saree" just narrows the results for no reason.
_GENDER_IMPLIED = {
    "Saree", "Casual Saree", "Wedding Saree", "Lehenga", "Blouse",
    "Anarkali", "Sharara", "Dupatta", "Sherwani", "Kurta (Women)",
    "Handbag", "Earrings", "Bangles",
}

_GENDER_WORD = {MALE: "men", FEMALE: "women"}

def _budget_words(min_price, max_price):
    """Words shops understand in their search box: "under 1000" etc."""
    if min_price and max_price:
        return f" between {min_price} and {max_price}"
    if max_price:
        return f" under {max_price}"
    if min_price:
        return f" above {min_price}"
    return ""


def _amazon(q, lo, hi):
    url = "https://www.amazon.in/s?k=" + quote_plus(q)
    if lo or hi:  # Amazon's price refinement is in paise
        url += "&rh=" + quote("p_36:{}-{}".format(lo * 100 if lo else "", hi * 100 if hi else ""))
    return url


def _flipkart(q, lo, hi):
    url = "https://www.flipkart.com/search?q=" + quote_plus(q)
    if lo:
        url += "&p%5B%5D=" + quote(f"facets.price_range.from={lo}")
    if hi:
        url += "&p%5B%5D=" + quote(f"facets.price_range.to={hi}")
    return url


def _google(q, lo, hi):
    url = "https://www.google.com/search?tbm=shop&q=" + quote_plus(q)
    if lo or hi:
        parts = ["mr:1", "price:1"]
        if lo:
            parts.append(f"ppr_min:{lo}")
        if hi:
            parts.append(f"ppr_max:{hi}")
        url += "&tbs=" + quote(",".join(parts))
    return url


def _myntra(q, lo, hi):
    q = q + _budget_words(lo, hi)
    slug = re.sub(r"[^a-z0-9]+", "-", q.lower()).strip("-") or "clothing"
    return "https://www.myntra.com/{}?rawQuery={}".format(slug, quote(q))


STORES = [
    # (id, name, url builder(query, min_price, max_price))
    ("myntra", "Myntra", _myntra),
    ("ajio", "AJIO",
     lambda q, lo, hi: "https://www.ajio.com/search/?text=" + quote(q + _budget_words(lo, hi))),
    ("amazon", "Amazon", _amazon),
    ("flipkart", "Flipkart", _flipkart),
    ("meesho", "Meesho",
     lambda q, lo, hi: "https://www.meesho.com/search?q=" + quote_plus(q + _budget_words(lo, hi))),
    ("google", "Google Shopping", _google),
]


def clean_price(value):
    """A whole number of rupees, or None for blank/invalid input."""
    try:
        price = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None
    return price if 0 < price <= 10_000_000 else None


def search_term(category):
    """Shop-friendly words for a category (catalogue value or any name)."""
    if not category:
        return ""
    value = category_catalog.canonical(category) or category
    if value in _SEARCH_TERMS:
        return _SEARCH_TERMS[value]
    entry = category_catalog.CATALOG.get(value)
    label = entry["label"] if entry else str(value)
    label = label.split("/")[0]
    label = re.sub(r"\(.*?\)", "", label).replace("_", " ")
    return " ".join(label.lower().split())


def build_query(category=None, color=None, gender=None, patterned=False):
    """'women navy printed kurti' - empty pieces are simply skipped."""
    value = category_catalog.canonical(category) or category
    words = []
    g = normalize_gender(gender)
    if g in _GENDER_WORD and value not in _GENDER_IMPLIED:
        words.append(_GENDER_WORD[g])
    if color:
        words.append(str(color).strip().lower())
    if patterned:
        words.append("printed")
    term = search_term(category)
    words.append(term or "clothing")
    # de-duplicate while keeping order ("black black jeans")
    seen, out = set(), []
    for word in " ".join(words).split():
        if word not in seen:
            seen.add(word)
            out.append(word)
    return " ".join(out)


def clean_query(text):
    """A user-typed query, trimmed to something safe to put in a URL."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text[:120]


def store_links(query, min_price=None, max_price=None):
    query = clean_query(query) or "clothing"
    lo, hi = clean_price(min_price), clean_price(max_price)
    if lo and hi and lo > hi:
        lo, hi = hi, lo
    return [
        {"store": store_id, "name": name, "url": build(query, lo, hi)}
        for store_id, name, build in STORES
    ]


def lens_url(image_url):
    """Google Lens 'search by this picture' - only for a public https image."""
    if not image_url or not str(image_url).startswith("https://"):
        return None
    return "https://lens.google.com/uploadbyurl?url=" + quote(image_url, safe="")


def shopping_payload(category=None, color=None, gender=None,
                     patterned=False, image_url=None, query=None,
                     min_price=None, max_price=None):
    """Everything the page needs to render the Shop Similar section."""
    final_query = clean_query(query) or build_query(category, color, gender, patterned)
    return {
        "category": category,
        "color": color,
        "patterned": bool(patterned),
        "gender": normalize_gender(gender),
        "query": final_query,
        "links": store_links(final_query, min_price, max_price),
        "min_price": clean_price(min_price),
        "max_price": clean_price(max_price),
        "lens_url": lens_url(image_url),
        "image_url": image_url if lens_url(image_url) else None,
    }
