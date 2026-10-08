"""
STYLE & TRENDS / OUTFIT STUDIO - the app's personal-stylist layer.

    "Learn from fashion. Don't copy fashion. Style the user."

Three things are kept strictly apart:

  1. USER WARDROBE      - backend.wardrobe; only ever READ here.
  2. FASHION INSPIRATION - trends.py (published sources) and live.py
                          (optional Pinterest Trends API / news search
                          signals). Never written into the wardrobe.
  3. AI-GENERATED OUTFIT - engine.py, built only from (1) by the
                          existing outfit engine, so every styling rule
                          the app already has (gender, occasion,
                          ethnic/western separation, footwear, colour)
                          still applies.

Modules:
  trends.py    trend catalogue: curated, sourced, dated; personalised
  live.py      optional live signals (Pinterest Trends API, news)
  recipes.py   "does this outfit / wardrobe recreate this trend?"
  naming.py    aesthetic + memorable outfit names
  engine.py    outfit alternatives, wardrobe ideas, explanations
  gaps.py      "what should I shop for?" - the smallest useful purchase
  saved.py     My Saved Outfits
  calendar.py  Outfit Calendar on top of the existing wear_log
"""
