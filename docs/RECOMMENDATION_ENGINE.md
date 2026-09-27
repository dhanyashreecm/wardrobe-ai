# How the Outfit Recommendation Engine Works

A rule-based, explainable engine (no black-box ML for ranking). Every
suggestion comes with "Why this works" reasons built from the same
numbers used to rank it.

## Pipeline (backend/outfit_recommendation.py → recommend_outfits)

1. **Hard filters**
   - *Gender* – a men's account never gets saree/lehenga etc. (and vice versa).
   - *Occasion* – each garment kind has a set of occasions it suits
     (e.g. Dhoti Pants → wedding/traditional/party, T-Shirt → casual/college/date/day out).
     An item that doesn't suit the occasion is never used.

2. **Build real outfits** (backend/outfit_builder.py)
   - Every item gets a *kind* (tshirt, kurta_women, saree, mojari, belt…) and a *role*
     (top, bottom, one-piece, layer, footwear, accessory).
   - Explicit pairing table, e.g. Sherwani → only Dhoti/Trousers; Women's Kurta →
     Salwar/Leggings, Palazzo, Jeans, Pant.
   - Saree/Lehenga are built as **sets** with the best-matching blouse.
   - Petticoats are never shown; a blouse is only used inside a set.
   - Western and ethnic stay separate: a Crop Top/Top is a western top (never a saree/lehenga
     blouse), **Traditional** shows ethnic outfits only (no western or kurta + jeans), and
     sarees/lehengas are shown only for **Wedding** and **Traditional**.
   - Top/bottom pairs whose colours clash are **rejected**.
   - The whole wardrobe is considered.

3. **Complete the look**
   - *Layer* (jacket/coat/blazer/Nehru) only when there's a reason: cold, rain or wind;
     a blazer for office/interview; a Nehru jacket for wedding/traditional/party.
     Never in hot weather.
   - *Footwear* – mojaris for ethnic, boots when cold/rainy, best colour match otherwise.
   - *Accessories* – up to 2, of different types, suited to the outfit and occasion
     (dupatta only with a suit or lehenga, belt only with western bottoms,
     no mixing of gold and silver jewellery).

4. **Score** (higher = better)

   | Factor | What it measures |
   |---|---|
   | Occasion fit | Garment kinds typical for the occasion + right level of dressiness |
   | Colour harmony | Neutral balancing, monochromatic, analogous, complementary, triadic |
   | Style match | Formality compatibility (casual / smart casual / formal / traditional / festive) |
   | Weather | Light pieces when hot, warm layers when cold/rain/wind; shorts penalised in cold |
   | Activity | Optional nudge (sports, outdoor, travel, formal event) |
   | Wear history | Pieces worn in the last 2 days −12, this week −6, same outfit this week −10 |
   | Likes | Liked combination +12; disliked combinations are never shown again |

5. **Keep occasions and activities different** (backend/outfit_assignment.py)
   - Many outfits are valid for several occasions (t-shirt + jeans suits casual, college,
     day out and date). To avoid showing the same outfits everywhere, every outfit gets
     ONE home occasion through a *draft*: occasions take turns picking the outfit most
     specific to them (the occasion with fewest options picks first each round).
   - Activities are real filters now (sports → t-shirts/shorts/leggings + sports shoes;
     formal event → no t-shirts, shorts or jeans; …) and are drafted the same way,
     so outdoor and travel don't repeat each other either.
   - If a wardrobe is too small to give a choice its own outfits, shared outfits are
     shown with a clear note instead of an empty page.

6. **Diversify** – picks the best outfits while spreading which garments are used,
   so one shirt doesn't appear in every suggestion.

## Final validation, presentation and inspiration

- **Final validator** (`outfit_presentation.validate_outfit`, applied in `recommend_service.finalize`):
  every outfit is re-checked against the user's stored wardrobe before it reaches the browser -
  item exists (not deleted), belongs to this user, has an image, right gender, no duplicate item,
  complete (top + bottom or one-piece), right occasion, and Traditional is ethnic-only.
  Failures are dropped and logged, never "fixed up".
- **Filters**: Colour and Style (Casual / Smart / Formal / Party / Ethnic) on the recommendations page.
- **Titles / tags / "why this works"**: generated from the same data used for scoring.
- **Pinterest inspiration**: search links built from the outfit's own pieces and occasion
  (no scraping, no copied images). If Pinterest is unreachable nothing else is affected.
- **Home page** (`/api/home`): item counts, recently added, favourites and the four Style Edits
  (Weekend = day outing, After Dark = party, Festive = traditional, Campus = college) are all
  built from the user's wardrobe by the same engine.
- **Trip looks**: Sightseeing / Relaxed Day / Evening Dinner / Night Out, each using the
  destination's weather and never repeating main pieces.

## Automatic category (backend/garment_classifier.py)

MobileNetV2 features + a logistic-regression head trained on Myntra (western + Indian wear,
footwear, accessories) and IndoFashion (lehenga, blouse, sherwani…). Train once with
`python -m backend.train_garment_classifier`; fix old items with
`python -m backend.reclassify_wardrobe you@email [--apply]`.

## Personalisation (backend/outfit_feedback.py)

- **I wore this** → saved in `wear_log`; those pieces rank lower for a few days.
- **Like / Dislike** → saved in `outfit_feedback`, keyed by the outfit's main garments
  (accessories ignored, so the same shirt + jeans is the same outfit).

API: `POST /api/outfits/wear`, `POST /api/outfits/feedback`, `GET /api/outfits/history`.

## Tests

```bash
python -m unittest discover backend/tests -v
```

62 tests (two files) cover garment recognition, pairing rules, sets, colour clashes,
layers and weather, gender separation, wear history, likes/dislikes, and no repetition across occasions/activities.
