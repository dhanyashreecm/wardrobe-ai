"""
What the uploaded photo shows, as editable words.

Built only from models this project already runs - garment_classifier
for the type (with the IndoFashion model as the older fallback) and
color_detection for colours - so analysing a photo adds no new model.
Sleeve, neckline, pattern, cut and fabric are then filled in from what
the matched shop listings agree on (refine_with_titles), and the user
can correct any of it on the page.

The analysis is a flat dict of short strings. It goes to the browser
and comes back with the shop search, so the photo is analysed ONCE
per search, not once per request.
"""

from backend.shopping.attributes import (
    GROUPS,
    category_term,
    consensus_from_titles,
    extract_from_text,
)

DETAIL_FIELDS = ("pattern", "sleeve", "neckline", "silhouette", "fabric")
CATEGORY_UNSURE_BELOW = 0.5
MAX_FIELD_LENGTH = 60


def _empty():
    return {
        "category": "", "category_label": "", "category_confidence": None,
        "colour": "", "secondary_colours": [], "patterned": None,
        "pattern": "", "sleeve": "", "neckline": "", "silhouette": "", "fabric": "",
        "audience": "", "keywords": "",
        "sources": {},
        "uncertain": False,
    }


def analyse_photo(image_path, account_gender=None, fallback_category=None):
    """
    Attributes from the photo alone. Each model is optional: whatever
    fails is simply left blank (and the page asks the user to fill it)
    rather than guessed.
    `fallback_category` is the IndoFashion prediction the Find Similar
    route already computes, used only when the main classifier is
    missing.
    """
    analysis = _empty()

    prediction = None
    try:
        from backend import garment_classifier
        if garment_classifier.is_available():
            prediction = garment_classifier.predict(image_path, account_gender)
    except Exception as error:  # noqa: BLE001 - analysis must never fail the search
        print(f"Shop analysis: garment classifier skipped ({type(error).__name__})")

    if not prediction and fallback_category:
        prediction = {"category": fallback_category.get("category"),
                      "confidence": fallback_category.get("confidence")}

    if prediction and prediction.get("category"):
        term, audience = category_term(prediction["category"])
        analysis["category"] = term
        analysis["category_label"] = prediction["category"]
        confidence = prediction.get("confidence")
        analysis["category_confidence"] = round(float(confidence), 2) if confidence is not None else None
        analysis["audience"] = audience or ""
        analysis["sources"]["category"] = "photo"
        if confidence is not None and confidence < CATEGORY_UNSURE_BELOW:
            analysis["uncertain"] = True
    else:
        analysis["uncertain"] = True

    if not analysis["audience"] and account_gender in ("Male", "Female"):
        analysis["audience"] = "women" if account_gender == "Female" else "men"

    try:
        from backend.color_detection import detect_colors
        colours = detect_colors(image_path)
    except Exception as error:  # noqa: BLE001
        print(f"Shop analysis: colour detection skipped ({type(error).__name__})")
        colours = None

    if colours:
        analysis["colour"] = colours.get("primary") or ""
        analysis["secondary_colours"] = list(colours.get("secondary") or [])[:3]
        analysis["patterned"] = colours.get("is_patterned")
        analysis["sources"]["colour"] = "photo"
        if colours.get("confidence") == "low":
            analysis["uncertain"] = True

    return analysis


def refine_with_titles(analysis, titles):
    """
    Fill blank details from what several matched listings agree on.
    Never overwrites anything the photo models or the user supplied.
    """
    refined = dict(analysis)
    refined["sources"] = dict(analysis.get("sources") or {})
    agreed = consensus_from_titles(titles)

    for field in DETAIL_FIELDS:
        if not refined.get(field) and agreed.get(field):
            refined[field] = agreed[field][0][0]
            refined["sources"][field] = "matched products"

    if not refined.get("category") and agreed.get("category"):
        refined["category"] = agreed["category"][0][0]
        refined["sources"]["category"] = "matched products"

    if not refined.get("colour") and agreed.get("colours"):
        refined["colour"] = agreed["colours"][0][0]
        refined["sources"]["colour"] = "matched products"

    return refined


def clean_client_analysis(raw):
    """
    The analysis as sent back by the browser - untrusted, so every
    field is coerced to a short string and anything unknown dropped.
    """
    clean = _empty()
    if not isinstance(raw, dict):
        return clean
    for key in ("category", "category_label", "colour", "audience", "keywords", *DETAIL_FIELDS):
        value = raw.get(key)
        if isinstance(value, str):
            clean[key] = " ".join(value.split())[:MAX_FIELD_LENGTH]
    secondary = raw.get("secondary_colours")
    if isinstance(secondary, list):
        clean["secondary_colours"] = [str(c)[:20] for c in secondary[:3] if isinstance(c, str)]
    if isinstance(raw.get("sources"), dict):
        clean["sources"] = {
            str(k)[:20]: str(v)[:20] for k, v in list(raw["sources"].items())[:12]
        }
    clean["patterned"] = raw.get("patterned") if isinstance(raw.get("patterned"), bool) else None
    clean["uncertain"] = raw.get("uncertain") is True
    return clean


def build_query(analysis):
    """
    Shop search words, most specific first:
        "pink embroidered straight kurta women"
    The user's own keywords win outright when given.
    """
    if analysis.get("keywords"):
        return analysis["keywords"]

    parts = [analysis.get("colour")]
    pattern = analysis.get("pattern")
    if pattern and pattern != "solid":
        parts.append(pattern)
    parts.append(analysis.get("silhouette"))
    parts.append(analysis.get("category"))
    if analysis.get("category"):
        parts.append(analysis.get("audience"))

    words = []
    for part in parts:
        for word in str(part or "").split():
            if word.lower() not in (w.lower() for w in words):
                words.append(word)
    return " ".join(words)


def describe_title(title):
    """Attributes one listing's title mentions (for ranking/display)."""
    return extract_from_text(title)


__all__ = [
    "analyse_photo", "refine_with_titles", "clean_client_analysis",
    "build_query", "describe_title", "DETAIL_FIELDS", "GROUPS",
]
