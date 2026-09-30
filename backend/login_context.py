"""
WHAT WE CAN HONESTLY SAY ABOUT A LOGIN - for the "new login" email.

Everything here is best effort and deliberately conservative:

  * Device / OS / browser come from the User-Agent header (plus two
    optional hints the frontend sends: whether it is running as the
    installed app, and the device's time zone). A User-Agent can be
    spoofed, so this is descriptive, never used for any security
    decision.
  * Location is reported ONLY when a proxy/CDN we control has already
    worked it out (Cloudflare, Vercel, App Engine geo headers) and
    TRUST_PROXY_HEADERS is on. We never guess from a raw IP, never call
    a third-party lookup service with the user's IP, and never report
    a location for a private/loopback address - "Not available" is
    better than a wrong city in a security email.

No dependencies: a few regexes cover the browsers people really use.
"""

import ipaddress
import re
from datetime import datetime, timezone
from urllib.parse import unquote

from backend import config

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover - Python < 3.9
    ZoneInfo = None
    ZoneInfoNotFoundError = Exception

MAX_HINT_LENGTH = 64


def _clip(value, limit=MAX_HINT_LENGTH):
    if not isinstance(value, str):
        return ""
    return re.sub(r"[\x00-\x1f\x7f]", "", value).strip()[:limit]


# ------------------------------------------------------------------
# USER-AGENT PARSING
# ------------------------------------------------------------------

def _version(pattern, ua):
    match = re.search(pattern, ua)
    if not match:
        return ""
    return match.group(1).split(".")[0]


def parse_user_agent(ua):
    """
    Returns {"os", "device_type", "browser"} from a User-Agent string.
    Unknown parts come back as "" so the caller can say "Unknown".
    """
    ua = _clip(ua or "", 512)
    low = ua.lower()

    # ---- operating system (order matters: iPadOS/Android before Linux) ----
    os_name = ""
    if "windows nt" in low:
        os_name = "Windows"
    elif "ipad" in low:
        os_name = "iPadOS"
    elif "iphone" in low or "ipod" in low:
        os_name = "iOS"
    elif "android" in low:
        version = _version(r"Android (\d+)", ua)
        os_name = f"Android {version}".strip()
    elif "cros" in low:
        os_name = "ChromeOS"
    elif "macintosh" in low or "mac os x" in low:
        # iPads on iPadOS 13+ ask for the desktop site and report as a
        # Mac; "Mobile/" in the UA is the usual giveaway.
        os_name = "iPadOS" if "mobile/" in low else "macOS"
    elif "linux" in low:
        os_name = "Linux"

    if os_name == "iOS":
        version = _version(r"OS (\d+)_", ua)
        os_name = f"iOS {version}".strip()

    # ---- device type ----
    if os_name == "iPadOS" or ("android" in low and "mobile" not in low) or "tablet" in low:
        device_type = "Tablet"
    elif "mobi" in low or os_name.startswith("iOS"):
        device_type = "Mobile"
    elif os_name:
        device_type = "Desktop"
    else:
        device_type = ""

    # ---- browser (order matters: most UAs also claim Chrome/Safari) ----
    browser = ""
    checks = [
        (r"Edg(?:e|A|iOS)?/([\d.]+)", "Microsoft Edge"),
        (r"OPR/([\d.]+)", "Opera"),
        (r"SamsungBrowser/([\d.]+)", "Samsung Internet"),
        (r"(?:Firefox|FxiOS)/([\d.]+)", "Firefox"),
        (r"CriOS/([\d.]+)", "Chrome"),
        (r"Chrome/([\d.]+)", "Chrome"),
        (r"Version/([\d.]+).*Safari/", "Safari"),
    ]
    for pattern, label in checks:
        if re.search(pattern, ua):
            version = _version(pattern, ua)
            browser = f"{label} {version}".strip()
            break

    if not browser and ("; wv)" in low or "wardrobe-ai" in low):
        browser = "Wardrobe-AI app"

    return {"os": os_name, "device_type": device_type, "browser": browser}


# ------------------------------------------------------------------
# IP AND LOCATION
# ------------------------------------------------------------------

def client_ip(request):
    """
    The caller's IP. X-Forwarded-For is only believed when
    TRUST_PROXY_HEADERS is on - otherwise anyone could put any address
    in it.
    """
    if config.TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("CF-Connecting-IP") or \
            (request.headers.get("X-Forwarded-For", "").split(",")[0])
        forwarded = forwarded.strip()
        if forwarded:
            return forwarded
    return request.remote_addr or ""


def _is_public(ip):
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return address.is_global


def approximate_location(request, ip):
    """
    "City, Region, Country" from a trusted proxy's geo headers, or ""
    when it can't be determined reliably.
    """
    if not config.TRUST_PROXY_HEADERS or not _is_public(ip):
        return ""

    headers = request.headers
    city = headers.get("CF-IPCity") or headers.get("X-Vercel-IP-City") \
        or headers.get("X-AppEngine-City") or ""
    region = headers.get("CF-Region") or headers.get("X-Vercel-IP-Country-Region") \
        or headers.get("X-AppEngine-Region") or ""
    country = headers.get("CF-IPCountry") or headers.get("X-Vercel-IP-Country") \
        or headers.get("X-AppEngine-Country") or ""

    # Vercel URL-encodes the city; Cloudflare uses XX / T1 for unknown / Tor.
    city = _clip(unquote(city))
    region = _clip(unquote(region))
    country = _clip(country).upper()
    if country in ("XX", "T1", "ZZ"):
        country = ""

    return ", ".join(part for part in (city, region, country) if part)


# ------------------------------------------------------------------
# TIME
# ------------------------------------------------------------------

def _zone(name):
    if not ZoneInfo or not name:
        return None
    name = _clip(name)
    if not re.match(r"^[A-Za-z_]+(/[A-Za-z0-9_+\-]+){0,2}$", name):
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None


def format_login_time(when_utc, tz_name=None):
    """
    (date_text, time_text) in the device's time zone when it told us a
    valid one, else LOGIN_EMAIL_DEFAULT_TIMEZONE, else UTC.
    """
    if when_utc.tzinfo is None:
        when_utc = when_utc.replace(tzinfo=timezone.utc)

    zone = _zone(tz_name) or _zone(config.LOGIN_EMAIL_DEFAULT_TIMEZONE)
    local = when_utc.astimezone(zone) if zone else when_utc
    label = local.tzname() or "UTC"

    date_text = local.strftime("%A, %d %B %Y")
    time_text = local.strftime("%I:%M %p").lstrip("0") + f" ({label})"
    return date_text, time_text


# ------------------------------------------------------------------
# EVERYTHING TOGETHER
# ------------------------------------------------------------------

def describe_login(request, client_hints=None, when_utc=None):
    """
    The facts for one login notification. `client_hints` is the
    optional {"timezone", "standalone", "platform"} object the frontend
    sends - untrusted, length-limited, and only ever displayed.
    """
    hints = client_hints if isinstance(client_hints, dict) else {}
    when_utc = when_utc or datetime.now(timezone.utc)

    parsed = parse_user_agent(request.headers.get("User-Agent", ""))
    ip = client_ip(request)

    device_bits = [b for b in (parsed["device_type"], parsed["os"]) if b]
    if not parsed["os"]:
        platform_hint = _clip(hints.get("platform"))
        if platform_hint:
            device_bits.append(platform_hint)
    device = " - ".join(device_bits) if device_bits else "Unknown device"

    browser = parsed["browser"] or "Unknown browser"
    if hints.get("standalone") is True:
        browser = f"Wardrobe-AI installed app ({browser})" \
            if parsed["browser"] else "Wardrobe-AI installed app"

    date_text, time_text = format_login_time(when_utc, hints.get("timezone"))

    return {
        "date": date_text,
        "time": time_text,
        "device": device,
        "browser": browser,
        "location": approximate_location(request, ip),
        "ip": ip if _is_public(ip) else "",
    }
