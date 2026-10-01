"""
VIRTUAL TRY-ON ORCHESTRATOR - which provider does the work, and what
happens when it can't.

Flask routes never talk to a provider directly. They ask this module:

    active()          the provider a new try-on would use right now
    status_summary()  what the Try-On page should tell the user
    run_pass()        one garment onto one photo, with failover

Providers are listed in order in the settings (TRYON_PROVIDERS, e.g.
"fashn_space,self_hosted"). The first one that is configured and not
cooling down is used. When a provider fails for a PROVIDER-SIDE reason -
quota used up, rate limited, queue full, asleep, unreachable, timed
out, credentials rejected - it is marked unavailable for a while and
the SAME pass goes to the next provider. Each provider is tried at most
once per pass, so a job is never re-submitted to a provider that just
refused it, and nothing ever retries in a loop.

When the failure is about the INPUT - an unsupported garment, a photo
the model can't use, a garment photo that can't be loaded - no other
provider would do better, so the error goes straight to the user and no
other provider's allowance is spent.

This never invents a result: every image returned came from a provider.
If every provider is unavailable the caller gets a TryOnUnavailable with
a plain explanation, and the rest of the app is unaffected.

The health record is in memory, per backend process. A restart forgets
it, which costs at most one quick refused request per provider - a
quota refusal does not consume quota.
"""

import threading
import time

from backend import config
from backend import virtual_tryon as vt


# Provider-side problems: another provider may well succeed.
FAILOVER_STATES = {
    vt.QUOTA_EXHAUSTED, vt.RATE_LIMITED, vt.QUEUE_FULL, vt.PROVIDER_SLEEPING,
    vt.TEMPORARILY_UNAVAILABLE, vt.TIMEOUT, vt.AUTH_ERROR, vt.CONFIGURATION_ERROR,
}

# WHAT THE SERVER ACTUALLY LEARNED, which decides whether the user's
# daily attempt is given back at once or held for a while.
#
# CONFIRMED means no image was produced and none ever will be: the
# allowance was refused, the queue turned us away, the Space is asleep
# or unreachable, the credentials were rejected, the settings are
# wrong, or the input cannot be used. Nothing is running anywhere, so
# the attempt goes straight back.
CONFIRMED_FAILURE_STATES = {
    vt.QUOTA_EXHAUSTED, vt.RATE_LIMITED, vt.QUEUE_FULL, vt.PROVIDER_SLEEPING,
    vt.TEMPORARILY_UNAVAILABLE, vt.AUTH_ERROR, vt.CONFIGURATION_ERROR,
    vt.UNSUPPORTED_INPUT,
}

# UNCERTAIN means we stopped waiting, not that the model stopped
# working. A timeout or a lost connection leaves a generation that may
# still finish at the provider's end, so the attempt is held rather
# than refunded - see tryon_usage for how it expires.
UNCERTAIN_STATES = {vt.TIMEOUT, vt.UNKNOWN_ERROR}


def is_confirmed_failure(state):
    """True when the failure definitely produced nothing."""
    return state in CONFIRMED_FAILURE_STATES


# How long a provider is skipped after each kind of failure, unless the
# provider itself said how long ("retry in 3:12:00"). ZeroGPU's daily
# allowance resets 24 h after first use, which the server cannot see,
# so quota is re-checked hourly: a re-check that is refused costs nothing.
COOLDOWN_SECONDS = {
    vt.QUOTA_EXHAUSTED: 3600,
    vt.RATE_LIMITED: 60,
    vt.QUEUE_FULL: 60,
    vt.PROVIDER_SLEEPING: 90,
    vt.TEMPORARILY_UNAVAILABLE: 120,
    vt.TIMEOUT: 120,
    vt.AUTH_ERROR: 1800,
    vt.CONFIGURATION_ERROR: 1800,
}
MAX_COOLDOWN_SECONDS = 24 * 3600

MESSAGE_READY = "Virtual Try-On is ready."
MESSAGE_FALLBACK = (
    "Primary try-on service is temporarily unavailable. Using another "
    "available try-on service."
)
MESSAGE_NONE_AVAILABLE = (
    "Free Virtual Try-On is temporarily unavailable. Your wardrobe and all "
    "other AI Wardrobe features are still available. Try again when a "
    "provider becomes available."
)
MESSAGE_NOT_CONFIGURED = "Virtual Try-On is not configured yet."

# Why no provider is available, in words - most useful reason first.
_REASON_FOR_STATE = {
    vt.QUOTA_EXHAUSTED: "Today's free try-on allowance has been used up (it resets within 24 hours).",
    vt.QUEUE_FULL: "The free try-on GPUs are all busy right now.",
    vt.RATE_LIMITED: "The try-on service is receiving too many requests.",
    vt.PROVIDER_SLEEPING: "The try-on service is starting up.",
    vt.TEMPORARILY_UNAVAILABLE: "The try-on service can't be reached right now.",
    vt.TIMEOUT: "The try-on service was too slow to respond.",
    vt.AUTH_ERROR: "The try-on service rejected this server's credentials.",
    vt.CONFIGURATION_ERROR: "The try-on service settings need attention.",
}
_REASON_ORDER = [vt.QUOTA_EXHAUSTED, vt.QUEUE_FULL, vt.RATE_LIMITED, vt.PROVIDER_SLEEPING,
                 vt.TIMEOUT, vt.TEMPORARILY_UNAVAILABLE, vt.AUTH_ERROR, vt.CONFIGURATION_ERROR]


class ProviderHealth:
    """Thread-safe record of which providers are cooling down, and why."""

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._state = {}  # name -> (state, until)

    def record(self, name, state, retry_after=None):
        seconds = retry_after if retry_after else COOLDOWN_SECONDS.get(state, 120)
        seconds = max(1, min(int(seconds), MAX_COOLDOWN_SECONDS))
        with self._lock:
            self._state[name] = (state, self._clock() + seconds)

    def clear(self, name):
        with self._lock:
            self._state.pop(name, None)

    def state_of(self, name):
        with self._lock:
            entry = self._state.get(name)
            if not entry:
                return vt.AVAILABLE
            state, until = entry
            if self._clock() >= until:
                del self._state[name]
                return vt.AVAILABLE
            return state

    def reset(self):
        with self._lock:
            self._state.clear()


health = ProviderHealth()


# ------------------------------------------------------------
# Which providers exist
# ------------------------------------------------------------

def configured_names():
    """
    Provider names in priority order. TRYON_PROVIDERS ("a,b") wins;
    otherwise the older single TRYON_PROVIDER, followed by the
    self-hosted fallback when TRYON_FALLBACK_URL is set.
    """
    listed = [n.strip() for n in (getattr(config, "TRYON_PROVIDERS", "") or "").split(",") if n.strip()]
    if not listed:
        listed = [config.TRYON_PROVIDER or "none"]
        if getattr(config, "TRYON_FALLBACK_URL", "") and "self_hosted" not in listed:
            listed.append("self_hosted")
    seen, names = set(), []
    for name in listed:
        if name not in seen:
            seen.add(name)
            names.append(name)
    return names


def providers():
    """Provider instances, in order. Unknown names are skipped."""
    return [vt._PROVIDERS[name]() for name in configured_names() if name in vt._PROVIDERS]


def primary():
    """The first configured provider (the 'nothing configured' one if none)."""
    found = providers()
    return found[0] if found else vt.VirtualTryOnProvider()


def _usable(engine):
    return engine.name != "none" and not engine.missing_configuration()


def provider_states():
    """[(provider, state)] in order - for the status summary and logs."""
    out = []
    for engine in providers():
        if engine.name == "none":
            continue
        state = vt.CONFIGURATION_ERROR if engine.missing_configuration() else health.state_of(engine.name)
        out.append((engine, state))
    return out


def active():
    """The provider a new try-on would use now, or None."""
    for engine, state in provider_states():
        if state == vt.AVAILABLE:
            return engine
    return None


def missing_configuration():
    """Setting NAMES still needed when no provider is configured at all."""
    unknown = [n for n in configured_names() if n not in vt._PROVIDERS]
    if unknown:
        return [f"TRYON_PROVIDERS (unknown value {unknown[0]!r}; use: "
                f"{', '.join(sorted(k for k in vt._PROVIDERS if k != 'none'))})"]
    engines = [e for e in providers() if e.name != "none"]
    if not engines:
        return ["TRYON_PROVIDERS"]
    if any(_usable(e) for e in engines):
        return []
    missing = []
    for engine in engines:
        for name in engine.missing_configuration():
            if name not in missing:
                missing.append(name)
    return missing


def status_summary():
    """
    What the Try-On page should say. Never names a provider, a host or a
    setting value:

        {"status": "ready" | "fallback" | "unavailable" | "not_configured",
         "available": bool, "message": str, "reason": str | None,
         "engine": provider or None}
    """
    states = provider_states()
    configured = [(e, s) for e, s in states if not e.missing_configuration()]

    if not configured:
        return {"status": "not_configured", "available": False,
                "message": MESSAGE_NOT_CONFIGURED, "reason": None, "engine": None}

    for index, (engine, state) in enumerate(configured):
        if state == vt.AVAILABLE:
            if index == 0:
                return {"status": "ready", "available": True, "message": MESSAGE_READY,
                        "reason": None, "engine": engine}
            return {"status": "fallback", "available": True, "message": MESSAGE_FALLBACK,
                    "reason": _REASON_FOR_STATE.get(configured[0][1]), "engine": engine}

    present = {state for _, state in configured}
    reason = next((_REASON_FOR_STATE[s] for s in _REASON_ORDER if s in present), None)
    return {"status": "unavailable", "available": False, "message": MESSAGE_NONE_AVAILABLE,
            "reason": reason, "engine": None}


def nothing_available_error(last=None):
    summary = status_summary()
    if summary["status"] == "not_configured":
        return vt.TryOnUnavailable(MESSAGE_NOT_CONFIGURED, detail="no provider configured",
                                   state=vt.CONFIGURATION_ERROR)
    reason = summary.get("reason")
    message = MESSAGE_NONE_AVAILABLE + (f" ({reason})" if reason else "")
    return vt.TryOnUnavailable(
        message,
        detail=f"all providers unavailable; last: {getattr(last, 'detail', '')}",
        state=getattr(last, "state", vt.TEMPORARILY_UNAVAILABLE),
    )


# ------------------------------------------------------------
# Doing the work
# ------------------------------------------------------------

def run_pass(person_bytes, garment_bytes, model_category, prefer=None, run=None):
    """
    One garment onto one photo. Returns (image_bytes, provider_used).

    Order: `prefer` (the provider already used for this outfit) if it is
    still available, then the configured order. Each provider at most
    once. Input problems are raised immediately; provider problems move
    on to the next provider; if none is left, a clear
    TryOnUnavailable - never a made-up image.
    """
    run = run or vt._run_pass
    order = [e for e, s in provider_states() if s == vt.AVAILABLE]
    if prefer is not None:
        order.sort(key=lambda e: 0 if e.name == prefer.name else 1)

    last = None
    for engine in order:
        if model_category not in engine.supported_model_categories:
            continue  # never send a provider a garment type it doesn't know
        try:
            image = run(engine, person_bytes, garment_bytes, model_category)
        except vt.TryOnUnavailable as error:
            if error.state not in FAILOVER_STATES:
                raise  # the same input would fail anywhere - don't spend more allowance
            health.record(engine.name, error.state, error.retry_after)
            print(f"Try-on provider {engine.name} unavailable ({error.state}); "
                  f"trying the next one if configured.")
            last = error
            continue
        if not image:
            raise vt.TryOnUnavailable(
                "The try-on finished but produced no image. Please try again.",
                detail=f"empty image from {engine.name}", state=vt.UNKNOWN_ERROR)
        health.clear(engine.name)
        return image, engine

    raise nothing_available_error(last)
