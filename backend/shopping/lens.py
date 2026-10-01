"""
Google Lens through SerpApi - the one product search that can find the
EXACT item from a photo across Myntra, AJIO, Amazon, Flipkart, Nykaa
Fashion and the rest, with real links, prices and stock.

    1. POST the photo to SerpApi's Image API  -> image_id (valid 10 min)
    2. GET  engine=google_lens, type=all      -> visual_matches
    3. GET  engine=google_lens, type=exact_matches (optional)
                                              -> pages showing this
                                                 very picture

The API key is read from the server's .env and sent only to
serpapi.com. It is never logged, never put in an error message and
never returned to the browser - error text below is written by hand
from the failure type, the same rule email_service follows.
"""

import io
import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor

from backend import config

UPLOAD_URL = "https://serpapi.com/image"
SEARCH_URL = "https://serpapi.com/search.json"
TIMEOUT_SECONDS = 25
MAX_UPLOAD_BYTES = 500 * 1024      # SerpApi's Image API limit


class LensError(Exception):
    """`kind` is one of: auth, quota, no_results, bad_image, unavailable."""

    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind
        self.message = message


def prepare_image(image_bytes):
    """JPEG under SerpApi's 500 KB limit, shrinking only as needed."""
    from PIL import Image, ImageOps

    try:
        img = Image.open(io.BytesIO(image_bytes))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except Exception as error:
        raise LensError("bad_image", "The photo could not be read.") from error

    for side, quality in ((1024, 85), (800, 80), (640, 75), (480, 70)):
        copy = img.copy()
        copy.thumbnail((side, side))
        out = io.BytesIO()
        copy.save(out, "JPEG", quality=quality)
        if out.tell() <= MAX_UPLOAD_BYTES:
            return out.getvalue()
    raise LensError("bad_image", "The photo is too large to search with.")


def _describe_api_error(text):
    text = (text or "").lower()
    if "run out of searches" in text or ("plan" in text and "limit" in text):
        return LensError("quota", "This month's free Google Lens searches are used up.")
    if "invalid api key" in text or "api key" in text:
        return LensError("auth", "The SerpApi key on the server was rejected.")
    if "hasn't returned any results" in text or "no results" in text:
        return LensError("no_results", "Google Lens found no matches for this photo.")
    if "image" in text and ("format" in text or "size" in text):
        return LensError("bad_image", "Google Lens could not read this photo.")
    return LensError("unavailable", "Google Lens search is unavailable right now.")


def _open(request):
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        try:
            body = json.loads(error.read().decode("utf-8"))
            raise _describe_api_error(body.get("error"))
        except (ValueError, AttributeError):
            pass
        if error.code in (401, 403):
            raise LensError("auth", "The SerpApi key on the server was rejected.")
        if error.code == 429:
            raise LensError("quota", "Google Lens search limit reached - try again later.")
        raise LensError("unavailable", "Google Lens search is unavailable right now.")
    except (urllib.error.URLError, TimeoutError, OSError):
        raise LensError("unavailable", "Couldn't reach the Google Lens search service.")
    except ValueError:
        raise LensError("unavailable", "Google Lens returned an unreadable answer.")


def upload(jpeg_bytes):
    boundary = uuid.uuid4().hex
    parts = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"api_key\"\r\n\r\n"
        f"{config.SERPAPI_API_KEY}\r\n".encode(),
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; "
        f"filename=\"query.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n".encode(),
        jpeg_bytes,
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    request = urllib.request.Request(
        UPLOAD_URL, data=b"".join(parts), method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    body = _open(request)
    if body.get("error") or not body.get("image_id"):
        raise _describe_api_error(body.get("error"))
    return body["image_id"]


def _search(image_id, kind, query=None):
    params = {
        "engine": "google_lens",
        "image_id": image_id,
        "type": kind,
        "hl": "en",
        "country": config.SHOP_COUNTRY,
        "api_key": config.SERPAPI_API_KEY,
    }
    if query and kind != "exact_matches":
        params["q"] = query
    body = _open(urllib.request.Request(SEARCH_URL + "?" + urllib.parse.urlencode(params)))
    if body.get("error"):
        error = _describe_api_error(body["error"])
        if error.kind == "no_results":
            return []
        raise error
    return body.get("exact_matches" if kind == "exact_matches" else "visual_matches") or []


def _price(raw):
    """(number|None, display text|None, currency|None) from either shape."""
    price = raw.get("price")
    if isinstance(price, dict):
        value = price.get("extracted_value")
        text = price.get("value")
        currency = price.get("currency")
    else:
        value = raw.get("extracted_price")
        text = price if isinstance(price, str) else None
        currency = None
    if not currency and text:
        currency = "₹" if "₹" in text else ("$" if "$" in text else None)
    if currency in ("₹", "Rs", "Rs.", "INR"):
        currency = "INR"
    try:
        value = float(value) if value is not None else None
    except (TypeError, ValueError):
        value = None
    return value, (text.rstrip("*") if text else None), currency


def _stock(raw):
    if raw.get("in_stock") is True:
        return True
    if raw.get("out_of_stock") is True or raw.get("in_stock") is False:
        return False
    return None


def normalise(raw, exact_evidence, position):
    value, text, currency = _price(raw)
    return {
        "title": (raw.get("title") or "").strip(),
        "url": raw.get("link") or "",
        "source": raw.get("source") or "",
        "image": raw.get("thumbnail") or raw.get("image") or "",
        "price": value,
        "price_text": text,
        "currency": currency,
        "in_stock": _stock(raw),
        "exact_evidence": bool(exact_evidence),
        "position": position,
        "provider": "google_lens",
    }


def search(image_bytes, query=None, include_exact=True):
    """
    Returns {"visual": [product, ...], "exact": [product, ...]}.
    Raises LensError when the whole search failed. A failure of only
    the optional exact-match lookup is swallowed (visual results still
    count), so one hiccup never empties the page.
    """
    if not config.shopping_api_configured():
        raise LensError("unavailable", "Google Lens search is not configured on the server.")

    image_id = upload(prepare_image(image_bytes))

    with ThreadPoolExecutor(max_workers=2) as pool:
        visual_future = pool.submit(_search, image_id, "all", query)
        exact_future = pool.submit(_search, image_id, "exact_matches") if include_exact else None

        visual_raw = visual_future.result()
        exact_raw = []
        if exact_future is not None:
            try:
                exact_raw = exact_future.result()
            except LensError:
                exact_raw = []

    # Only the dedicated exact-match lookup counts as evidence that a
    # page shows THIS item. Visual matches carry an "exact_matches"
    # flag too, but its meaning isn't documented precisely enough to
    # justify telling a user "this is the exact product".
    visual = [normalise(item, False, i) for i, item in enumerate(visual_raw)]
    exact = [normalise(item, True, i) for i, item in enumerate(exact_raw)]
    return {"visual": visual, "exact": exact}
