# Style inspiration pictures

Put curated reference looks here — for example outfits you saved from
Pinterest boards you follow. The app shows them as **pictures only**
(no links, no source names) in the "Inspiration" section of Outfit
Recommendations, only to accounts of the matching gender and only for
the matching occasion. They are never treated as items in anyone's
wardrobe.

## Folders

    inspiration_images/
      male/     casual  day_outing  college  interview  office  date  party  wedding  traditional  sports
      female/   casual  day_outing  college  interview  office  date  party  wedding  traditional  sports

Also accepted: `formal` (= interview), `date_night` (= date), `festive` (= traditional).

## Rules

* JPG, PNG or WEBP, at least **400 px** on the short side (portrait
  outfit photos around 800×1200 look best). Smaller files are refused,
  never stretched.
* One look per picture; up to 8 per folder are shown.
* Only use pictures you are allowed to use.

## Publish (makes them appear on every device)

    cd ~/Desktop/wardrobe-ai && source ai_env/bin/activate
    python -m backend.build_inspiration --dry-run   # check what will be published
    python -m backend.build_inspiration             # upload to Cloudinary + save the list in Atlas

Re-run after adding or removing pictures. Removed pictures disappear
from the app too.
