"""
Which websites count as SHOPS, and keyword search links for each.

Google Lens returns every page that shows a similar picture: shops,
but also blogs, social media and image boards. Only shops belong in
"Shop this look", so a result is kept when its domain is a known
fashion retailer, or when it carries a real price (Google only
attaches prices to product listings).

Search links are the honest fallback when no product search API is
configured: they open each shop's own search page for words derived
from the photo ("pink embroidered kurta women"). They are labelled as
searches in the UI - never presented as products.
"""

from urllib.parse import quote, quote_plus, urlparse

# domain suffix -> display name. Suffix match, so "www.myntra.com" and
# "m.myntra.com" both count.
RETAILERS = {
    "myntra.com": "Myntra",
    "ajio.com": "AJIO",
    "nykaafashion.com": "Nykaa Fashion",
    "nykaa.com": "Nykaa",
    "amazon.in": "Amazon",
    "amazon.com": "Amazon",
    "flipkart.com": "Flipkart",
    "meesho.com": "Meesho",
    "tatacliq.com": "Tata CLiQ",
    "libas.in": "Libas",
    "biba.in": "BIBA",
    "wforwoman.com": "W for Woman",
    "fabindia.com": "Fabindia",
    "jaypore.com": "Jaypore",
    "westside.com": "Westside",
    "lifestylestores.com": "Lifestyle",
    "shoppersstop.com": "Shoppers Stop",
    "maxfashion.in": "Max Fashion",
    "pantaloons.com": "Pantaloons",
    "manyavar.com": "Manyavar",
    "soch.com": "Soch",
    "aurelia.com": "Aurelia",
    "globaldesi.in": "Global Desi",
    "kalkifashion.com": "Kalki Fashion",
    "lashkaraa.com": "Lashkaraa",
    "utsavfashion.com": "Utsav Fashion",
    "hm.com": "H&M",
    "zara.com": "Zara",
    "uniqlo.com": "Uniqlo",
    "marksandspencer.in": "Marks & Spencer",
    "snitch.co.in": "Snitch",
    "thesouledstore.com": "The Souled Store",
    "bewakoof.com": "Bewakoof",
    "urbanic.com": "Urbanic",
    "levi.in": "Levi's",
    "fabally.com": "FabAlley",
    "jiomart.com": "JioMart",
    "shein.in": "SHEIN",
}

# Never shops, even when Google attaches something price-like.
NOT_SHOPS = (
    "pinterest.", "pinimg.com", "instagram.com", "facebook.com", "youtube.com",
    "tiktok.com", "twitter.com", "x.com", "reddit.com", "tumblr.com", "wikipedia.org",
    "quora.com", "lookaside.", "blogspot.", "wordpress.com", "medium.com",
)


def domain_of(url):
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def retailer_name(url):
    host = domain_of(url)
    for suffix, name in RETAILERS.items():
        if host == suffix or host.endswith("." + suffix):
            return name
    return None


def is_safe_product_url(url):
    """Only plain https/http links are ever shown or saved."""
    try:
        parsed = urlparse(str(url or ""))
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.hostname)


def is_shop_result(url, has_price):
    host = domain_of(url)
    if not host or any(bad in host for bad in NOT_SHOPS):
        return False
    return bool(retailer_name(url)) or bool(has_price)


# ------------------------------------------------------------------
# SEARCH LINKS
# ------------------------------------------------------------------

def _myntra(q):
    slug = "-".join(q.lower().split())
    return f"https://www.myntra.com/{quote(slug)}?rawQuery={quote_plus(q)}"


SEARCH_LINKS = [
    ("Myntra", _myntra),
    ("AJIO", lambda q: f"https://www.ajio.com/search/?text={quote_plus(q)}"),
    ("Nykaa Fashion", lambda q: f"https://www.nykaafashion.com/catalogsearch/result/?q={quote_plus(q)}"),
    ("Amazon", lambda q: f"https://www.amazon.in/s?k={quote_plus(q)}"),
    ("Flipkart", lambda q: f"https://www.flipkart.com/search?q={quote_plus(q)}"),
    ("Meesho", lambda q: f"https://www.meesho.com/search?q={quote_plus(q)}"),
    ("Tata CLiQ", lambda q: f"https://www.tatacliq.com/search/?searchCategory=all&text={quote_plus(q)}"),
    ("Google Shopping", lambda q: f"https://www.google.com/search?tbm=shop&q={quote_plus(q)}"),
]


def search_links(query):
    query = " ".join(str(query or "").split())[:120]
    if not query:
        return []
    return [{"platform": name, "query": query, "url": build(query)}
            for name, build in SEARCH_LINKS]
