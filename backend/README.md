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

Rules the hub enforces, whatever the runner does:

| Rule | Where |
| --- | --- |
| Platform must be switched on (`SYNC_ENABLED_<PLATFORM>`) | `runs.prepare_run`, `runs.start_run` |
| One run per platform per UK day | unique constraint on `SyncRun(platform, uk_date)` |
| Only alert listings may be opened | `SyncRun.allowlist`; anything else is refused and logged |
| A stop ends the run, alerts the team, no retry that day | `runs.finish_run` |
| Every URL is logged | `SyncLog` (captured, skipped, stopped, failed, refused) |

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

Variables for web and worker: see `.env.example`. `SECRET_KEY`, `DATABASE_URL`, `ALLOWED_HOSTS` are
required; add a bucket (`S3_*`) before the first real sync, because a Railway container's disk is
wiped on every deploy. Then run `python manage.py createsuperuser` and
`python manage.py create_runner_token <name>` once from a Railway shell.

`develop` deploys to staging and `main` to production. Keep every `SYNC_ENABLED_*` off on staging.
