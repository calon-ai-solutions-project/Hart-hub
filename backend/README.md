# Hart Hub backend

Django project that stores the listing database and enforces the platform sync rules (workflow F0).
The portal API and the other workflows (W1 to W6) are added here later as more apps.

## Layout

```
config/                 settings (base, local, test, production), urls, celery
apps/core/              base models, events (append-only), settings rows, UK time helpers
apps/accounts/          staff users and roles (owner, sales, admin)
apps/listings/          listings, photos, pricing, expiry
apps/sourcing/          alerts, sync runs, sync log, runner tokens
    platforms.py        what a listing URL looks like on each platform
    normalisers/        one per platform: scraped record -> listing fields
    services/           alerts (ingest), runs (the sync rules), ingest (save a car)
    api/                the sync API used by the runner + the inbound alert webhook
apps/ai/                the one metered AI client (OpenRouter) and the ai_usage log
apps/matching/          requirements, parsing, hard filters, ranking, option cards
apps/chat/              the staff chatbot: conversations and API (the page is the React app in ../web)
apps/quotes/            Codeweavers finance quotes for chosen cars
```

Views stay thin; rules live in `services/`. Money is integer pence, times are UTC (shown and
scheduled in Europe/London), ids are UUIDs.

## How cars get in and stay right

Cars enter the database in two ways: from forwarded saved-search alert emails (below), or from the
runner's `run_scrape.py`, which searches the platforms by filter and posts each car to
`POST /api/scrape/listings`. Either way the daily sync then re-checks the cars that are still live.

## How a day's sync works

1. Hart's saved-search alert emails are forwarded to `POST /api/alerts/inbound`. Each listing link in
   an alert becomes a listing (live, details still to capture).
2. Once a platform's slot (UK time) has passed, its run for the day is created with its allowlist:
   the URLs from the alerts since the last run plus the live cars the scrape command stored. Alert
   listings that have left the alerts are ended. The worker does this every 5 minutes; without a
   worker it happens when the runner asks for its run.
3. The runner (`sync-runner/run_sync.py`, on the dedicated machine) collects the run, opens only the
   allowlisted URLs and posts each car and its photos back.
4. Every 15 minutes the worker ends listings past their end time and flags those ending soon.
5. A car whose page has gone from the platform (the runner gets a 404 or 410: sold or withdrawn) is
   deleted with its photos, search vector, matches and finance quotes, and a `listing.deleted` event
   records it. Set `sync_delete_sold_listings` (Settings) to false to keep such cars as ended instead.

Rules the hub enforces, whatever the runner does:

| Rule | Where |
| --- | --- |
| Platform must be switched on (`SYNC_ENABLED_<PLATFORM>`) | `runs.prepare_run`, `runs.start_run` |
| One run per platform per UK day | unique constraint on `SyncRun(platform, uk_date)` |
| Only alert listings may be opened | `SyncRun.allowlist`; anything else is refused and logged |
| A stop ends the run, alerts the team, no retry that day | `runs.finish_run` |
| Every URL is logged | `SyncLog` (captured, skipped, stopped, failed, refused) |

## Stock chatbot

The page is the React app in `../web` (`npm run dev`, then http://localhost:5173, staff login through
`/api/auth/login`; see [web/README.md](../web/README.md)). Staff type what the customer wants (the enquiry form is no longer in the chat); the answer is the five best live
cars, each with the reason it was picked. Follow-ups such as "only black" or "any make under £15k"
refine the same request.

- A colour is a preference (other colours still show, flagged) unless the salesperson insists:
  "only grey", "must be grey", or a message that is just the colour. Then other colours are hidden.
- "Cheapest first", "newest", "lowest mileage" set the order; "best match first" resets it.
- The bar above the message box shows the current filters; the x on each removes it. The chips under
  the latest answer are one-tap next steps chosen from what was found.

- Code applies the hard rules first (live, complete, priced, make and model, auto/manual, budget);
  AI only ranks inside that shortlist and writes the one-line reason. It is never given prices and a
  reason that mentions money is replaced.
- AI is on only when `OPENROUTER_API_KEY` and `OPENROUTER_MODEL` are set; otherwise the same flow
  runs on rules alone. Every AI call is logged in **AI usage**.
- A monthly budget is turned into a price ceiling using `finance_estimate_apr_percent` and
  `finance_estimate_term_months` (Settings). It is a filter only, never a quote; Codeweavers quotes
  replace it in the next step.
- **Vector search (pgvector).** With `OPENROUTER_EMBEDDING_MODEL` set, every car's description is
  embedded into `listings_listingembedding` in the same PostgreSQL database. A request is embedded
  too, and cars are ranked by similarity INSIDE the set that already passed the hard filters, so
  "AMG Line" finds "AMG Line Premium" but a CLA never matches an SLK. A car is re-embedded only when
  its description changes. New cars are indexed after each scrape and sync and every 5 minutes by the
  worker; `python manage.py embed_listings` indexes everything waiting. Without the model, or if the
  service is down, matching uses the rules alone.
- Each card has a `customer` part (the only fields a customer may ever see) and a `staff` part.

| Call | Purpose |
| --- | --- |
| `POST /api/chat/conversations` | Start a chat; returns the greeting and form |
| `GET /api/chat/conversations` | Your chats |
| `GET /api/chat/conversations/<id>` | One chat with its messages |
| `DELETE /api/chat/conversations/<id>` | Delete one of your own chats and its messages |
| `POST /api/chat/conversations/<id>/messages` | Send `{"form": {...}}` or `{"text": "..."}` |

## Finance quotes (Codeweavers)

In the chat, tick up to five cars, check the deposit and press **Get finance quotes**.

- **Two ways to get quotes**, chosen by the `codeweavers_method` setting:
  - `api` (default): `apps/quotes/codeweavers_api.py` calls Codeweavers' JSON Finance API
    (`POST /public/v3/jsonfinance/calculate`, Hart's Codeweavers login as HTTP basic auth). All cars go
    in one call, PCP and HP together, in a few seconds. Checked against the Showroom on real cars: the
    same monthly, final payment, APR and total payable to the penny. The lender name is read from
    Codeweavers' terms for the quote. **No quote document (PDF)**: the API does not provide one.
  - `browser`: `apps/quotes/codeweavers.py` signs in to the Showroom in a headless browser, enters
    the car and deal, and reads Codeweavers' answer and PDF (30 to 50 seconds a car, one at a time;
    signs out anyone else using the login). It never opens the Application tab: quotes only.
- Either way, an answer for a different term, price, deposit or annual mileage than asked is refused.
  Codeweavers sometimes lowers the deposit on cheap cars (a lender minimum); those cars are not quoted
  rather than shown with a different deposit.
- Every figure shown comes from Codeweavers. Nothing is calculated or estimated, and a car that
  cannot be quoted shows "Finance quote to follow" with the reason for staff.
- Term, extra mileage, annual mileage, product, credit rating and the wording under each quote are
  Settings rows (`codeweavers_term_months` = 48, `codeweavers_extra_mileage` = 500,
  `codeweavers_annual_mileage` = 8000, `codeweavers_product` = "(MotoNovo Finance) PCP",
  `codeweavers_fallback_product` = "(MotoNovo Finance) HP",
  `codeweavers_credit_tier`, `finance_disclaimer`).
- **PCP only.** Every quote is a 48-month PCP; a car with no PCP at that term is not quoted, so it is
  never offered to a customer (the WhatsApp flow moves on to the next car). Older cars often have no
  48-month PCP. Setting `codeweavers_fallback_product` (empty by default) to an HP product would quote HP
  instead for those cars. The term is never shortened.
- **Checked before it is kept.** The Showroom screen remembers the last car, product and term, so
  every answer is checked against what was asked: registration, mileage, term, price, deposit and
  annual mileage. A calculation or document for anything else is refused.
- Where Codeweavers' document shows its grey "Image not available" box, `apps/quotes/pdf.py` puts the
  standard no-vehicle picture there instead. Nothing else in the document is changed.
- Quotes are shown and sent as figures only; no PDF is offered to staff or customers.
- The same car with the same inputs is not quoted twice in a day for the same person.
- One Showroom proposal is created once and re-used for every quote (`codeweavers_proposal_url`),
  so the Hub does not fill Hart's proposal list.
- Codeweavers allows one session per login. When the Hub signs in, anyone else using that login is
  signed out, and when they sign back in the Hub is signed out until its next quote. Give the Hub
  its own Showroom user.
- `python manage.py codeweavers_quote "AB12 CDE" --mileage 30500 --price 14750 --deposit 2000`
  checks the connection from the command line.

| Call | Purpose |
| --- | --- |
| `POST /api/quotes` | `{"listing_ids": [...], "deposit": "2000", "conversation": "<id>"}`: start quotes |
| `GET /api/quotes?ids=a,b` | How those quotes are getting on, and their figures |
| `GET /api/quotes/<id>/pdf` | Codeweavers' quote PDF (`?download=1` to download) |

## Sync API

All `/api/sync/*` calls need `Authorization: Bearer <runner token>`.

| Call | Purpose |
| --- | --- |
| `POST /api/alerts/inbound` | Alert email webhook (`X-Alert-Token` header or `?token=`) |
| `GET /api/sync/platforms` | Each platform's switch and slot |
| `POST /api/scrape/listings` | Store a car the scrape command found |
| `POST /api/scrape/photos` | One photo for it (multipart: platform, external_id, position, file) |
| `GET /api/sync/next?platform=` | Today's run, or the reason there is none |
| `POST /api/sync/runs/<id>/start` | Claim it: `{"session_ok": true}` |
| `POST /api/sync/runs/<id>/urls` | One per URL opened: outcome and scraped record |
| `POST /api/sync/runs/<id>/photos` | One photo (multipart: url, position, file) |
| `POST /api/sync/runs/<id>/report` | Finish: completed, stopped_by_platform or failed |

## Run locally

```bat
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Set `DATABASE_URL` in `.env` to the Railway Postgres public URL to use it as the main database;
left empty it uses a local SQLite file. Without `REDIS_URL` jobs run inline. Restart `runserver`
after changing `.env`. Admin is at `/admin/`: listings, sync runs with their URL log, alerts, settings, events.

```bat
python manage.py test --settings=config.settings.test
python manage.py embed_listings                         :: build the search vector for every waiting car
python manage.py seed_settings                           :: add a settings row for every default (keeps changed ones)
python manage.py create_runner_token calon-runner-1     :: token for sync-runner/.env
python manage.py import_export motorway ..\sync-runner\export_data\motorway_export\cars.json --images-root ..\sync-runner
python manage.py ingest_alert alert.eml --platform motorway
python manage.py prepare_sync motorway                   :: create today's run now
python manage.py expire_listings
```

## Deploy on Railway

One project, EU region, four services. Set each code service's root directory to `backend`.

| Service | Config file | Runs |
| --- | --- | --- |
| web | `railway.json` | migrations, then gunicorn; health check `/healthz` |
| worker | `railway.worker.json` | Celery worker + beat (keep at one replica: beat must not run twice) |
| Postgres | Railway plugin | set `DATABASE_URL` on web and worker |
| Redis | Railway plugin | set `REDIS_URL` on web and worker |

**Photos and quote documents** live in Cloudinary when `CLOUDINARY_URL` is set (`apps/core/storage.py`),
otherwise in the bucket (`S3_*`), otherwise in `backend/media`. In Cloudinary, photos are ordinary
images; quote PDFs are stored as private ("authenticated") files and only read through the Hub. Cards
point at `/media/listings/...`, a fixed address that `apps/listings/views.py` forwards to where the
photo is kept for signed-in staff, so cards saved in a chat keep their photo.
`python manage.py upload_media`, run once on a machine that has `backend/media` with `CLOUDINARY_URL`
(or the `S3_*` variables) set, copies the existing files up.

Variables for web and worker: see `.env.example`. `SECRET_KEY`, `DATABASE_URL`, `ALLOWED_HOSTS` are
required; add a bucket (`S3_*`) before the first real sync, because a Railway container's disk is
wiped on every deploy. Then run `python manage.py createsuperuser` and
`python manage.py create_runner_token <name>` once from a Railway shell.

`develop` deploys to staging and `main` to production. Keep every `SYNC_ENABLED_*` off on staging.
