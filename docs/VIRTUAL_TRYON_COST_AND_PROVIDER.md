# Virtual Try-On: provider, free capacity, and the ten daily images

The requirement this document answers is **ten successfully generated,
viewable try-on images per registered user per day, at ₹0**.

The short version, stated plainly because it matters more than anything
else here: **the application now enforces and reports ten successful
images per user per day, and it is capable of delivering them — but only
one of the free compute options can actually supply the GPU time, and it
is not the one the project was pointed at.** The public Hugging Face
Space cannot, by arithmetic, and no amount of application code changes
that. Details below.

## 1. The model and the provider layer

| | |
|---|---|
| Model | **FASHN VTON v1.5** — maskless virtual try-on, pose estimation (DWPose) inside the model |
| Licence | **Apache-2.0** — permissive, commercial use allowed |
| VRAM | **~8 GB** for inference |
| Speed | ~5 s on an H100; roughly 20–60 s on the free 16 GB cards below |
| Categories | `tops`, `bottoms`, `one-pieces` |
| Called through | `backend/virtual_tryon.py`, supervised by `backend/tryon_orchestrator.py` |

The licence is why this model and not a better-known one. IDM-VTON,
CatVTON, OOTDiffusion, StableVITON, VITON-HD and HR-VITON are all
**CC BY-NC-SA 4.0**, which forbids commercial use. FASHN VTON v1.5 is
Apache-2.0, so the project is not relying on a licence it would breach
the moment it left a classroom.

**The model has not been changed, and neither has its quality.** Same
weights, same resolution and parameters, same garment planning and
layering order, same pre-processing, same storage and display. Every
change described here is around the generation call, never inside it.

## 2. Where the GPU time comes from: the options, measured

| Option | Free allowance | GPU | Fits the model? | Realistic images/day |
|---|---|---|---|---|
| **Hugging Face ZeroGPU**, anonymous | ~**2 GPU-min/day**, lowest queue priority | RTX Pro 6000 (48 GB) | yes | **~2–5 for the WHOLE app** |
| **ZeroGPU**, free account token | ~**3.5–5 GPU-min/day**, needs a verified account **over 30 days old** | same | yes | **~5–10 for the WHOLE app** |
| ZeroGPU, PRO | ~25 min/day | same | yes | — **paid, excluded** |
| **Kaggle Notebooks** | ~**30 GPU-hours/week**, 12-hour sessions, phone-verified account, Internet switched on | P100 or 2×T4 (16 GB) | yes (8 GB needed) | **hundreds** — capacity is not the limit, uptime is |
| **Google Colab** free | no published allowance; a GPU "when one is spare", up to 12 h, disconnects when idle | usually T4 (16 GB) | yes | tens to hundreds, unpredictable |
| Lightning AI | 15 credits/month, **expire monthly** | T4…H200 | yes | small, and a trial — excluded by the ₹0-no-expiring-trial rule |
| Paperspace Gradient free | 6-hour sessions, notebooks public | M4000 (8 GB) | marginal at 8 GB | unreliable |

### The arithmetic that decides this

ZeroGPU's allowance belongs to **the caller**, not to the Space. This
application calls the Space from one backend, so **every registered user
shares one allowance**. Ten images per user per day for eight users is
80 generations — roughly 40 GPU-minutes. The free ZeroGPU ceiling is
about 3.5–5 minutes **in total, for everyone, per day**.

So the honest answer to "can ten images per user per day be guaranteed
on the public Space?" is **no, and it is not close** — it is short by
roughly a factor of ten even for a single user. Switching to a different
ZeroGPU Space does not help: the allowance is counted per account across
all of them. Using several Hugging Face accounts to get around it would
be breaking the rules, so it is not on this list.

### The option that does work

**Kaggle Notebooks.** About 30 GPU-hours a week on a 16 GB P100 or two
T4s, in sessions of up to 12 hours, for a phone-verified free account.
The model needs 8 GB, so it fits. At roughly 30 seconds a try-on, 30
hours is on the order of 3,500 generations a week — far beyond 10 a day
per user for every account in this project.

The limiting factor on Kaggle is **uptime, not GPU time**: the notebook
has to be running, it stops at the 12-hour session limit, and the
`gradio.live` link changes on every restart. That makes it the right
thing to start before a demo or a marking session, not infrastructure
that stays up on its own.

Google Colab is the same code on a second free GPU. It publishes no
allowance and can refuse outright when GPUs are scarce, so it is best
used **alongside** Kaggle rather than instead of it.

## 3. What was implemented

**Capacity.** `spaces/tryon/kaggle_tryon.ipynb` is new: the same model,
the same `/try_on` contract the backend already expects, set up for
Kaggle — it checks for a GPU, checks that Internet is enabled (Kaggle
disables it by default), downloads the weights, warms the model up so the
first real user does not pay for CUDA compilation, and serves one
generation at a time (two at once on a 16 GB card can run out of memory
and fail both). A **second notebook slot** was added,
`TRYON_FALLBACK_URL_2` → provider `self_hosted_2`, so Kaggle and Colab
can both be configured: two notebooks are two separate free GPUs, and one
falling asleep stops being an outage.

The recommended order is now
`TRYON_PROVIDERS=self_hosted,self_hosted_2,fashn_space` — your own
notebooks first, the public Space as the last resort rather than the
main road. `.env.example` says so and explains why.

**The counter counts images, not requests.** An attempt is reserved
before generation and then resolved by what actually happened:

* **settled** — the provider produced an image and the backend stored
  it. This is the only way an attempt is spent.
* **released** — a *confirmed* failure that produced nothing (allowance
  refused, queue full, Space asleep or unreachable, credentials or
  settings wrong, unusable photo, unsupported garment, our own storage
  failed). The attempt goes straight back.
* **held** — an *uncertain* outcome: a timeout, a broken connection, or
  the backend killed mid-generation. The model may have finished the
  picture at the other end, so releasing at once would let somebody
  collect images while paying for none. The hold expires after
  `TRYON_UNCERTAIN_HOLD_SECONDS` (one hour, many times longer than any
  generation) and the attempt returns on the next ordinary read of the
  counter. This is also what rescues an attempt when the backend
  restarts: the thread that would have resolved it is gone, but the hold
  it left behind expires by itself.

The API reports both numbers: `successful` (images the user can open) and
`in_progress` (reserved but not yet an image). The page shows
**`3/10` try-ons created today · 7 remaining**, plus "1 in progress"
while one is running, so the headline figure never claims an image that
does not exist.

**Not spending the free GPU by accident.** Six guards: the button is
disabled while a generation runs; a synchronous in-page flag catches a
second click before React re-renders; a **request identifier** on each
submission means a double-click or a retry after a dropped connection is
answered with the job already started; a **unique index** on
`(user_email, request_id)` closes the last window where two copies arrive
before either sees the other; **one try-on per account at a time** (a
second tab or the other laptop gets HTTP 409, charged nothing, and is
pointed at the running job); and **no automatic retries** — failover
tries each provider at most once per pass, and a retry only happens
because a person pressed Retry, which first checks that a provider is
usable at all. Requests that cannot succeed never reach a provider.

There is deliberately **no result caching**: a loosely-keyed cache could
show one person another garment's try-on, which is far worse than
spending a GPU second.

**Security.** The quota is enforced entirely in the backend, keyed on the
JWT identity. Nothing the client sends influences it — `request_id` is
the only new client field, it is validated as a string of at most 64
characters, and it is only ever looked up scoped to the authenticated
user (there is a test that one account's identifier cannot reach
another's job). The usage document's `_id` is derived from the account
and the day, so it cannot be addressed or reset from outside. No secret,
provider name, Space id, token or setting *value* appears in any
user-facing message or in the frontend.

## 4. Does it cost anything?

**No.** No paid service, no billing, no trial that expires, no new
third party, no new database and no new storage. The model is
Apache-2.0 on free compute; the counter lives in the MongoDB Atlas
cluster the project already uses, as one small document per account per
day.

No API calls to any provider were added. Everything new is a database
operation: one atomic `find_one_and_update` to reserve, one `update_one`
to resolve, one `find_one` to read the counter, one indexed `find_one`
to recognise a repeated submission, one indexed `find` to check nothing
is already running. **Reading the counter never generates an image and
never contacts a provider** — there is a test asserting exactly that.
Two non-unique-plus-one-unique indexes were added through the existing
idempotent `ensure_indexes()`, which can be run any number of times and
alters no data.

## 5. Behaviour when a provider fails

| What happened | Shown to the user | The attempt |
|---|---|---|
| Image produced | the result | **spent** |
| Free GPU allowance used up | "today's free allowance has been used up" | **returned** |
| All GPUs busy / rate limited | "receiving too many requests" | **returned** |
| Space or notebook asleep, unreachable | "starting up" / "can't be reached" | **returned** |
| Credentials or settings wrong | a plain sentence, no secret, no setting value | **returned** |
| Photo or garment unusable | what to change about the photo | **returned** |
| Our own storage failed | "the try-on worked but the image couldn't be saved" | **returned** |
| Timed out, connection broke, backend restarted | "we couldn't confirm whether the image was created" | **held**, then returned automatically |

The page never confuses the two limits. A user with seven images left
whose try-on failed because the GPUs were busy is told the *service* is
unavailable and that their seven remain untouched — never that they have
run out.

**Known limitation:** the providers are Gradio endpoints. They offer no
"what happened to request X" lookup and no idempotency key, so an
uncertain outcome genuinely cannot be resolved by asking them.
Hold-and-expire is a safe substitute, not a reconciliation. If a provider
that does support status checks is added later,
`tryon_usage.release_stale_holds` is where it belongs.

## 6. Settings

| Setting | Default | What it does |
|---|---|---|
| `TRYON_PROVIDERS` | `self_hosted,self_hosted_2,fashn_space` | which providers, in order |
| `TRYON_FALLBACK_URL` | *(blank)* | the `https://….gradio.live` link your Kaggle notebook prints |
| `TRYON_FALLBACK_URL_2` | *(blank)* | the same for a second notebook (Colab) |
| `TRYON_SPACE_ID` | `fashn-ai/fashn-vton-1.5` | the public Space, used last |
| `HUGGINGFACE_API_TOKEN` | *(blank, optional)* | a free **read** token; moves ZeroGPU from the anonymous allowance to your account's, if the account is over 30 days old |
| `TRYON_DAILY_LIMIT` | 10 | successful images per account per day |
| `TRYON_RESET_OFFSET_HOURS` | 5.5 | which midnight the day ends at (+5:30 = India) |
| `TRYON_MAX_CONCURRENT_JOBS` | 1 | try-ons one account may run at once |
| `TRYON_UNCERTAIN_HOLD_SECONDS` | 3600 | how long an unresolved attempt is held before it comes back |
| `TRYON_TIMEOUT_SECONDS` | 300 | how long one generation may take |

A fixed offset rather than a named timezone on purpose: `zoneinfo` needs
the `tzdata` package on Windows and raises without it, so a zone name
would work on the Mac and fail on the Windows laptop — and the two
machines would then disagree about what day it is.

## 7. Verification

**Backend:** `python -m unittest discover -s backend/tests -t .` —
**313 tests, all passing.** The ones specific to this requirement: ten
successful generations each producing a viewable image and the eleventh
refused with 429; the counter equalling the number of images actually in
the history; a generation in flight reported as in progress rather than
as an image; ten of forty simultaneous requests granted and no more; a
repeated request identifier making one job; two identical submissions at
the same instant making one job; a second concurrent try-on refused
without charge; a confirmed provider failure returning the attempt; a
provider limit never reported as the daily limit; an uncertain outcome
held rather than refunded, and coming back when it expires; an
interrupted generation not locking an attempt for ever; reading the
counter generating nothing; the second notebook taking over a failed
request without charging twice; and one account's request identifier
never reaching another's job.

**Frontend:** `npm test -- --watchAll=false` — **61 tests, all
passing**, including six new ones for the counter, the in-progress
figure, the exhausted state, the "this cost you nothing" message, the
"on hold" message, and the request identifier. `npm run build` compiles
with **no warnings**.

**What has NOT been verified:** no real image was generated during this
work. The public Space was confirmed to be up and running on ZeroGPU,
which is a reachability check, not a generation — and deliberately so,
since one real call would have spent most of a day's free anonymous
allowance. **Nobody should treat "313 tests pass" as evidence that the
free GPU will produce ten images today.** The application's side is
tested; the provider's capacity is the table in section 2.

## 8. What you have to do by hand

1. **Open `spaces/tryon/kaggle_tryon.ipynb` on Kaggle**, set
   Accelerator to GPU and Internet to On (Kaggle requires a
   phone-verified account for Internet), run the cells, and copy the
   `https://….gradio.live` link it prints.
2. Put that link in `.env` with
   `python -m backend.set_secret TRYON_FALLBACK_URL`, on each machine
   that runs the backend.
3. Optionally do the same with `colab_tryon.ipynb` into
   `TRYON_FALLBACK_URL_2`, for a second free GPU.
4. Set `TRYON_PROVIDERS=self_hosted,self_hosted_2,fashn_space`.
5. **Keep the notebook tab open while the app is being used.** The link
   changes on every restart and has to be set again.
6. A `gradio.live` link is **public while it lasts** — anyone holding it
   can send images to your notebook. Do not post it anywhere, and
   restart the notebook if you ever paste it somewhere by accident.

No account was created, no terms were accepted, and no billing was
enabled on your behalf.

## 9. The honest summary

* The application **guarantees** ten *successful* images per user per
  day: correctly counted, enforced in the backend, race-safe, never
  charged for a failure, reset at midnight IST.
* Whether those ten images **actually appear** depends on free GPU
  availability, which no code in this repository controls.
* On the **public Hugging Face Space alone, ten per user per day is not
  achievable** — the free allowance is a few GPU-minutes a day shared by
  the entire application.
* On a **Kaggle notebook you start yourself, it is comfortably
  achievable**, at ₹0, for as long as the notebook is running.
* The closest thing to a zero-cost guarantee is therefore: Kaggle as the
  primary provider, Colab as the second, the public Space as a
  last-resort trickle — which is exactly how the project is now
  configured.
