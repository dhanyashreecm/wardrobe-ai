"""
Trend catalogue: curated from published sources (data/trends.json),
optionally confirmed by live signals (live.py), filtered to the
account's gender and personalised to the wardrobe.

Every trend returned carries its sources (publication, title, URL,
date) and a "freshness" field:
  * "curated" - from the dated publications in trends.json
  * "live"    - also confirmed by a live signal retrieved just now
Nothing is called "trending right now" without one of those.
"""
import json
import os
from datetime import datetime
from functools import lru_cache

from backend.category_catalog import normalize_gender
from backend.style_studio import live

DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "trends.json")

# Indian festive season (Navratri - Diwali - wedding season) and winter.
FESTIVE_MONTHS = {9, 10, 11, 12}
WINTER_MONTHS = {11, 12, 1, 2}


@lru_cache(maxsize=1)
def catalogue():
    with open(DATA_FILE, encoding="utf-8") as handle:
        return json.load(handle)


def _sources(trend, registry):
    return [dict(registry[key], id=key) for key in trend.get("sources", []) if key in registry]


def _match_live(trend, pin_signals, news_signals):
    words = [w.lower() for w in trend.get("keywords", [])]
    matched_pins = [s for s in pin_signals if any(w in s["keyword"].lower() for w in words)]
    matched_news = [s for s in news_signals if any(w in s["title"].lower() for w in words)]
    return matched_pins[:3], matched_news[:3]


def trends_for(gender, now=None):
    """All trends for this gender, with sources, confidence, freshness."""
    g = normalize_gender(gender)
    data = catalogue()
    registry = data["sources"]
    live_status, pins, news = live.status(g)
    out = []
    for trend in data["trends"]:
        if g not in trend.get("gender", []):
            continue
        sources = _sources(trend, registry)
        live_pins, live_news = _match_live(trend, pins, news)
        independent = len({s["name"] for s in sources}) + len(live_news)
        out.append({
            **{k: v for k, v in trend.items() if k not in ("sources", "keywords")},
            "sources": sources,
            "live_signals": live_pins + live_news,
            "freshness": "live" if (live_pins or live_news) else "curated",
            "confidence": "high" if independent >= 2 or live_pins else "medium",
            "curated_on": data["curated_on"],
        })
    return out, live_status


def personal_rank(trend, profile, can_recreate, now=None):
    """Higher = shown first. Recreatable + matches the wardrobe's makeup."""
    now = now or datetime.utcnow()
    score = {"yes": 30, "partly": 15, "no": 5, "inspiration": 0}.get(can_recreate, 0)
    indian = trend.get("category") in ("indian", "indo_western")
    share = profile.get("ethnic_share", 0)
    score += 12 * share if indian else 12 * (1 - share)
    if indian and now.month in FESTIVE_MONTHS:
        score += 8
    owned = set(profile.get("colour_words", []))
    if owned & set(trend.get("colors", [])):
        score += 4
    if trend.get("confidence") == "high":
        score += 3
    if trend.get("freshness") == "live":
        score += 5
    return score
