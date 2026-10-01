"""
One "Shop this look" search: Google Lens products when configured,
search links ALWAYS, and a plain-language status for each.

Fallback behaviour (the page shows whichever applies):

  products found          ranked product cards + search links
  Lens found nothing      "no matching products" + search links + retry
  Lens unavailable/quota  search links, with the reason - never fake
                          products, never an empty page
  Lens not configured     search links only

Results are cached in memory per (photo, search words) for
SHOP_CACHE_HOURS, so retrying, re-sorting or reopening the same photo
doesn't spend another search from the monthly allowance. Failures are
never cached.
"""

import hashlib
import threading
import time
from collections import OrderedDict

from backend import config
from backend.shopping import lens
from backend.shopping.analysis import build_query, refine_with_titles
from backend.shopping.ranking import rank
from backend.shopping.retailers import search_links

CACHE_MAX_ENTRIES = 200

_cache = OrderedDict()
_cache_lock = threading.Lock()


def clear_cache():
    with _cache_lock:
        _cache.clear()


def _cache_get(key):
    ttl = config.SHOP_CACHE_HOURS * 3600
    with _cache_lock:
        entry = _cache.get(key)
        if not entry:
            return None
        stored_at, value = entry
        if time.time() - stored_at > ttl:
            _cache.pop(key, None)
            return None
        _cache.move_to_end(key)
        return value


def _cache_put(key, value):
    if config.SHOP_CACHE_HOURS <= 0:
        return
    with _cache_lock:
        _cache[key] = (time.time(), value)
        _cache.move_to_end(key)
        while len(_cache) > CACHE_MAX_ENTRIES:
            _cache.popitem(last=False)


def search(image_bytes, analysis):
    """
    `analysis` is the (cleaned) attribute dict from the browser.
    Returns the JSON-ready result for /api/shop/search.
    """
    query = build_query(analysis)
    result = {
        "query": query,
        "analysis": analysis,
        "products": [],
        "links": search_links(query),
        "provider": {"name": "Google Lens", "configured": config.shopping_api_configured()},
        "status": "links_only",
        "message": "",
        "cached": False,
    }

    if not config.shopping_api_configured():
        result["message"] = ("Product search isn't set up on this server yet, so here are "
                             "searches for this look on each shop.")
        return result

    # The user's own keywords refine Lens; detected words don't (they
    # would only narrow Google's visual matching to our guesses).
    lens_query = analysis.get("keywords") or None
    digest = hashlib.sha256(image_bytes).hexdigest()
    key = (digest, (lens_query or "").lower(), config.SHOP_LENS_EXACT_MATCHES, config.SHOP_COUNTRY)

    raw = _cache_get(key)
    if raw is not None:
        result["cached"] = True
    else:
        try:
            raw = lens.search(image_bytes, lens_query, include_exact=config.SHOP_LENS_EXACT_MATCHES)
        except lens.LensError as error:
            if error.kind == "no_results":
                raw = {"visual": [], "exact": []}
            else:
                result["status"] = "provider_error"
                result["error_kind"] = error.kind
                result["message"] = error.message + " Here are searches for this look on each shop instead."
                return result
        _cache_put(key, raw)

    titles = [p["title"] for p in raw["exact"] + raw["visual"]][:20]
    refined = refine_with_titles(analysis, titles)
    if not analysis.get("keywords"):
        refined_query = build_query(refined)
        if refined_query != query:
            result["query"] = refined_query
            result["links"] = search_links(refined_query)
    result["analysis"] = refined

    products = rank(raw["visual"], raw["exact"], refined)
    result["products"] = products

    if not products:
        result["status"] = "no_results"
        result["message"] = ("No matching products were found in shops for this photo. "
                             "Try the shop searches below, or edit the keywords and search again.")
    elif any(p["match"] == "exact" for p in products):
        result["status"] = "exact_found"
    else:
        result["status"] = "similar_only"
        result["message"] = ("We couldn't verify the exact product online - these are the "
                             "closest matches, labelled by how much they have in common.")
    return result
