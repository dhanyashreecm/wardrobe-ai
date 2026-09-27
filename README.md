# Wardrobe-AI

A digital wardrobe and outfit recommender: upload photos of your
clothes, and the app classifies them, detects their colour, and
suggests outfits for an occasion, an activity and the weather.

Flask + MongoDB on the backend, React on the frontend, TensorFlow/
MobileNetV2 for the image models.

**Your account, not your computer, owns your wardrobe.** Log in on any
machine and you see the same clothes, because every machine talks to
one shared MongoDB Atlas database and one shared Cloudinary image
store. Each developer still runs the app locally - nothing has to be
deployed for this to work.

---

## 1. Required software

| What | Why | Notes |
|---|---|---|
| Python 3.9+ | backend | 3.9.6 and 3.11 are both known to work here |
| Node.js 18+ and npm | frontend | |
| A MongoDB Atlas account | shared database | free M0 tier is enough |
| A Cloudinary account | shared image storage | free tier is enough |

The AI models also need the `dataset/` folder (feature files and the
trained `.keras` model). It is deliberately **not** in git - it is
hundreds of megabytes - so copy it from the other developer's machine
or regenerate it with the scripts in `backend/`.

---

## 2. Getting the project

```bash
git clone https://github.com/dhanyashreecm/wardrobe-ai.git
cd wardrobe-ai
```

### Python environment

macOS / Linux:

```bash
python3 -m venv ai_env
source ai_env/bin/activate
pip install -r backend/requirements.txt
```

Windows (PowerShell):

```powershell
python -m venv ai_env
Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process
.\ai_env\Scripts\Activate.ps1
pip install -r backend\requirements.txt
```

`Set-ExecutionPolicy ... -Scope Process` applies to that one window
only, and is needed again in every new PowerShell window. In Command
Prompt, activate with `ai_env\Scripts\activate.bat` and skip that line.

### Frontend dependencies

```bash
cd frontend
npm install
cd ..
```

---

## 3. Environment variables

The backend reads everything machine-specific from a `.env` file in
the project root. Create it from the template:

```bash
cp .env.example .env      # Windows: copy .env.example .env
```

| Variable | Required | What it is |
|---|---|---|
| `MONGODB_URI` | yes | Atlas connection string (`mongodb+srv://...`) |
| `MONGODB_DB_NAME` | yes | database inside the cluster, e.g. `ai_wardrobe` |
| `JWT_SECRET_KEY` | yes | long random string that signs login tokens |
| `CLOUDINARY_CLOUD_NAME` | for shared images | from the Cloudinary dashboard |
| `CLOUDINARY_API_KEY` | for shared images | from the Cloudinary dashboard |
| `CLOUDINARY_API_SECRET` | for shared images | from the Cloudinary dashboard |
| `OPENWEATHER_API_KEY` | optional | enables weather-aware recommendations |

Generate a signing key with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

**Both computers must use the same `MONGODB_URI`, `MONGODB_DB_NAME`
and `JWT_SECRET_KEY`.** Different database values mean separate
wardrobes - the exact problem this setup fixes. A different signing
key means a login token issued by one machine is rejected by the
other.

### `.env` must never be committed

It holds the database password and the Cloudinary secret; anyone with
them can read or delete every user's data. `.gitignore` already
excludes it. `.env.example` (placeholders only) is what belongs in
git. If a real secret is ever committed, rotate it in Atlas/Cloudinary
rather than only deleting the file - it stays in git history.

### Setting up MongoDB Atlas (once, by one person)

1. Create a free M0 cluster at <https://www.mongodb.com/atlas>.
2. **Database Access** → add a database user with a password.
3. **Network Access** → add the IP addresses of both developers'
   machines. A wrong entry here is the usual cause of a connection
   that hangs and then fails.
4. **Connect → Drivers → Python** → copy the connection string into
   `MONGODB_URI`, replacing `<password>` with the real password.
5. Send the other developer the same values over something private -
   not a git commit.

### Setting up Cloudinary (once, by one person)

Sign up at <https://cloudinary.com>, then copy Cloud name, API key and
API secret from the dashboard into both `.env` files. Uploads are
organised as `ai-wardrobe/<hashed-user-id>/wardrobe/...` - the folder
is a hash, so the public URL never contains anyone's email.

### Frontend variable (optional)

`frontend/.env` only matters if the backend is not on
`http://localhost:5001`:

```
REACT_APP_API_URL=http://localhost:5001
```

React reads this at build time, so restart `npm start` after changing
it.

---

## 4. Running the app

Two terminals, backend first.

**Backend** (project root, virtualenv active):

```bash
python -m backend.app
```

It prints what it is connected to before serving:

```
Wardrobe-AI configuration:
  Database name : ai_wardrobe
  Database host : cluster0.xxxxx.mongodb.net
  Image storage : cloudinary
  Weather       : configured
 * Running on http://127.0.0.1:5001
```

If a required variable is missing it refuses to start and says which
one. That is deliberate: starting against a local database instead
would quietly give this computer its own separate copy of every
account and wardrobe.

**Frontend**:

```bash
cd frontend
npm start
```

Opens <http://localhost:3000>.

---

## 5. Health check

```
GET http://localhost:5001/api/health
```

```json
{
  "status": "ok",
  "database": { "connected": true, "name": "ai_wardrobe", "host": "cluster0.xxxxx.mongodb.net" },
  "storage":  { "backend": "cloudinary", "shared_across_devices": true },
  "weather":  { "configured": true }
}
```

It needs no login (it is what you call when you *cannot* log in) and
contains no passwords, keys or connection strings. `"connected":
false` with HTTP 503 means the backend is running but cannot reach
Atlas - check the password in `MONGODB_URI` and your IP in Atlas
Network Access.

---

## 6. Migrating data from before the shared setup

### The one-command way

Once `.env` is filled in, this does the whole thing on this machine:

```bash
python -m backend.sync_setup
```

It checks the setup, writes a JSON snapshot of this machine's local
database to `backups/`, shows a dry run, waits for you to type `yes`,
migrates, then verifies the result. It stops at the first problem, and
nothing local is ever deleted or modified. If it is interrupted, run it
again - it resumes and copies only what is still missing.

Verify an already-migrated machine without migrating anything again:

```bash
python -m backend.sync_setup --verify-only
```

### Proving both computers really share one wardrobe

With the backend running on both machines:

```bash
python -m backend.sync_test send      # on the first computer
python -m backend.sync_test check     # on the second
```

`send` uploads one small generated test image and prints a marker;
`check`, on the other machine, confirms that item is visible there,
that its image loads from shared storage, and that a login token issued
by the first machine is accepted by the second. Swap the order to test
the reverse direction, then `python -m backend.sync_test cleanup`
removes the probes.

If the two machines are not actually sharing a database, `check` fails
and says so - it cannot pass by accident.

### The step-by-step way

Each machine that used the app when it stored data locally still has
those accounts, items and photos in its own local MongoDB. Move them
into the shared setup with:

```bash
python -m backend.migrate_to_atlas --dry-run   # report only, writes nothing
python -m backend.migrate_to_atlas             # do it
```

Run it on **each** machine that has old data. It never modifies or
deletes the local database or the local image files, never overwrites
an account that already exists in Atlas, and can be run again safely -
it remembers what it already copied and skips it. An item whose owner
has no matching account is imported under `legacy_unassigned` and
listed in the summary rather than being guessed at.

---

## 7. How it fits together

```
Laptop A (Flask + React)  ─┐
                           ├─→  MongoDB Atlas   (accounts, wardrobe, trips)
Laptop B (Flask + React)  ─┘    Cloudinary      (the image files)
```

**Authentication.** Register stores a bcrypt hash of the password -
never the password. Login returns a JWT signed with `JWT_SECRET_KEY`,
which the frontend keeps in `localStorage` and sends as
`Authorization: Bearer <token>`. Every protected route takes the user
from the token (`get_jwt_identity()`), never from anything the browser
claims, so a request cannot ask for someone else's data by changing an
id. Gender is chosen once at registration and is locked afterwards -
no route updates it.

**Wardrobe sync.** Items are stored with the owner's email; the
listing, update and delete queries all filter on it, so deleting or
editing another user's item returns 404 rather than doing anything.
Since the database is shared, uploading on one machine and refreshing
on the other shows the new item.

**Images.** Uploads go to Cloudinary and the database stores the
`https://` URL, which loads on any computer. If Cloudinary is not
configured the app still runs, saving images to `backend/uploads/` on
that machine and saying so at startup and in `/api/health` - handy for
solo work, but those images will not appear elsewhere. Older items
that still hold a `/api/uploads/...` path keep working: the frontend
prefixes a relative path with the API address and leaves an absolute
URL alone.

---

## 8. Welcome and sign-in emails (optional)

When outgoing mail is configured, creating an account sends a
"Welcome to Wardrobe AI" message, and every successful login sends a
"Welcome back" notice that also serves as a security alert - if the
account holder did not just sign in, the message tells them someone
else did.

This is entirely optional. With no mail settings, accounts, wardrobes
and recommendations all work exactly as before; nothing is sent.

### Setting it up with a Gmail account

`SMTP_PASSWORD` is **not** the Gmail password. Google stopped
accepting account passwords over SMTP in 2022, so an App Password is
required:

1. The Google account must have 2-Step Verification turned on.
2. Google Account -> Security -> 2-Step Verification -> App passwords.
3. Create one and copy the 16-character code.

Then, on each machine:

```
python -m backend.set_secret SMTP_USERNAME     # the Gmail address
python -m backend.set_secret SMTP_PASSWORD     # the 16-char App Password
```

`SMTP_HOST` and `SMTP_PORT` default to Gmail's (`smtp.gmail.com`,
port 587) and only need setting for a different provider. Port 465 is
also supported and switches to implicit SSL automatically.

To send only the joining message, or only the sign-in notice, add one
of these to `.env` by hand:

```
SEND_WELCOME_EMAIL=false
SEND_LOGIN_EMAIL=false
```

`set_secret` preserves settings it does not manage, so a line added
this way survives the next time a secret is changed.

### Why mail can never break logging in

Mail servers are slow and occasionally down, and an App Password can
be revoked without warning. None of that is a user's problem when
they are trying to log in, so `backend/email_service.py` is built so
it cannot become one:

- every send runs on a **background thread**, so the login response is
  already on its way back to the browser before the mail server is
  contacted. A server that takes 1.5 seconds adds nothing to login.
- every failure is caught and written to the server log only. There is
  no path by which a mail problem produces a failed login, a 500, or
  an error on screen.
- with no settings configured, every function quietly does nothing.

Mail is only ever sent on a **successful** registration or login, and
only to the address stored on the account - so typing a stranger's
address into the login form cannot make the app send them anything.

The App Password is read from `.env`, used, and never logged, never
returned by any route, and never included in an error message. The
failure descriptions in `email_service._describe_failure` are written
by hand for that reason: `smtplib`'s own exception text can echo the
credentials it just tried.

`run_test22.py` in the test harness covers all of the above,
including that login still succeeds against five different kinds of
mail-server failure.

## 9. Troubleshooting

**"Wardrobe-AI cannot start: required configuration is missing"** -
there is no `.env`, or it is missing a value. The message lists which.

**Backend starts, `/api/health` says `"connected": false`** - Atlas is
unreachable. Usually the password in `MONGODB_URI`, or this machine's
IP not being in Atlas → Network Access.

**`ModuleNotFoundError: No module named 'flask'`** - the virtualenv is
not active. The prompt should start with `(ai_env)`.

**`ModuleNotFoundError: No module named 'dns'` or an SRV error** -
`mongodb+srv://` needs `dnspython`: `pip install dnspython`.

**Images upload but appear broken on the other machine** - that
machine's `/api/health` will show `"backend": "local"`; its `.env` is
missing the Cloudinary values. Items uploaded while it was in local
mode need re-uploading or migrating.

**Two accounts with the same email** - both machines registered
separately before sharing. Keep the Atlas one; the migration script
skips duplicates rather than merging them.

**`npm : File ... cannot be loaded because running scripts is
disabled`** - PowerShell. Run `Set-ExecutionPolicy -ExecutionPolicy
Bypass -Scope Process` in that window, or use Command Prompt.

**Weather says it is not configured** - `OPENWEATHER_API_KEY` is not
set, or a brand-new key has not activated yet (it can take ~2 hours).
