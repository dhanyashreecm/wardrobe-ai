"""
VIRTUAL TRY-ON: putting the user's own clothes onto the user's own photo.

WHY THE MODEL RUNS SOMEWHERE ELSE

Realistic try-on means a diffusion model, which means a CUDA GPU.
Neither machine on this project has one, so the model runs on a
Hugging Face ZeroGPU Space and this module calls it. That is a
deliberate architectural choice, not a shortcut: the alternative -
CPU inference on a laptop - takes many minutes per image and would
freeze during a demo.

WHICH MODEL, AND WHY

FASHN VTON v1.5, under Apache-2.0. Nearly every well-known open
try-on model (IDM-VTON, CatVTON, OOTDiffusion, StableVITON, VITON-HD,
HR-VITON) is CC BY-NC-SA 4.0, which forbids commercial use; the two
permissive alternatives, DCI-VTON (MIT) and ViViD (Apache-2.0), are
either older or built for video. FASHN v1.5 is a current production
model released permissively, and it is MASKLESS, which matters here
for more than speed: segmentation, pose estimation, garment warping,
occlusion and lighting all happen INSIDE the model. This module
therefore does not - and should not - bolt a second pose estimator or
segmentation step in front of it. Doing so would be duplicated work
that could only make the result worse.

WHAT THIS MODULE IS RESPONSIBLE FOR

  - deciding, from ONE explicit table keyed on category_catalog, which
    wardrobe items CAN be worn (tops, bottoms, one-pieces, jackets) and
    which cannot (sarees, lehengas, sherwanis and other draped or
    multi-piece traditional wear; footwear; accessories) - and saying
    why, instead of re-mapping them to something the model can do,
  - turning an outfit into an ordered sequence of single-garment
    passes, because the model wears one garment at a time,
  - fetching each garment's real photo from wherever storage.py put
    it, so the user sees their own clothes rather than a lookalike,
  - checking the user's photo is usable and saying plainly what to
    fix when it is not,
  - never letting a provider failure become anything worse than an
    honest error message.

WHAT IT CANNOT DO, STATED HERE RATHER THAN DISCOVERED LATER

  Footwear and accessories. No current try-on model renders shoes,
  bags or jewellery onto a person. They are returned in
  `not_applied` so the interface can show them beside the result
  instead of pretending they were worn.

  A full outfit costs more than one generation. Top and bottom are
  separate passes, the second applied to the first's output. That
  doubles both the wait and the GPU allowance used.

  The provider is swappable (config.TRYON_PROVIDER): any service that
  implements VirtualTryOnProvider (submit / status / result / cancel)
  can replace the self-hosted Space without anything above this module
  changing.
"""

import io
import logging
import os
import tempfile
import time

from backend import config
from backend import category_catalog
from backend import storage


logger = logging.getLogger(__name__)


# ============================================================
# WHAT THE MODEL CAN WEAR - one explicit table, by catalogue category
#
# Keyed on backend/category_catalog.py values (the ONE category system
# in this project; legacy names resolve through category_catalog
# .canonical). Every garment category is listed deliberately rather
# than guessed from its name, because the failure this prevents is a
# quiet one: sending a saree to a model built for tops, bottoms and
# dresses does not raise an error - it returns a confident, wrong
# picture.
#
# FASHN VTON v1.5 accepts exactly three garment categories: "tops",
# "bottoms" and "one-pieces". It was trained on western-cut garments.
# So:
#
#   SUPPORTED   shirts, T-shirts, tops, jackets, trousers, jeans,
#               skirts, dresses, gowns, jumpsuits - and the Indian
#               garments that are structurally one of those (a kurta
#               is a long tunic top; a salwar or churidar is a pair of
#               trousers; a Nehru jacket is a sleeveless jacket).
#
#   UNSUPPORTED draped or multi-piece traditional wear - saree, lehenga,
#               sherwani, dhoti, anarkali, kurta sets, salwar suits,
#               dupattas - and all footwear and accessories. These are
#               refused with a reason, never re-mapped to something the
#               model can do ("Saree -> dress", "Sherwani -> shirt").
#
# Adding support later is a one-line change here, made once the
# provider has actually been checked against real photos.
# ============================================================

TOP, BOTTOM, OUTERWEAR, ONE_PIECE = "top", "bottom", "outerwear", "one_piece"

# slot -> the provider's category string
MODEL_CATEGORY_FOR_SLOT = {
    TOP: "tops",
    # A jacket is worn on the upper body, so the model treats it as a
    # top. Layering it OVER a shirt is a second pass.
    OUTERWEAR: "tops",
    BOTTOM: "bottoms",
    ONE_PIECE: "one-pieces",
}

_SUPPORTED_SLOTS = {
    # tops
    "T-Shirt": TOP, "Shirt": TOP, "Casual Shirt": TOP, "Formal Shirt": TOP,
    "Polo Shirt": TOP, "Tank Top": TOP, "Top": TOP, "Crop Top": TOP,
    "Camisole": TOP, "Tunic": TOP, "Sports T-Shirt": TOP, "Sports Jersey": TOP,
    "Blouse": TOP, "Kurta (Men)": TOP, "Kurta (Women)": TOP,
    # bottoms
    "Jeans": BOTTOM, "Trousers": BOTTOM, "Formal Trousers": BOTTOM,
    "Chinos": BOTTOM, "Cargo Pants": BOTTOM, "Wide-Leg Pants": BOTTOM,
    "Shorts": BOTTOM, "Skirt": BOTTOM, "Track Pants": BOTTOM, "Joggers": BOTTOM,
    "Athletic Shorts": BOTTOM, "Leggings": BOTTOM, "Pajama": BOTTOM,
    "Salwar": BOTTOM, "Palazzos": BOTTOM,
    # one-pieces
    "Dress": ONE_PIECE, "Gown": ONE_PIECE, "Jumpsuit": ONE_PIECE,
    "Romper": ONE_PIECE,
    # outerwear
    "Jacket": OUTERWEAR, "Blazer": OUTERWEAR, "Coat": OUTERWEAR,
    "Bomber Jacket": OUTERWEAR, "Denim Jacket": OUTERWEAR,
    "Leather Jacket": OUTERWEAR, "Hoodie": OUTERWEAR, "Cardigan": OUTERWEAR,
    "Shrug": OUTERWEAR, "Track Jacket": OUTERWEAR, "Nehru Jacket": OUTERWEAR,
}

_DRAPED = (
    "is a draped garment. The try-on model is built for tops, bottoms and "
    "dresses and can't drape fabric realistically, so it isn't offered "
    "rather than showing a misleading result."
)
_SET = (
    "is a multi-piece traditional outfit. The try-on model puts on one "
    "top, bottom or dress at a time and hasn't been verified on this kind "
    "of outfit, so it isn't offered rather than showing a misleading result."
)

_UNSUPPORTED_REASONS = {
    "Saree": "A saree " + _DRAPED,
    "Casual Saree": "A saree " + _DRAPED,
    "Wedding Saree": "A saree " + _DRAPED,
    "Dhoti Pants": "A dhoti " + _DRAPED,
    "Dupatta": "A dupatta " + _DRAPED,
    "Lehenga": "A lehenga " + _SET,
    "Sherwani": (
        "A sherwani is a long, structured traditional coat. The try-on model "
        "hasn't been verified on it and would likely render it as a short "
        "jacket, so it isn't offered."
    ),
    "Anarkali": "An anarkali " + _SET,
    "Sharara": "A sharara " + _SET,
    "Salwar Suit": "A salwar suit " + _SET,
    "Kurta Set (Men)": "A kurta set " + _SET + " Try the kurta on its own instead.",
    "Kurta Set (Women)": "A kurta set " + _SET + " Try the kurta on its own instead.",
}

_FOOTWEAR_REASON = (
    "Shoes can't be rendered onto a person by the try-on model, so they're "
    "shown next to the result instead."
)
_ACCESSORY_REASON = (
    "Bags, jewellery and other accessories can't be rendered onto a person "
    "by the try-on model, so they're shown next to the result instead."
)

# A ceiling on passes per request. Each pass is one generation of a
# limited GPU allowance.
MAX_PASSES = 3


def garment_support(category):
    """
    Whether this wardrobe category can be tried on.

    Returns {"supported": bool, "slot": str|None,
             "model_category": str|None, "reason": str}.
    `reason` is empty for supported garments and a user-readable
    sentence otherwise.
    """
    value = category_catalog.canonical(category)

    if value and value in _SUPPORTED_SLOTS:
        slot = _SUPPORTED_SLOTS[value]
        return {
            "supported": True,
            "slot": slot,
            "model_category": MODEL_CATEGORY_FOR_SLOT[slot],
            "reason": "",
        }

    if value and value in _UNSUPPORTED_REASONS:
        reason = _UNSUPPORTED_REASONS[value]
    else:
        section = category_catalog.CATALOG.get(value, {}).get("section") if value else None
        key = (category or "").strip().lower()
        if section == "Footwear" or key in ("footwear", "shoes"):
            reason = _FOOTWEAR_REASON
        elif section == "Accessories" or key in (
            "hand cuff", "neck chain", "finger ring", "jewelry", "jewellery",
        ):
            reason = _ACCESSORY_REASON
        else:
            reason = (
                f"'{category or 'This item'}' isn't a garment type the "
                "try-on model supports."
            )

    return {"supported": False, "slot": None, "model_category": None, "reason": reason}


def garment_support_for(category, engine=None):
    """
    garment_support(), narrowed to what `engine` (the provider that would
    actually run the try-on) accepts. A garment is never labelled
    supported just because some OTHER provider could wear it.
    """
    support = garment_support(category)
    if (support["supported"] and engine is not None
            and support["model_category"] not in engine.supported_model_categories):
        return {"supported": False, "slot": None, "model_category": None,
                "reason": "The try-on service available right now can't put this kind of "
                          "garment on a photo."}
    return support


def is_accessory_like(category):
    """Footwear/accessories: shown beside a result instead of blocking it."""
    reason = garment_support(category)["reason"]
    return reason in (_FOOTWEAR_REASON, _ACCESSORY_REASON)


# ============================================================
# PROVIDER STATES
#
# Every provider failure is classified into ONE of these, so the
# orchestrator (tryon_orchestrator.py) can decide whether trying another
# provider makes sense - a quota or an outage is the provider's problem,
# a bad photo or an unsupported garment is not and would fail anywhere.
# ============================================================

AVAILABLE = "AVAILABLE"
CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
RATE_LIMITED = "RATE_LIMITED"
QUEUE_FULL = "QUEUE_FULL"
PROVIDER_SLEEPING = "PROVIDER_SLEEPING"
TEMPORARILY_UNAVAILABLE = "TEMPORARILY_UNAVAILABLE"
AUTH_ERROR = "AUTH_ERROR"
UNSUPPORTED_INPUT = "UNSUPPORTED_INPUT"
TIMEOUT = "TIMEOUT"
UNKNOWN_ERROR = "UNKNOWN_ERROR"

PROVIDER_STATES = (
    AVAILABLE, CONFIGURATION_ERROR, QUOTA_EXHAUSTED, RATE_LIMITED, QUEUE_FULL,
    PROVIDER_SLEEPING, TEMPORARILY_UNAVAILABLE, AUTH_ERROR, UNSUPPORTED_INPUT,
    TIMEOUT, UNKNOWN_ERROR,
)


class TryOnUnavailable(RuntimeError):
    """
    Try-on cannot run. `detail` is for the server log; str() is for
    the user and never names a token, a URL or a provider secret.
    `state` is one of PROVIDER_STATES; `retry_after` (seconds) is set
    when the provider said how long to wait.
    """

    def __init__(self, message, detail="", state=UNKNOWN_ERROR, retry_after=None):
        super().__init__(message)
        self.detail = detail or message
        self.state = state
        self.retry_after = retry_after


class PhotoUnsuitable(ValueError):
    """The user's photo cannot be used. str() explains what to change."""


# ============================================================
# THE USER'S PHOTO
# ============================================================

# Below this, the model has too little to work with and the result
# looks like an upscaled thumbnail.
MIN_WIDTH = 384
MIN_HEIGHT = 512

# A very wide photo is almost always a group shot or a landscape, not
# a single person standing up.
MAX_ASPECT_RATIO = 1.2

# What the upload accepts. MPO is how some phone cameras label a JPEG.
ACCEPTED_FORMATS = {"JPEG", "PNG", "WEBP", "MPO"}


def check_person_photo(image_bytes):
    """
    Returns a list of plain-language problems with the photo, empty if
    it looks usable.

    HONEST ABOUT ITS OWN LIMITS. This checks what can be checked from
    the pixels without a second model: that the file is a real image,
    that it is big enough, and that it is portrait-shaped rather than
    a landscape group photo. It does NOT verify that there is exactly
    one person, that they are facing the camera, or that their whole
    body is visible - claiming to detect that without a detector would
    be a lie, and the guidance text in the interface covers it
    instead. The model's own pose detection handles the rest, and a
    bad photo shows up as a bad result rather than a crash.
    """
    problems = []

    if not image_bytes:
        return ["That file is empty. Choose a JPEG or PNG photo."]

    megabytes = len(image_bytes) / (1024 * 1024)

    # Checked before decoding, so an oversized upload is never
    # decompressed into memory at all.
    if megabytes > config.TRYON_MAX_UPLOAD_MB:
        return [
            f"The photo is {megabytes:.1f} MB, which is larger than the "
            f"{config.TRYON_MAX_UPLOAD_MB} MB limit. Most phones can share a "
            "smaller copy, or you can take a screenshot of it."
        ]

    try:
        from PIL import Image
    except ImportError:
        return problems

    try:
        image = Image.open(io.BytesIO(image_bytes))
        image.verify()
        image = Image.open(io.BytesIO(image_bytes))
        width, height = image.size
        image_format = (image.format or "").upper()
    except Exception:
        return ["That file isn't an image we can read. Use a JPEG, PNG or WebP photo."]

    if image_format not in ACCEPTED_FORMATS:
        return [
            f"{image_format or 'That'} images aren't supported. Use a JPEG, "
            "PNG or WebP photo."
        ]

    if width < MIN_WIDTH or height < MIN_HEIGHT:
        problems.append(
            f"The photo is {width}x{height}, which is too small for a clear "
            f"result. Use one at least {MIN_WIDTH}x{MIN_HEIGHT}."
        )

    if height and (width / height) > MAX_ASPECT_RATIO:
        problems.append(
            "The photo is much wider than it is tall. Use an upright "
            "photo of yourself standing, not a landscape or group photo."
        )

    return problems


def person_photo_advice(image_bytes):
    """
    Things worth telling the user about their photo that are NOT
    reasons to refuse it.

    The distinction matters. check_person_photo above REJECTS - the
    file is not an image, it is too big, it is a landscape group shot.
    This one only advises: the photo is dim, or soft. Plenty of
    perfectly good indoor phone photos are a bit of both, and refusing
    them would be exactly the kind of "photograph it against a white
    wall" demand this app is supposed to avoid. But the model will
    spend a minute of a shared free GPU reproducing whatever it is
    given, so saying so beforehand is worth a line of text.

    Returns a list of sentences, empty when there is nothing to say.
    """
    if not image_bytes:
        return []

    try:
        from PIL import Image
        image = Image.open(io.BytesIO(image_bytes))
    except Exception:  # noqa: BLE001 - advice may never be the thing that breaks
        return []

    return _exposure_and_focus_problems(image)


# The same thresholds the clothing upload uses (image_pipeline), so a
# photo judged too dark or too soft in one place is judged the same way
# in the other.
MIN_MEAN_BRIGHTNESS = 30
MIN_SHARPNESS = 12


def _exposure_and_focus_problems(image):
    """
    Two cheap numbers: mean brightness, and Laplacian variance for
    focus. Same thresholds as the clothing upload, so the two parts of
    the app agree about what "dark" and "blurry" mean.

    Deliberately NOT a quality score for the result, and never a reason
    to refuse a photo - see person_photo_advice.
    """
    problems = []

    try:
        import numpy as np
    except ImportError:
        return problems

    try:
        gray = np.asarray(image.convert("L"), dtype=np.float32)
    except Exception:  # noqa: BLE001 - a validation check may never crash
        return problems

    if gray.size == 0:
        return problems

    if float(gray.mean()) < MIN_MEAN_BRIGHTNESS:
        problems.append(
            "The photo is very dark. Stand facing a window or turn a light "
            "on - the try-on can only be as clear as the photo."
        )

    try:
        import cv2
        side = min(512, gray.shape[1]), min(512, gray.shape[0])
        small = cv2.resize(gray, side)
        sharpness = float(cv2.Laplacian(small, cv2.CV_32F).var())
    except Exception:  # noqa: BLE001 - opencv missing or an odd image
        return problems

    if sharpness < MIN_SHARPNESS:
        problems.append(
            "The photo looks out of focus. A sharper photo gives a much "
            "better result - hold still, or ask someone to take it."
        )

    return problems


# ============================================================
# TURNING A SELECTION INTO PASSES
# ============================================================

def category_for_item(item):
    """The provider category for this item, or None if it can't be worn."""
    return garment_support(item.get("category", ""))["model_category"]


def plan_outfit(items, max_passes=None):
    """
    Works out how to wear a set of wardrobe items.

    Returns (passes, not_applied, problems):

      passes       ordered [(item, model_category)] - each one
                   generation, every pass applied to the previous
                   pass's output.
      not_applied  shoes and accessories: shown beside the result,
                   never silently dropped and never "worn".
      problems     reasons the selection cannot be tried on as given -
                   including any garment the model does not support.
                   An unsupported garment is refused, not re-mapped.

    Order matters: the bottom goes on before the top, so a shirt's hem
    lands over the waistband the way it would in life, and a jacket
    goes on last so it sits over the shirt.

    `max_passes` is the provider's limit. A provider that can only put
    on one garment is never handed a multi-garment outfit.
    """
    limit = MAX_PASSES if max_passes is None else max_passes

    slots = {TOP: [], BOTTOM: [], OUTERWEAR: [], ONE_PIECE: []}
    not_applied = []
    problems = []

    for item in items:
        category = item.get("category", "")
        support = garment_support(category)

        if support["supported"]:
            slots[support["slot"]].append(item)
            continue

        if is_accessory_like(category):
            not_applied.append({"item": item, "reason": support["reason"]})
            continue

        problems.append(support["reason"])

    if problems:
        return [], not_applied, problems

    one_pieces = slots[ONE_PIECE]

    if one_pieces and (slots[TOP] or slots[BOTTOM]):
        problems.append(
            f"A {one_pieces[0].get('category', 'dress').lower()} is worn on "
            "its own - remove the separate top or bottom, or remove the "
            f"{one_pieces[0].get('category', 'dress').lower()}."
        )
    for slot, noun in ((ONE_PIECE, "dress, gown or jumpsuit"), (TOP, "top"),
                       (BOTTOM, "bottom"), (OUTERWEAR, "jacket or layer")):
        if len(slots[slot]) > 1:
            problems.append(f"Only one {noun} can be tried on at a time.")

    if problems:
        return [], not_applied, problems

    passes = []

    if one_pieces:
        passes.append((one_pieces[0], MODEL_CATEGORY_FOR_SLOT[ONE_PIECE]))
    else:
        for slot in (BOTTOM, TOP):
            for item in slots[slot]:
                passes.append((item, MODEL_CATEGORY_FOR_SLOT[slot]))

    for item in slots[OUTERWEAR]:
        passes.append((item, MODEL_CATEGORY_FOR_SLOT[OUTERWEAR]))

    if not passes:
        problems.append("Pick at least one top, bottom, dress or jacket to try on.")
        return [], not_applied, problems

    if len(passes) > limit:
        if limit == 1:
            problems.append(
                "The try-on service can put on one garment at a time. "
                "Choose a single item."
            )
        else:
            problems.append(
                f"That's more layers than one try-on can handle (limit {limit})."
            )
        return [], not_applied, problems

    return passes, not_applied, problems


def item_image(item):
    """
    Where a wardrobe item's photo lives.

    The wardrobe collection has always called this field "image_path"
    - it predates Cloudinary, when it really was a path. It now holds
    an https URL for migrated items and a "/api/uploads/..." path for
    ones still only on one machine. The alternative spellings are
    accepted because recommendation payloads and test fixtures have
    used them.
    """
    return (
        item.get("image_path")
        or item.get("image_url")
        or item.get("image")
        or ""
    )


def garment_image_bytes(item):
    """
    The item's REAL photo, wherever storage.py put it.

    Deliberately the user's own image rather than a generated
    lookalike - the point of trying on your own wardrobe is that it is
    your own wardrobe. Cloudinary URLs are downloaded through
    storage.local_copy_of, which caches, so trying the same shirt on
    twice does not download it twice.
    """
    url = item_image(item)

    if not url:
        raise TryOnUnavailable(
            f"'{item.get('category', 'That item')}' has no photo stored, so "
            "it can't be tried on.",
            state=UNSUPPORTED_INPUT,
        )

    if storage.is_remote_url(url):
        path = storage.local_copy_of(url)

        if not path:
            raise TryOnUnavailable(
                "One of the clothing photos could not be loaded. Try again "
                "in a moment.",
                detail=f"local_copy_of returned nothing for {url[:60]}",
                state=UNSUPPORTED_INPUT,
            )
    else:
        # A legacy "/api/uploads/<folder>/<file>" path from before
        # Cloudinary. Still valid on the machine that holds the file.
        relative = url.replace("/api/uploads/", "", 1)
        path = os.path.join(storage.BASE_UPLOAD_FOLDER, relative)

        if not os.path.isfile(path):
            raise TryOnUnavailable(
                f"'{item.get('category', 'That item')}' has a photo that only "
                "exists on the computer it was uploaded from, so it can't be "
                "tried on from here.",
                detail=f"local path missing for {url[:60]}",
                state=UNSUPPORTED_INPUT,
            )

    with open(path, "rb") as handle:
        return handle.read()


# ============================================================
# PROVIDERS
#
# VirtualTryOnProvider is the whole contract between this module and
# whatever actually runs the model. It is shaped for an asynchronous
# service - submit, check status, fetch the result - because every
# realistic try-on backend is one: a hosted diffusion model takes tens
# of seconds and runs in a queue. A provider whose client happens to be
# blocking can still implement it; _run_pass() is the only caller and
# enforces the timeout either way.
#
# A provider says what it can do (which garment categories, whether it
# can layer several garments by chaining passes) and what configuration
# it is missing, so the interface never offers something the provider
# cannot deliver and never pretends to be set up when it is not.
# ============================================================

RUNNING, DONE, FAILED = "running", "done", "failed"


class VirtualTryOnProvider:
    """Base class and the 'nothing configured' provider."""

    name = "none"

    # Provider category strings this provider accepts.
    supported_model_categories = ()

    # Whether a full outfit may be built by feeding one pass's output
    # into the next. False means one garment per try-on, full stop.
    supports_layering = False

    def missing_configuration(self):
        """
        Names of the settings still needed, e.g. ["TRYON_SPACE_ID"].
        Setting NAMES only - never a value.
        """
        return ["TRYON_PROVIDER"]

    def available(self):
        return not self.missing_configuration()

    def max_passes(self):
        return MAX_PASSES if self.supports_layering else 1

    def submit(self, person_bytes, garment_bytes, model_category):
        """Starts one generation and returns an opaque handle."""
        raise TryOnUnavailable(
            "Virtual Try-On is not configured yet.",
            detail="no provider configured",
            state=CONFIGURATION_ERROR,
        )

    def status(self, handle):
        """RUNNING, DONE or FAILED."""
        return FAILED

    def result(self, handle):
        """
        The finished image as bytes. Raises TryOnUnavailable (with a
        user-safe message) if the generation failed.
        """
        raise TryOnUnavailable("Virtual Try-On is not configured yet.",
                               state=CONFIGURATION_ERROR)

    def cancel(self, handle):
        """Best effort: stop a generation that is no longer wanted."""


# Kept for anything still importing the old name.
Provider = VirtualTryOnProvider


# The endpoint every supported host exposes: the official FASHN Space,
# the self-hosted Space in spaces/tryon/ and its Colab variant.
TRYON_API_NAME = "/try_on"


def _endpoint_parameters(client):
    """
    Parameter names the host's /try_on endpoint declares, read from the
    host's own API description rather than assumed. Empty set if the
    description can't be read - then only the three universal
    arguments are sent.
    """
    try:
        info = client.view_api(print_info=False, return_format="dict") or {}
        endpoint = (info.get("named_endpoints") or {}).get(TRYON_API_NAME) or {}
        return {
            parameter.get("parameter_name")
            for parameter in endpoint.get("parameters", [])
            if isinstance(parameter, dict)
        }
    except Exception:  # noqa: BLE001 - optional refinement only
        return set()


def _gradio_client_installed():
    try:
        import importlib.util
        return importlib.util.find_spec("gradio_client") is not None
    except (ImportError, ValueError):
        return False


class HuggingFaceSpaceProvider(VirtualTryOnProvider):
    """
    FASHN VTON v1.5 running in a Gradio app this project deploys
    itself - a Hugging Face ZeroGPU Space, or the same app on a Colab
    GPU exposed as an https share link. Both live in spaces/tryon/, so
    the call signature is fixed rather than guessed: endpoint
    "/try_on", inputs person_image, garment_image, category (one of
    tops / bottoms / one-pieces), one image out.

    The access token is read from the server's own environment and
    never leaves it.
    """

    name = "huggingface_space"

    # For documentation and logs only - never shown to users.
    free_tier_note = (
        "Hugging Face ZeroGPU: free, no payment. Quota is per calling "
        "account across all ZeroGPU Spaces (about 2 GPU-minutes a day "
        "anonymous, 5 with a free account), resetting 24 h after first use."
    )

    supported_model_categories = ("tops", "bottoms", "one-pieces")

    def __init__(self, host=None, token=None):
        # None = read the server settings at call time (so a settings
        # change or a test patch is always honoured).
        self._host = host
        self._token = token

    @property
    def host(self):
        return self._host if self._host is not None else (config.TRYON_SPACE_ID or "")

    @property
    def token(self):
        return self._token if self._token is not None else (config.HUGGINGFACE_API_TOKEN or "")

    def host_is_url(self):
        return self.host.startswith("https://")

    # Name of the setting that holds this provider's host.
    host_setting = "TRYON_SPACE_ID"

    # FASHN puts on ONE garment per call. A full outfit is several
    # calls, each on the previous output - the approach FASHN
    # documents for multi-garment looks. It is never several garments
    # in one call.
    supports_layering = True

    def missing_configuration(self):
        missing = []

        if not _gradio_client_installed():
            missing.append("gradio_client (Python package: pip install gradio_client)")

        if not self.host:
            missing.append(self.host_setting)

        # HUGGINGFACE_API_TOKEN is deliberately NOT required. A public
        # ZeroGPU Space can be called anonymously; the token only moves
        # the GPU allowance from the small anonymous pool to the free
        # account that owns the token (see config.py).

        return missing

    def _client(self):
        try:
            from gradio_client import Client
        except ImportError:
            raise TryOnUnavailable(
                "Virtual Try-On is not configured yet.",
                detail="gradio_client is not installed - pip install gradio_client",
                state=CONFIGURATION_ERROR,
            )

        # A Space id needs the token so the GPU allowance is charged
        # to our account. A share link takes no token, and passing an
        # empty one makes gradio_client raise rather than connect.
        arguments = {"verbose": False}

        # gradio_client 1.x/2.x calls this argument "token" (0.x used
        # "hf_token", which 2.x rejects outright).
        if self.token and not self.host_is_url():
            arguments["token"] = self.token

        try:
            return Client(self.host, **arguments)
        except Exception as error:
            raise _unavailable(
                error, f"{type(error).__name__} connecting to the try-on host",
                default_state=TEMPORARILY_UNAVAILABLE,
                default=(
                    "The try-on service can't be reached right now. Please "
                    "try again in a few minutes."
                ),
            )

    def submit(self, person_bytes, garment_bytes, model_category):

        if model_category not in self.supported_model_categories:
            # A programming error upstream - never send the model a
            # category it does not understand.
            raise TryOnUnavailable(
                "That garment type can't be tried on.",
                detail=f"unsupported model category {model_category!r}",
                state=UNSUPPORTED_INPUT,
            )

        if not self.available():
            raise TryOnUnavailable(
                "Virtual Try-On is not configured yet.",
                detail="missing: " + ", ".join(self.missing_configuration()),
                state=CONFIGURATION_ERROR,
            )

        from gradio_client import handle_file

        client = self._client()

        person_path = _temp_image(person_bytes, "person")
        garment_path = _temp_image(garment_bytes, "garment")

        arguments = {
            "person_image": handle_file(person_path),
            "garment_image": handle_file(garment_path),
            "category": model_category,
        }

        # The official public Space (fashn-ai/fashn-vton-1.5) also takes
        # garment_photo_type ("model" = worn by a person, "flat-lay" =
        # the garment on its own) and defaults it to "model". Wardrobe
        # photos are background-removed garment shots, so the right
        # value is "flat-lay". The self-hosted app in spaces/tryon/ does
        # not take the argument, so it is only sent to an endpoint that
        # declares it - both hosts keep working.
        if "garment_photo_type" in _endpoint_parameters(client):
            arguments["garment_photo_type"] = config.TRYON_GARMENT_PHOTO_TYPE

        try:
            job = client.submit(api_name=TRYON_API_NAME, **arguments)
        except Exception as error:
            _remove_quietly(person_path, garment_path)
            raise _unavailable(error, f"{type(error).__name__} submitting to the try-on host")

        return {"job": job, "files": (person_path, garment_path)}

    def status(self, handle):
        job = handle["job"]

        if not job.done():
            # Remember WHERE the job is waiting (queue vs GPU) so a
            # timeout can say which - never shown raw to the user.
            try:
                code = job.status().code
                handle["phase"] = getattr(code, "value", str(code))
            except Exception:  # noqa: BLE001
                pass
            return RUNNING

        try:
            return FAILED if job.exception(timeout=0) else DONE
        except Exception:  # noqa: BLE001 - cancelled or broken future
            return FAILED

    def result(self, handle):
        job = handle["job"]

        try:
            error = job.exception(timeout=0)
            if error:
                raise _unavailable(error, f"{type(error).__name__} from the try-on host")

            output = job.result(timeout=0)
        except TryOnUnavailable:
            raise
        except Exception as error:  # noqa: BLE001
            raise _unavailable(error, f"{type(error).__name__} reading the try-on result")
        finally:
            _remove_quietly(*handle.get("files", ()))

        path = output[0] if isinstance(output, (list, tuple)) else output

        if isinstance(path, dict):
            path = path.get("path") or path.get("name")

        if not path or not os.path.isfile(str(path)):
            raise TryOnUnavailable(
                "The try-on finished but produced no image. Please try again.",
                detail=f"unusable result: {type(output).__name__}",
                state=UNKNOWN_ERROR,
            )

        with open(path, "rb") as image_file:
            data = image_file.read()

        if not data:
            raise TryOnUnavailable(
                "The try-on finished but produced no image. Please try again.",
                detail="empty result file",
                state=UNKNOWN_ERROR,
            )

        return data

    def phase(self, handle):
        """Last gradio status seen: IN_QUEUE, PROCESSING, ... (or "")."""
        return handle.get("phase", "") if isinstance(handle, dict) else ""

    def cancel(self, handle):
        try:
            handle["job"].cancel()
        except Exception:  # noqa: BLE001
            pass
        _remove_quietly(*handle.get("files", ()))


_MESSAGES = {
    QUOTA_EXHAUSTED: (
        "Today's free try-on allowance has run out. It resets within "
        "24 hours - everything else in the app still works."
    ),
    QUEUE_FULL: (
        "The free try-on GPUs are all busy right now. Please try again "
        "in a few minutes."
    ),
    RATE_LIMITED: (
        "The try-on service is receiving too many requests. Please wait "
        "a minute and try again."
    ),
    PROVIDER_SLEEPING: (
        "The try-on service is starting up. Please try again in a minute "
        "or two."
    ),
    TIMEOUT: (
        "The try-on took too long and was stopped. The service may be "
        "waking up - try again in a minute."
    ),
    AUTH_ERROR: (
        "The try-on service rejected this server's credentials, so "
        "Virtual Try-On isn't available right now. Everything else in "
        "the app still works."
    ),
    UNSUPPORTED_INPUT: (
        "The try-on service couldn't use that photo. Try a clear, "
        "upright photo of one person facing the camera."
    ),
    CONFIGURATION_ERROR: (
        "The try-on service has changed or can't be found, so Virtual "
        "Try-On isn't available right now. Everything else in the app "
        "still works."
    ),
    TEMPORARILY_UNAVAILABLE: (
        "The try-on service can't be reached right now. Please try again "
        "in a few minutes."
    ),
}

_RETRY_IN = __import__("re").compile(
    r"(?:retry|try again)\s+in\s+(?:(\d+):)?(\d{1,2}):(\d{2})", __import__("re").I
)


def _retry_after_seconds(text):
    """'retry in 3:12:00' / 'try again in 12:30' -> seconds, else None."""
    match = _RETRY_IN.search(text)
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    if hours is None:  # "12:30" = minutes:seconds
        return int(minutes) * 60 + int(seconds)
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds)


def classify_failure(error):
    """
    (state, user_message, retry_after_seconds) from the failure's SHAPE,
    never its raw text - which can contain the host address and, on some
    errors, the token sent with the request.

    Covers what free hosts actually do: a daily ZeroGPU allowance per
    caller, a shared queue with a size limit, a host that sleeps when
    idle, rate limiting, and a Colab/Kaggle share link that stops
    existing when its notebook stops.
    """
    text = str(error).lower()
    retry = _retry_after_seconds(text)

    # Daily ZeroGPU allowance used up ("You have exceeded your GPU
    # quota", "ZeroGPU quota exceeded ... retry in 3:12:00").
    if "quota" in text or ("exceeded" in text and "gpu" in text):
        return QUOTA_EXHAUSTED, _MESSAGES[QUOTA_EXHAUSTED], retry

    # Shared GPUs all in use right now - different from quota.
    if ("no gpu" in text or "gpu is not available" in text or "gpu task aborted" in text
            or "queue is full" in text or "queue full" in text):
        return QUEUE_FULL, _MESSAGES[QUEUE_FULL], retry

    if "429" in text or "too many requests" in text or "rate limit" in text:
        return RATE_LIMITED, _MESSAGES[RATE_LIMITED], retry

    if ("sleeping" in text or "paused" in text or "building" in text
            or "starting" in text or "503" in text):
        return PROVIDER_SLEEPING, _MESSAGES[PROVIDER_SLEEPING], retry

    if "timeout" in text or "timed out" in text:
        return TIMEOUT, _MESSAGES[TIMEOUT], retry

    if ("401" in text or "403" in text or "unauthorized" in text or "invalid token" in text
            or "invalid user token" in text or "forbidden" in text):
        return AUTH_ERROR, _MESSAGES[AUTH_ERROR], None

    if "nsfw" in text or "safety" in text or "no person" in text or "pose" in text:
        return UNSUPPORTED_INPUT, _MESSAGES[UNSUPPORTED_INPUT], None

    if "queue" in text or "busy" in text:
        return QUEUE_FULL, "The try-on service is busy. Please try again shortly.", retry

    if ("404" in text or "not found" in text or "does not exist" in text
            or "cannot find a function" in text or "api_name" in text):
        return CONFIGURATION_ERROR, _MESSAGES[CONFIGURATION_ERROR], None

    if ("502" in text or "connection" in text or "unreachable" in text
            or "name or service not known" in text or "failed to establish" in text
            or "remote end closed" in text or "tunnel" in text):
        return TEMPORARILY_UNAVAILABLE, _MESSAGES[TEMPORARILY_UNAVAILABLE], retry

    return UNKNOWN_ERROR, None, None


def _describe_provider_failure(error, default="The try-on couldn't be completed. Please try again."):
    """The user-facing sentence for a provider failure (see classify_failure)."""
    _, message, _ = classify_failure(error)
    return message or default


def _unavailable(error, detail, default_state=UNKNOWN_ERROR,
                 default="The try-on couldn't be completed. Please try again."):
    """A TryOnUnavailable with the right state for a raw provider error."""
    state, message, retry = classify_failure(error)
    if state == UNKNOWN_ERROR:
        state = default_state
        message = _MESSAGES.get(default_state) if default_state != UNKNOWN_ERROR else None
    return TryOnUnavailable(message or default, detail=detail, state=state, retry_after=retry)


def _temp_image(image_bytes, prefix):
    handle = tempfile.NamedTemporaryFile(
        prefix=f"tryon_{prefix}_", suffix=".png", delete=False
    )
    try:
        handle.write(image_bytes)
    finally:
        handle.close()
    return handle.name




def _remove_quietly(*paths):
    for path in paths:
        try:
            os.unlink(path)
        except OSError:
            pass


class SelfHostedGradioProvider(HuggingFaceSpaceProvider):
    """
    The SAME model (FASHN VTON v1.5) and the same /try_on contract,
    running on a free GPU you start yourself: the notebook in
    spaces/tryon/colab_tryon.ipynb on Google Colab's free tier (or the
    same code on Kaggle), which prints an https share link.

    Why this is a legitimate fallback and not a quota workaround: it is
    separate compute that YOU run in your own free notebook, not another
    Hugging Face account or anonymous calls to the same ZeroGPU pool
    (Hugging Face counts ZeroGPU quota per calling account across ALL
    ZeroGPU Spaces, so switching Spaces would not help and switching
    accounts would break the rules).

    Limits: Colab's free GPU is not guaranteed, a runtime lasts at most
    about 12 hours and stops when idle, and the share link changes every
    time the notebook starts. No token, no payment.
    """

    name = "self_hosted"
    host_setting = "TRYON_FALLBACK_URL"
    free_tier_note = (
        "Your own free Colab/Kaggle notebook: free GPU when available, "
        "session-limited, link changes each run."
    )

    @property
    def host(self):
        return self._host if self._host is not None else (config.TRYON_FALLBACK_URL or "")

    @property
    def token(self):
        return ""  # a share link never takes a Hugging Face token

    def missing_configuration(self):
        missing = super().missing_configuration()
        if self.host and not self.host_is_url():
            missing.append("TRYON_FALLBACK_URL (must be the https:// link the notebook prints)")
        return missing


class SecondSelfHostedGradioProvider(SelfHostedGradioProvider):
    """
    A second notebook, so Kaggle and Colab can both be running.

    Two notebooks are two separate free GPUs with two separate
    allowances, which is the only honest way to raise how many try-ons
    can actually succeed in a day without paying: Kaggle gives about 30
    GPU-hours a week, Colab an unpredictable few hours a day, and either
    one falling asleep stops being a total outage when the other is up.

    Identical in every other way - same model, same /try_on contract,
    same quality. It differs from self_hosted only in which setting
    holds its address.
    """

    name = "self_hosted_2"
    host_setting = "TRYON_FALLBACK_URL_2"
    free_tier_note = (
        "Your second free notebook (Kaggle or Colab): free GPU when "
        "available, session-limited, link changes each run."
    )

    @property
    def host(self):
        return self._host if self._host is not None else (config.TRYON_FALLBACK_URL_2 or "")

    def missing_configuration(self):
        # HuggingFaceSpaceProvider's version already reports
        # self.host_setting when the address is blank, and host_setting
        # above is the right name, so only the "must be a link" check
        # needs restating with this setting's own name.
        missing = HuggingFaceSpaceProvider.missing_configuration(self)
        if self.host and not self.host_is_url():
            missing.append(
                "TRYON_FALLBACK_URL_2 (must be the https:// link the notebook prints)"
            )
        return missing


class FashnSpaceProvider(HuggingFaceSpaceProvider):
    """The official/public FASHN VTON v1.5 Space (or your own copy of it)."""

    name = "fashn_space"


_PROVIDERS = {
    "fashn_space": FashnSpaceProvider,
    "huggingface_space": HuggingFaceSpaceProvider,   # older name, same provider
    "self_hosted": SelfHostedGradioProvider,
    "self_hosted_2": SecondSelfHostedGradioProvider,
    "none": VirtualTryOnProvider,
}


def provider():
    """
    The provider a new try-on would use right now: the first configured
    provider that is not cooling down after a quota/outage (see
    tryon_orchestrator). Falls back to the first configured provider -
    or the 'nothing configured' one - so callers always get an object.
    """
    from backend import tryon_orchestrator
    return tryon_orchestrator.active() or tryon_orchestrator.primary()


def available():
    """Whether a try-on could actually be generated right now."""
    from backend import tryon_orchestrator
    return tryon_orchestrator.active() is not None


def missing_configuration():
    """What still has to be set before try-on works (names, never values)."""
    from backend import tryon_orchestrator
    return tryon_orchestrator.missing_configuration()


# ============================================================
# GENERATION
# ============================================================

POLL_SECONDS = 2.0


def _now():
    """Monotonic clock for pass timeouts (a function so tests can replace it)."""
    return time.monotonic()


def _run_pass(engine, person_bytes, garment_bytes, model_category,
              timeout=None, sleep=None, clock=None):
    """
    One garment onto one person, with the provider contract enforced
    here rather than trusted: a timeout, and no raw exception - which
    could carry a token or an internal URL - ever escaping as anything
    but TryOnUnavailable with a sentence written for the user.
    """
    limit = timeout or config.TRYON_TIMEOUT_SECONDS
    clock = clock or _now
    sleep = sleep or time.sleep

    try:
        handle = engine.submit(person_bytes, garment_bytes, model_category)
    except TryOnUnavailable:
        raise
    except Exception as error:  # noqa: BLE001
        logger.warning("Provider %s submit raised %s", engine.name, type(error).__name__)
        raise _unavailable(error, f"unwrapped {type(error).__name__} from {engine.name}.submit")

    deadline = clock() + limit

    while True:
        try:
            state = engine.status(handle)
        except Exception as error:  # noqa: BLE001
            engine.cancel(handle)
            raise _unavailable(error, f"unwrapped {type(error).__name__} from {engine.name}.status")

        if state in (DONE, FAILED):
            break

        if clock() >= deadline:
            phase = ""
            if hasattr(engine, "phase"):
                try:
                    phase = engine.phase(handle) or ""
                except Exception:  # noqa: BLE001
                    phase = ""
            engine.cancel(handle)
            print(f"Try-on pass on {engine.name} stopped after {limit}s "
                  f"(last phase: {phase or 'unknown'}).")
            if phase in ("STARTING", "JOINING_QUEUE", "IN_QUEUE", "QUEUE_FULL"):
                # Never got a GPU - the free queue was busy, not the model slow.
                raise TryOnUnavailable(
                    "The free try-on GPUs were all busy, so the request "
                    "waited in the queue and was stopped. Please try again "
                    "in a few minutes.",
                    detail=f"still queued after {limit}s",
                    state=QUEUE_FULL,
                )
            raise TryOnUnavailable(
                "The try-on took too long and was stopped. The service may be "
                "starting up - please try again in a minute.",
                detail=f"timed out after {limit}s",
                state=TIMEOUT,
            )

        sleep(POLL_SECONDS)

    try:
        return engine.result(handle)
    except TryOnUnavailable:
        raise
    except Exception as error:  # noqa: BLE001
        raise _unavailable(error, f"unwrapped {type(error).__name__} from {engine.name}.result")


def generate_outfit(person_bytes, items, on_progress=None, engine=None):
    """
    Wears `items` on the person in `person_bytes`.

    Returns (image_bytes, report). With several garments each pass
    feeds the next, so the final image has every garment on at once.

    `on_progress(step, total, message)` is called before each pass.

    Normally the provider is chosen - and, if it runs out of quota or
    goes down mid-outfit, replaced - by tryon_orchestrator. Passing
    `engine` pins one provider (no fallback).
    """
    problems = check_person_photo(person_bytes)

    if problems:
        raise PhotoUnsuitable(" ".join(problems))

    from backend import tryon_orchestrator

    pinned = engine is not None
    engine = engine or tryon_orchestrator.active()

    if engine is None or not engine.available():
        raise tryon_orchestrator.nothing_available_error() if not pinned else TryOnUnavailable(
            "Virtual Try-On is not configured yet.",
            detail="missing: " + ", ".join(engine.missing_configuration()),
            state=CONFIGURATION_ERROR,
        )

    passes, not_applied, outfit_problems = plan_outfit(
        items, max_passes=engine.max_passes()
    )

    if outfit_problems:
        raise PhotoUnsuitable(" ".join(outfit_problems))

    current = person_bytes
    worn = []
    used = []

    for index, (item, model_category) in enumerate(passes, start=1):

        if on_progress:
            on_progress(
                index,
                len(passes),
                f"Putting on the {item.get('category', 'garment').lower()}"
                + (f" ({index} of {len(passes)})" if len(passes) > 1 else ""),
            )

        garment_bytes = garment_image_bytes(item)

        if pinned:
            current = _run_pass(engine, current, garment_bytes, model_category)
            used.append(engine.name)
        else:
            # Each pass is sent to ONE provider at a time; if it fails
            # for a provider-side reason the next provider gets the same
            # pass (never the same provider twice).
            current, engine = tryon_orchestrator.run_pass(
                current, garment_bytes, model_category, prefer=engine
            )
            used.append(engine.name)

        worn.append({
            "item_id": str(item.get("_id", "")),
            "category": item.get("category", ""),
        })

    return current, {
        "worn": worn,
        "not_applied": [
            {
                "item_id": str(entry["item"].get("_id", "")),
                "category": entry["item"].get("category", ""),
                "image_url": item_image(entry["item"]),
                "reason": entry["reason"],
            }
            for entry in not_applied
        ],
        "passes": len(passes),
        # Kept on the server-side record only; never sent to the browser.
        "provider": used[-1] if used else "",
        "providers": used,
        # True when a provider other than the first configured one did
        # (some of) the work - the browser is told only this, generically.
        "fallback_used": (not pinned) and any(
            name != tryon_orchestrator.primary().name for name in used
        ),
    }
