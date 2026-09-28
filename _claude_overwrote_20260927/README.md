# Set aside on 27 Sep 2026 — read this before deleting

On 27 September at 14:18 a Claude session committed files into this
project from a copy of the codebase taken on 23–26 September. It did
not know another session had been working here the same day and had
committed newer work at 12:56, 13:01 and 13:15.

Twelve files were overwritten with older versions. They have since
been restored from commit 97d9094, and `git status` confirms each one
now matches that commit exactly.

## What is in this folder

The twelve overwritten versions, at the paths they came from. They are
kept only so nothing was destroyed by the restore. **They are older
than your committed code — do not copy them back over anything.**

    .env.example
    README.md
    backend/app.py
    backend/config.py
    backend/email_service.py
    backend/requirements.txt
    backend/set_secret.py
    backend/storage.py
    frontend/src/App.js
    frontend/src/components/Sidebar.js
    frontend/src/pages/OutfitRecommendation.js
    frontend/src/pages/TripPlanner.js

Also `frontend/src/pages/VirtualTryOn.js` — an AI on-body try-on page
(diffusion model, FASHN VTON v1.5 via a Gradio host). It was moved out
of `src/` because the restored backend has no `/api/tryon/*` routes and
`App.js` does not route to it, so inside `src/` it was only a trap for
the next build. This project already has its own try-on at
`frontend/src/pages/TryOn.js` — a flat-lay board, which needs no GPU
and no external service.

## Still in the project, and harmless

    backend/virtual_tryon.py     the try-on engine  (nothing imports it)
    backend/tryon_store.py       its database layer (nothing imports it)
    spaces/tryon/                the GPU host: HF Space + Colab notebook

Nothing imports those three, so they cannot break anything. Keep them
if you ever want the AI on-body try-on; they are the working parts of
it. Delete them if you are staying with the flat-lay board.

## What may genuinely be lost

Any edit made to those twelve files between 13:15 (the last commit) and
14:18 (the overwrite). `components/Outfit.js` and `lib/categories.js`
carry 13:44 timestamps and were never touched, which suggests the
afternoon's work was elsewhere — but that is an inference, not proof.
