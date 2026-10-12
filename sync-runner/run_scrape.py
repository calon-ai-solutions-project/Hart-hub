"""
Find cars on the platforms and store them in the Hart Hub database.

For each platform that is switched on in the hub (SYNC_ENABLED_<PLATFORM>) this
  1. runs that platform's scraper with your filters (stock search, details, photos), and
  2. sends every car and its photos to the hub, which stores it as a listing: priced, with its
     end time and status. A car that is already stored is updated, never duplicated.

After this, `python run_sync.py` re-checks the stored cars once a day (price, bids, end time, gone).

Usage:
    python run_scrape.py                       # all four platforms, filters from the hub's settings
    python run_scrape.py --only motorway
    python run_scrape.py --max-mileage 60000 --min-year 2018
    python run_scrape.py --limit 5             # quick test, 5 cars per platform
    python run_scrape.py --no-images           # data only
    python run_scrape.py --upload-only         # send what is already in export_data/, scrape nothing

If a session has expired it runs that platform's login script (a Chrome window opens, logs in and
closes) and then carries on where the scraper stopped; at most twice per platform, and --no-login
switches it off. It stops a platform at once on a 403 or 429 and does not retry those.

Needs HUB_URL and HUB_RUNNER_TOKEN in .env, and the hub running.
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "scrapers"))  # the scraper modules live in scrapers/

from dotenv import load_dotenv  # noqa: E402

load_dotenv(HERE / ".env")

from hub import HubClient, HubError  # noqa: E402
from paths import EXPORTS, ROOT, SESSIONS  # noqa: E402
from run_sync import MAX_LOGINS, PLATFORMS, Log, log_in, photo_files, run_script  # noqa: E402

SESSION_EXPIRED = 2  # a scraper's exit code when the site has logged us out
PHOTO_UPLOADS = 6  # photos sent to the hub at the same time
EXIT_NOTES = {
    2: "could not get a logged-in session - check scrapers/{platform}_login.py works, then run this again",
    3: "the platform stopped us (403 or 429) - nothing was retried; try again tomorrow",
}


def read_cars(path):
    data = path.read_bytes()
    try:
        return json.loads(data.decode("utf-8"))
    except UnicodeDecodeError:
        return json.loads(data.decode("cp1252"))  # carwow and manheim exports use the Windows encoding


def scrape(platform, args, log):
    """Run one platform's scraper, logging in again if its session has expired. Returns its exit code."""
    script_args = ["--max-mileage", str(args.max_mileage), "--min-year", str(args.min_year)]
    if args.limit:
        script_args += ["--limit", str(args.limit)]
    if args.no_images:
        script_args.append("--no-images")
    script = HERE / "scrapers" / f"{platform}_scraper.py"

    logins = 0
    if not (SESSIONS / f"{platform}_session.json").exists():
        if args.no_login:
            return SESSION_EXPIRED
        logins += 1
        if not log_in(platform, log):
            return SESSION_EXPIRED
    while True:
        code = run_script(script, script_args, log)
        if code != SESSION_EXPIRED or args.no_login or logins >= MAX_LOGINS:
            return code
        logins += 1
        if not log_in(platform, log):
            return code
        log(f"{platform}: carrying on where it stopped...")


def upload(hub, platform, cars, images, log):
    saved = new = photos = rejected = 0
    for n, car in enumerate(cars, 1):
        try:
            answer = hub.save_scraped(platform, car)
        except HubError as e:
            if e.status != 422:  # 422 = the hub could not use this one record; carry on with the rest
                raise
            rejected += 1
            log(f"  rejected {car.get('url')} ({e})")
            continue
        saved += 1
        new += answer["created"]
        if images and car.get("image_folder"):
            files = photo_files(ROOT / car["image_folder"])
            wanted = [p for p in answer["missing_photos"] if p in files]
            with ThreadPoolExecutor(max_workers=PHOTO_UPLOADS) as pool:  # several at once: the hub may be far away
                list(pool.map(lambda p: hub.upload_scraped_photo(platform, answer["external_id"], p, files[p]),
                              wanted))
            photos += len(wanted)
        if n % 10 == 0 or n == len(cars):
            log(f"  stored {n}/{len(cars)}")
    note = f", {rejected} rejected" if rejected else ""
    log(f"{platform}: {saved} cars stored ({new} new, {saved - new} updated), {photos} photos uploaded{note}")


def main():
    ap = argparse.ArgumentParser(description="Scrape the platforms and store the cars in the Hart Hub database")
    ap.add_argument("--only", choices=PLATFORMS, help="run just one platform")
    ap.add_argument("--max-mileage", type=int, help="default: the hub's scrape_max_mileage setting")
    ap.add_argument("--min-year", type=int, help="default: the hub's scrape_min_year setting")
    ap.add_argument("--limit", type=int, default=0, help="only this many cars per platform (testing)")
    ap.add_argument("--no-images", action="store_true")
    ap.add_argument("--no-login", action="store_true", help="do not log in automatically when a session expired")
    ap.add_argument("--upload-only", action="store_true", help="send the existing export, do not scrape")
    args = ap.parse_args()

    sys.stdout.reconfigure(errors="replace")
    log = Log("scrape")
    hub = HubClient()
    try:
        switches = hub.platforms()
        filters = hub.scrape_settings()
    except HubError as e:
        raise SystemExit(f"{e}\nIs the hub running, and are HUB_URL and HUB_RUNNER_TOKEN right?")
    args.max_mileage = args.max_mileage or filters["max_mileage"]
    args.min_year = args.min_year or filters["min_year"]
    if not args.upload_only:
        log(f"Filters: max {args.max_mileage:,} miles, {args.min_year} or newer")

    for platform in [p for p in PLATFORMS if not args.only or p == args.only]:
        cars_json = EXPORTS / f"{platform}_export" / "cars.json"
        try:
            if not args.upload_only:
                if not switches[platform]["enabled"]:
                    log(f"{platform}: switched off in the hub (SYNC_ENABLED_{platform.upper()}) - skipped")
                    continue
                log(f"{platform}: scraping...")
                started = time.time()
                code = scrape(platform, args, log)
                if code:
                    log(f"{platform}: " + EXIT_NOTES.get(code, "the scraper failed (exit code {code})").format(
                        platform=platform, code=code))
                if not cars_json.exists() or cars_json.stat().st_mtime < started:
                    log(f"{platform}: nothing new was collected, so nothing was stored")
                    continue
            elif not cars_json.exists():
                log(f"{platform}: no export to upload ({cars_json.relative_to(HERE)})")
                continue
            cars = read_cars(cars_json)
            log(f"{platform}: sending {len(cars)} cars to the hub...")
            upload(hub, platform, cars, not args.no_images, log)
        except HubError as e:
            log(f"{platform}: {e}")


if __name__ == "__main__":
    main()
