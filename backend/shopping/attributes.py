"""
Clothing attributes as WORDS - the shared language between the photo,
the user's wardrobe and shop listings.

Two sources feed this:

  1. The photo itself, through models the project already has:
     garment_classifier (32 categories) for the type, and
     color_detection for primary/secondary colours and whether it is
     patterned. These are always available.
  2. The titles of products Google Lens matched to the photo
     ("Women Pink Embroidered Straight Kurta with Mandarin Collar").
     Shops write very regular titles, so when several independent
     listings agree on "mandarin collar" and "3/4 sleeves", that is
     good evidence about the photo. No new AI model is needed.

Everything here is plain string work, so it is fast and testable.
"""

import re
from collections import Counter

# ------------------------------------------------------------------
# VOCABULARY - canonical value -> phrases that mean it (lower case).
# Order inside each group matters only for display.
# ------------------------------------------------------------------

SLEEVES = {
    "sleeveless": ["sleeveless", "strappy", "spaghetti strap", "tank"],
    "short sleeves": ["short sleeve", "short-sleeve", "half sleeve", "half-sleeve", "cap sleeve"],
    "3/4 sleeves": ["3/4 sleeve", "three-quarter sleeve", "three quarter sleeve", "elbow sleeve"],
    "full sleeves": ["full sleeve", "long sleeve", "long-sleeve", "full-sleeve"],
    "puff sleeves": ["puff sleeve", "puffed sleeve"],
    "bell sleeves": ["bell sleeve", "flared sleeve"],
}

NECKLINES = {
    "round neck": ["round neck", "round-neck", "crew neck", "crew-neck"],
    "v-neck": ["v-neck", "v neck"],
    "mandarin collar": ["mandarin collar", "band collar", "chinese collar", "nehru collar"],
    "shirt collar": ["shirt collar", "spread collar", "collared"],
    "boat neck": ["boat neck", "boat-neck"],
    "square neck": ["square neck", "square-neck"],
    "sweetheart neck": ["sweetheart neck", "sweetheart"],
    "halter neck": ["halter"],
    "high neck": ["high neck", "high-neck", "turtle neck", "turtleneck", "mock neck"],
    "keyhole neck": ["keyhole neck", "keyhole"],
    "notched neck": ["notched neck", "notch neck"],
    "off-shoulder": ["off-shoulder", "off shoulder"],
    "cowl neck": ["cowl neck"],
    "hooded": ["hooded", "hoodie"],
}

PATTERNS = {
    "embroidered": ["embroidered", "embroidery", "chikankari", "chikan", "zari", "thread work",
                    "threadwork", "resham", "gota", "mirror work", "aari", "kantha"],
    "printed": ["printed", "print"],
    "floral": ["floral", "flower"],
    "solid": ["solid", "plain"],
    "striped": ["striped", "stripe"],
    "checked": ["checked", "checks", "check ", "plaid", "gingham", "tartan"],
    "polka dots": ["polka"],
    "paisley": ["paisley"],
    "geometric": ["geometric"],
    "ethnic motifs": ["ethnic motif", "motifs", "ikat", "ajrakh", "kalamkari", "bandhani",
                      "bandhej", "leheriya", "block print", "batik"],
    "sequinned": ["sequin", "sequinned", "sequined", "embellished", "mukaish"],
    "lace": ["lace"],
    "self design": ["self design", "self-design", "woven design", "jacquard", "brocade"],
    "tie-dye": ["tie-dye", "tie dye"],
    "abstract": ["abstract"],
    "animal print": ["animal print", "leopard", "zebra", "snake print"],
}

SILHOUETTES = {
    "straight": ["straight"],
    "a-line": ["a-line", "a line"],
    "anarkali": ["anarkali"],
    "flared": ["flared", "flare"],
    "kaftan": ["kaftan", "caftan"],
    "fit and flare": ["fit and flare", "fit & flare"],
    "bodycon": ["bodycon"],
    "maxi": ["maxi"],
    "midi": ["midi"],
    "mini": ["mini"],
    "crop": ["crop top", "cropped", "crop"],
    "slim fit": ["slim fit", "slim-fit", "skinny"],
    "regular fit": ["regular fit", "regular-fit"],
    "oversized": ["oversized", "relaxed fit", "boxy"],
    "wide leg": ["wide leg", "wide-leg"],
    "high-low": ["high-low", "high low"],
}

FABRICS = {
    "cotton": ["cotton"], "silk": ["silk"], "rayon": ["rayon"], "linen": ["linen"],
    "georgette": ["georgette"], "chiffon": ["chiffon"], "denim": ["denim"],
    "polyester": ["polyester"], "viscose": ["viscose"], "crepe": ["crepe"],
    "satin": ["satin"], "velvet": ["velvet"], "chanderi": ["chanderi"],
    "organza": ["organza"], "net": [" net ", "net "], "wool": ["wool", "woollen"],
    "khadi": ["khadi"], "modal": ["modal"], "jersey": ["jersey"],
}

COLOURS = [
    "black", "white", "off white", "cream", "ivory", "beige", "grey", "charcoal", "silver",
    "brown", "tan", "camel", "khaki", "navy", "blue", "sky blue", "teal", "turquoise",
    "green", "olive", "mint", "sea green", "emerald", "yellow", "mustard", "gold", "orange",
    "peach", "coral", "rust", "red", "maroon", "wine", "burgundy", "pink", "rose", "magenta",
    "purple", "lavender", "lilac", "mauve", "multicolour",
]
_COLOUR_ALIASES = {"multicolor": "multicolour", "multi-colour": "multicolour",
                   "multi colour": "multicolour", "gray": "grey", "off-white": "off white",
                   "navy blue": "navy"}

# Garment words used in shop titles -> the search term we use for it.
# Checked in order and the first hit wins, so the more specific phrase
# must come first ("t-shirt" before "shirt", "nehru jacket" before
# "jacket").
CATEGORY_WORDS = {
    "kurta set": ["kurta set", "kurta with trousers", "kurta with pants", "kurta with palazzos",
                  "kurta with salwar", "kurta & trousers", "kurta and pants", "salwar suit",
                  "suit set", "kurta & palazzos"],
    "kurta": ["kurta", "kurti"],
    "saree": ["saree", "sari"],
    "lehenga": ["lehenga", "lehnga", "ghagra"],
    "blouse": ["blouse"],
    "gown": ["gown"],
    "dress": ["dress"],
    "top": ["top", "blouse top", "tunic"],
    "t-shirt": ["t-shirt", "tshirt", "tee"],
    "shirt": ["shirt"],
    "jeans": ["jeans", "denim jeans"],
    "trousers": ["trousers", "pants", "chinos", "trouser"],
    "palazzo": ["palazzo"],
    "skirt": ["skirt"],
    "shorts": ["shorts"],
    "nehru jacket": ["nehru jacket"],
    "sherwani": ["sherwani"],
    "jacket": ["jacket", "blazer", "shrug"],
    "dupatta": ["dupatta", "stole"],
    "jumpsuit": ["jumpsuit", "co-ord", "coord"],
}

GROUPS = {
    "sleeve": SLEEVES,
    "neckline": NECKLINES,
    "pattern": PATTERNS,
    "silhouette": SILHOUETTES,
    "fabric": FABRICS,
}

# Classifier category -> (search term, implied audience or None).
# Keys are garment_classifier / category labels and IndoFashion class
# names, compared case-insensitively.
_CATEGORY_TERMS = {
    "kurta (women)": ("kurta", "women"), "women_kurta": ("kurta", "women"),
    "kurta (men)": ("kurta", "men"), "kurta_men": ("kurta", "men"),
    "saree": ("saree", "women"), "lehenga": ("lehenga", "women"),
    "blouse": ("blouse", "women"), "gown": ("gown", "women"), "gowns": ("gown", "women"),
    "dress": ("dress", "women"), "top": ("top", "women"), "skirt": ("skirt", "women"),
    "dupatta": ("dupatta", "women"), "dupattas": ("dupatta", "women"),
    "palazzos": ("palazzo", "women"), "petticoat": ("petticoat", "women"),
    "leggings & salwars": ("salwar", "women"), "leggings_and_salwars": ("salwar", "women"),
    "mojaris (women)": ("mojari", "women"), "mojaris_women": ("mojari", "women"),
    "mojaris (men)": ("mojari", "men"), "mojaris_men": ("mojari", "men"),
    "sherwani": ("sherwani", "men"), "sherwanis": ("sherwani", "men"),
    "nehru jacket": ("nehru jacket", "men"), "nehru_jackets": ("nehru jacket", "men"),
    "dhoti pants": ("dhoti pants", None), "dhoti_pants": ("dhoti pants", None),
    "denims": ("jeans", None), "pant": ("trousers", None), "shirt": ("shirt", None),
    "t-shirt": ("t-shirt", None), "shorts": ("shorts", None), "jacket": ("jacket", None),
    "footwear": ("footwear", None), "bag": ("bag", None), "belt": ("belt", None),
    "watch": ("watch", None), "earrings": ("earrings", "women"),
    "neck chain": ("necklace", None), "finger ring": ("ring", None),
    "hand cuff": ("bracelet", None),
}


def category_term(category):
    """('kurta', 'women') for 'Kurta (Women)'; best effort for anything else."""
    if not category:
        return "", None
    key = str(category).strip().lower()
    if key in _CATEGORY_TERMS:
        return _CATEGORY_TERMS[key]
    return re.sub(r"\s*\(.*?\)", "", key).replace("_", " ").strip(), None


def _normalise(text):
    text = " " + re.sub(r"\s+", " ", str(text or "").lower()) + " "
    for alias, canonical in _COLOUR_ALIASES.items():
        text = text.replace(alias, canonical)
    return text


def _find(text, phrases):
    for phrase in phrases:
        # Word-ish boundaries so "net" doesn't match "cabinet" and
        # "tee" doesn't match "steel".
        # A trailing "s"/"es" is allowed, so "3/4 sleeve" also
        # matches "3/4 Sleeves" and "print" matches "prints".
        pattern = r"(?<![a-z])" + re.escape(phrase.strip()) + r"(?:e?s)?(?![a-z])"
        if re.search(pattern, text):
            return True
    return False


def extract_from_text(text):
    """
    Attributes mentioned in one piece of text (a product title, or the
    user's own keywords). Returns
        {"category": str|None, "colours": [...], "sleeve": [...], ...}
    with every value canonical.
    """
    text = _normalise(text)
    found = {"category": None, "colours": []}

    for canonical, phrases in CATEGORY_WORDS.items():
        if _find(text, phrases):
            found["category"] = canonical
            break

    # Longer colour names first so "sky blue" wins over "blue".
    for colour in sorted(COLOURS, key=len, reverse=True):
        if _find(text, [colour]) and not any(colour in c for c in found["colours"]):
            found["colours"].append(colour)

    for group, vocab in GROUPS.items():
        found[group] = [value for value, phrases in vocab.items() if _find(text, phrases)]

    return found


def consensus_from_titles(titles, min_votes=2, min_share=0.25):
    """
    What several matched product titles agree on. A value counts only
    when at least `min_votes` titles AND `min_share` of all titles
    mention it, so one oddly-worded listing can't decide anything.

    Returns {group: [(value, share), ...]} for colours, sleeve,
    neckline, pattern, silhouette, fabric, and category.
    """
    titles = [t for t in titles if t]
    if not titles:
        return {}

    counts = {key: Counter() for key in ["category", "colours", *GROUPS]}
    for title in titles:
        found = extract_from_text(title)
        if found["category"]:
            counts["category"][found["category"]] += 1
        for key in ["colours", *GROUPS]:
            for value in set(found[key]):
                counts[key][value] += 1

    total = len(titles)
    agreed = {}
    for key, counter in counts.items():
        values = [
            (value, round(votes / total, 2))
            for value, votes in counter.most_common()
            if votes >= min_votes and votes / total >= min_share
        ]
        if values:
            agreed[key] = values
    return agreed
