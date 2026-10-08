"""
Optional LIVE trend signals. Nothing here is required: with no keys
configured the Style page uses the curated, sourced catalogue and says
so plainly. Every signal carries where it came from and when.

  * Pinterest - the official Pinterest API v5 "trending keywords"
    endpoint (GET /v5/trends/keywords/{region}/top/{trend_type}).
    Needs PINTEREST_ACCESS_TOKEN (a Pinterest developer app with the
    trends scope). Returns real keywords with real growth figures.
  * News - Google News results through SerpApi (SERPAPI_API_KEY), so
    recent articles can confirm a trend with a dated source.
  * Instagram has no public trends API, and scraping it is against its
    terms - so it is NOT queried. The UI says this instead of pretending.

Results are cached in memory for CACHE_HOURS so a page view never waits
on these services more than once; any failure just means "no live
signals" for that provider.
"""
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

CACHE_HOURS = 12
TIMEOUT_S = 6
_cache = {}


def _now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _get_json(url, headers=None):
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        return json.loads(response.read().decode("utf-8"))


def _cached(key, loader):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_HOURS * 3600:
        return hit[1]
    try:
        value = loader()
    except Exception as error:  # noqa: BLE001 - live data is optional
        print(f"[style] live signal '{key}' unavailable: {type(error).__name__}")
        value = {"ok": False, "signals": [], "error": type(error).__name__}
    _cache[key] = (time.time(), value)
    return value


def pinterest_signals(gender):
    token = os.environ.get("PINTEREST_ACCESS_TOKEN", "").strip()
    if not token:
        return {"ok": False, "configured": False, "signals": []}
    interest = "womens_fashion" if gender == "female" else "mens_fashion"

    def load():
        query = urllib.parse.urlencode({"interests": interest, "limit": 50})
        data = _get_json(
            f"https://api.pinterest.com/v5/trends/keywords/IN/top/growing?{query}",
            headers={"Authorization": f"Bearer {token}"},
        )
        signals = []
        for row in data.get("trends", []):
            keyword = str(row.get("keyword") or "").strip()
            if not keyword:
                continue
            signals.append({
                "provider": "Pinterest Trends API (India)",
                "keyword": keyword,
                "growth_mom": row.get("pct_growth_mom"),
                "growth_yoy": row.get("pct_growth_yoy"),
                "retrieved_at": _now_iso(),
            })
        return {"ok": True, "configured": True, "signals": signals}

    return _cached(f"pinterest:{interest}", load)


def news_signals(gender):
    key = os.environ.get("SERPAPI_API_KEY", "").strip()
    if not key:
        return {"ok": False, "configured": False, "signals": []}
    topic = "womenswear" if gender == "female" else "menswear"

    def load():
        signals = []
        for q in (f"{topic} fashion trends", "Indian ethnic wear trends"):
            query = urllib.parse.urlencode({"engine": "google_news", "q": q, "gl": "in", "hl": "en", "api_key": key})
            data = _get_json(f"https://serpapi.com/search.json?{query}")
            for row in (data.get("news_results") or [])[:15]:
                if not row.get("link") or not row.get("title"):
                    continue
                signals.append({
                    "provider": "News (Google News via SerpApi)",
                    "title": row["title"],
                    "url": row["link"],
                    "source": (row.get("source") or {}).get("name") if isinstance(row.get("source"), dict) else row.get("source"),
                    "published": row.get("date"),
                    "retrieved_at": _now_iso(),
                })
        return {"ok": True, "configured": True, "signals": signals}

    return _cached(f"news:{topic}", load)


def status(gender):
    """What the page should say about live data, without fetching twice."""
    pin = pinterest_signals(gender)
    news = news_signals(gender)
    return {
        "pinterest": {"configured": pin.get("configured", False), "ok": pin.get("ok", False),
                      "count": len(pin.get("signals", []))},
        "news": {"configured": news.get("configured", False), "ok": news.get("ok", False),
                 "count": len(news.get("signals", []))},
        "instagram": {"configured": False, "ok": False, "count": 0,
                      "note": "Instagram has no public trends API, so it isn't queried."},
    }, pin.get("signals", []), news.get("signals", [])
