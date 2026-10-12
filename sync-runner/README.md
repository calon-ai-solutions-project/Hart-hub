# Hart Hub sync runner

Collects the cars from Hart's saved-search alerts on **Motorway**, **Carwow**, **BCA** and **Manheim**
(details, sale end time, photos) and posts them to the Hart Hub backend (`../backend`). It runs on
the dedicated machine that holds the logged-in sessions, not on Railway.

## Two commands

| Command | What it does |
|---|---|
| `python run_scrape.py` | Finds cars: runs each platform's scraper with your filters (max mileage, min year) and stores every car and its photos in the hub's database. Run it when you want new stock. |
| `python run_sync.py` | Keeps them right: once per platform per UK day, after that platform's slot, it re-opens the stored cars that are still live and updates price, bids and end time. A car whose page is gone is ended. |

Both go through the hub's API, so the hub must be running (`python manage.py runserver 8001` in
`../backend`, or the Railway deployment) and `HUB_URL` must point at it. Both skip any platform
whose `SYNC_ENABLED_<PLATFORM>` switch is off in the hub.

`run_scrape.py` searches a platform by filter rather than reading Hart's saved-search alerts. The
contract's sync rules describe alert listings only, so agree this with Alom before using it on a
live platform account.

## The rules the daily sync follows

The daily sync is `run_sync.py`, and it follows the platform sync rules in the contract:

- It asks the hub for today's run. The hub hands one out only if the platform is switched on, its
  daily slot has passed and it has not already run today.
- It opens **only** the listing URLs on that run's allowlist (cars from Hart's saved-search alerts
  and live cars `run_scrape.py` stored), one
  at a time with a pause, and posts each car and its photos to the hub. It never walks a platform's
  search and never touches the database itself.
- On any CAPTCHA, verification, unusual-activity notice, access denied, 403 or 429 it stops the
  whole run and reports it. Nothing is retried or waited out.
- If a session has expired it runs that platform's login script itself (a Chrome window opens, logs
  in with the details in `.env` and closes), then carries on with the listings not done yet. It
  tries at most twice per platform; `--no-login` switches this off. A CAPTCHA on the login page is
  never bypassed: the window waits for a person to complete it.
- It is read only: it never bids, watches or buys. Motorway private sellers' contact details are
  never saved.

## Layout

| Path | What it is |
|---|---|
| `run_scrape.py` | Scrape the platforms and store the cars in the hub |
| `run_sync.py` | The daily sync loop |
| `scrapers/guard.py` | Allowlist check, pause between pages, stop conditions |
| `scrapers/collectors.py` | One allowlist collector per platform |
| `scrapers/hub.py` | Client for the hub's sync API |
| `scrapers/<site>_scraper.py` | Page parsing and photo download for that platform |
| `scrapers/<site>_login.py` | A person runs this to log in (visible Chrome) and save the session |
| `scrapers/paths.py` | Where sessions, exports and logs are kept |
| `tests/` | Guard tests |
| `docs/` | Per-platform notes on how the data is read |
| `sessions/`, `export_data/`, `logs/` | Created when it runs; never committed |

## Setup

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
copy .env.example .env
```

In `.env` set `HUB_URL` and `HUB_RUNNER_TOKEN` (issued on the hub with
`python manage.py create_runner_token <name>`) and the platform login details the login scripts use.

## Run

```bat
python scrapers\motorway_login.py   :: log in by hand (both commands also do this when a session expires)
python run_scrape.py                :: find cars on all four platforms and store them
python run_scrape.py --only motorway --limit 5
python run_scrape.py --upload-only  :: store what is already in export_data, scrape nothing
python run_sync.py                  :: update the stored cars (once per platform per UK day)
python run_sync.py --only motorway
python -m unittest discover tests
```

`run_sync.py` says why when it has nothing to do (switched off, slot not reached, already run today).
Slots are UK time and can be changed in the hub admin under Settings (`sync_slot_<platform>`).
Output is also written to `logs/scrape-<date>.log` and `logs/sync-<date>.log`.

Photos are saved under `export_data/<site>_export/images/` before they are uploaded to the hub.

## Notes

- BCA needs a real (not headless) browser because of Cloudflare, so its window opens minimised and
  works in the background. It comes forward only if BCA shows a security check for a person to
  complete. `python scrapers/bca_scraper.py --show` keeps it visible. For production, ask BCA about
  an official data feed.
- Motorway runs one live sale a day, so every car in it shares the same end time.
- Confirm each platform's buyer terms allow re-use of its data and photos.
