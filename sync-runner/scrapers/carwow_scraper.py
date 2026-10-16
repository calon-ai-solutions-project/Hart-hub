"""
Carwow dealer stock scraper.

Uses the logged-in session saved by carwow_login.py (carwow_session.json),
applies the stock filters, then for every matching car saves:
  - all listing details (specs, vehicle info, CAP clean/below/average/retail,
    Autotrader retail valuation, service history, condition, MOT, MotorCheck ...)
  - every gallery photo in full size

Output (in ./export_data/carwow_export/):
  cars.csv / cars.json          one row per car
  images/<REG>_<listing id>/    all photos for that car
  raw/<listing id>.html         the original listing page, for reference

Usage:
    python scrapers/carwow_login.py              # once, to log in and save the session
    python scrapers/carwow_scraper.py            # defaults: max 80,000 miles, 2016 or newer
    python scrapers/carwow_scraper.py --max-mileage 60000 --min-year 2018
    python scrapers/carwow_scraper.py --limit 5  # quick test on 5 cars
    python scrapers/carwow_scraper.py --no-images

Re-running continues where it left off (cars already saved are skipped).
"""

import argparse
import csv
import json
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import requests
from bs4 import BeautifulSoup

from paths import EXPORTS, SESSIONS, rel

BASE = "https://dealers.carwow.co.uk"
STOCK_URL = f"{BASE}/dealers/listings/filtered/stock"
SESSION_FILE = SESSIONS / "carwow_session.json"
OUT_DIR = EXPORTS / "carwow_export"
IMAGE_HOST = "https://carwow-sell-my-car.imgix.net/"
PAGE_SIZE = 40  # cars per page of the stock search

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)


class SessionExpired(Exception):
    pass


def polite_pause(low=1.0, high=2.5):
    time.sleep(random.uniform(low, high))


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def money(text):
    """'£17,848' -> 17848 (int) or None."""
    m = re.search(r"£\s*([\d,]+)", text or "")
    return int(m.group(1).replace(",", "")) if m else None


def make_session():
    if not SESSION_FILE.exists():
        raise SystemExit("No saved session - run `python scrapers/carwow_login.py` first.")
    state = json.loads(SESSION_FILE.read_text())
    s = requests.Session()
    for ck in state["cookies"]:
        s.cookies.set(ck["name"], ck["value"], domain=ck["domain"], path=ck["path"])
    s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-GB,en;q=0.9",
                      "Accept-Encoding": "identity"})  # avoids broken-gzip errors
    return s


def get(session, url, **kwargs):
    for attempt in range(4):
        try:
            r = session.get(url, timeout=60, **kwargs)
        except requests.RequestException as e:
            print(f"  network error ({e}), retrying...")
            time.sleep(5 * (attempt + 1))
            continue
        if "auth.carwow.co.uk" in r.url or "/dealers/login" in r.url or "/sign_in" in r.url:
            raise SessionExpired("Session expired - run `python scrapers/carwow_login.py` again.")
        if r.status_code in (403, 429):
            print(f"Carwow answered HTTP {r.status_code} - stopping, nothing is retried.")
            raise SystemExit(3)
        if r.status_code >= 500:
            wait = 15 * (attempt + 1)
            print(f"  HTTP {r.status_code}, waiting {wait}s...")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r
    raise RuntimeError(f"Failed to fetch {url}")


# ---------------------------------------------------------------- listing ids

def collect_listing_ids(session, filters):
    """Walk the stock search (page 1 + infinite-scroll pages) and return listing ids."""
    r = get(session, STOCK_URL, params=filters)
    page_text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.text))
    total = re.search(r"([\d,]+) vehicles matching your filter", page_text)
    total = int(total.group(1).replace(",", "")) if total else None
    pages = -(-total // PAGE_SIZE) if total else None
    print(f"Carwow search has {total if total is not None else '?'} vehicles "
          f"({pages if pages else '?'} pages) - collecting...")

    ids = list(dict.fromkeys(re.findall(r'id="listing-card-(\d+)"', r.text)))
    page_no = 1
    print(f"  page 1/{pages or '?'}: {len(ids)} vehicles found so far")
    while True:
        polite_pause(0.8, 1.6)
        r = get(
            session,
            f"{STOCK_URL}/next_page",
            params={**filters, "offset": len(ids)},
            headers={"Accept": "text/vnd.turbo-stream.html, text/html"},
        )
        new = [i for i in dict.fromkeys(re.findall(r'id="listing-card-(\d+)"', r.text)) if i not in ids]
        if not new:
            break
        ids.extend(new)
        page_no += 1
        print(f"  page {page_no}/{max(pages, page_no) if pages else '?'}: {len(ids)} vehicles found so far")
    return ids


# ---------------------------------------------------------------- detail page


def parse_listing(html, fragments, listing_id):
    # Fragments (condition report, vehicle details/history) are loaded separately by the page
    # Most content sits inside <template> tags, whose text BeautifulSoup ignores - unwrap them
    fragments = [re.sub(r"</?template[^>]*>", "", f) for f in fragments]
    html = re.sub(r"</?template[^>]*>", "", html)
    soup = BeautifulSoup(html + "".join(fragments), "html.parser")
    main = soup
    car = {"listing_id": listing_id, "url": f"{BASE}/dealers/listings/{listing_id}"}

    plates = [clean(p.get_text()) for p in main.select(".listing-plate-component__value")]
    car["registration"] = next((p for p in plates if not p.startswith("VIN")), "")
    car["vin"] = next((p.replace("VIN:", "").strip() for p in plates if p.startswith("VIN")), "")

    def text_of(sel):
        el = soup.select_one(sel)
        return clean(el.get_text(" ")) if el else ""

    car["make_model"] = text_of(".place-bid-modal-component__make-and-model")
    car["derivative"] = text_of(".place-bid-modal-component__engine-and-trim")
    specs_line = text_of(".listing__vehicle-specs")
    car["specs_summary"] = specs_line
    m = re.search(r"([\d,]+)\s*miles", specs_line, re.I)
    car["mileage"] = int(m.group(1).replace(",", "")) if m else None

    # Autotrader retail valuation (the big price shown on the listing)
    car["autotrader_retail_valuation"] = money(text_of(".floating-box-in-auction-component__cap-clean-value")) \
        or money(text_of(".place-bid-modal-component__clean-price-value"))

    # CAP live: Clean / Below / Average / Retail
    for item in main.select(".listing__vehicle-valuation-item"):
        label = clean(item.select_one(".listing__vehicle-valuation-item-label").get_text())
        value = item.select_one(".listing__vehicle-valuation-item-content")
        car[f"cap_{label.lower()}"] = money(value.get_text() if value else "")
    car["cap_last_updated"] = text_of(".listing__vehicle-valuation-last-checked").replace("Last updated", "").strip()

    # Every "label: value" row (vehicle info, specifications, ...)
    for item in main.select(".listing-data-list__item"):
        label = item.select_one(".listing-data-list__label")
        value = item.select_one(".listing-data-list__content")
        if label and value:
            key = re.sub(r"[^a-z0-9]+", "_", clean(label.get_text()).lower()).strip("_")
            car.setdefault(key, clean(value.get_text(" ")).replace(" view details", ""))

    # Summary lists (location, delivery, ...)
    for item in main.select(".summary-list__item"):
        dt, dd = item.find("dt"), item.find("dd")
        if dt and dd:
            key = re.sub(r"[^a-z0-9]+", "_", clean(dt.get_text()).lower()).strip("_")
            car.setdefault(key, clean(dd.get_text(" ")))

    grade = main.select_one(".listing-appraisal-grade-component")
    car["grade"] = clean(grade.get_text(" ")).replace("Grade", "").strip() if grade else ""
    timer = soup.select_one("[data-floating-box-timer-component-end-time-value]")
    car["auction_ends"] = timer["data-floating-box-timer-component-end-time-value"] if timer else ""
    tf = main.select_one(".listing__selling-timeframe-text")
    car["selling_timeframe"] = clean(tf.get_text()).replace("Selling timeframe:", "").strip() if tf else ""

    # Features (Heated seats, Sat nav, ...)
    feats = main.select(".listing__vehicle-features li, .listing__vehicle-feature, [class*='features'] li")
    car["features"] = " | ".join(dict.fromkeys(clean(f.get_text(" ")) for f in feats if clean(f.get_text())))

    # Full readable text of the history/condition sections so nothing is lost
    # (service history, mechanical report, condition/damage, MotorCheck, MOT history)
    for name, frag in zip(("details_and_history_text", "condition_report_text"), reversed(fragments)):
        car[name] = clean(BeautifulSoup(frag, "html.parser").get_text(" "))

    # Gallery photos: unique image ids in gallery order, with their labels
    photos, seen = [], set()
    gallery = main.select_one(".listing__gallery") or main
    for img in gallery.select("img"):
        src = img.get("src") or img.get("srcset") or ""
        m = re.search(r"carwow-sell-my-car\.imgix\.net/([a-z0-9]+)", src)
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            photos.append({"id": m.group(1), "label": img.get("alt") or "photo"})
    car["photo_count"] = len(photos)
    car["photo_urls"] = " | ".join(IMAGE_HOST + p["id"] for p in photos)
    car["photo_labels"] = " | ".join(p["label"] for p in photos)  # e.g. "damage_generic": kept from customers
    return car, photos


def fetch_listing(session, listing_id):
    r = get(session, f"{BASE}/dealers/listings/{listing_id}")
    fragments = []
    for part in ("condition_reports", "provenance_sections"):
        try:
            fragments.append(get(session, f"{BASE}/dealers/listings/{part}/{listing_id}").text)
        except Exception:
            pass
    return r.text, fragments


# ---------------------------------------------------------------- images

def download_photos(car, photos, folder):
    folder.mkdir(parents=True, exist_ok=True)

    def one(idx_photo):
        idx, photo = idx_photo
        name = re.sub(r"[^a-z0-9_]+", "_", photo["label"].lower())
        path = folder / f"{idx:02d}_{name}.jpg"
        if path.exists() and path.stat().st_size > 0:
            return
        for attempt in range(3):
            try:
                r = requests.get(IMAGE_HOST + photo["id"], timeout=60)
                r.raise_for_status()
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(r.content)
                return
            except requests.RequestException:
                time.sleep(3 * (attempt + 1))
        print(f"  could not download photo {photo['id']}")

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(one, enumerate(photos, 1)))


# ---------------------------------------------------------------- output

def save_outputs(cars):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "cars.json").write_text(json.dumps(cars, indent=2, ensure_ascii=False))
    first = ["listing_id", "registration", "vin", "make_model", "derivative", "year_of_manufacture",
             "mileage", "autotrader_retail_valuation", "cap_clean", "cap_below", "cap_average",
             "cap_retail", "grade", "auction_ends", "photo_count", "image_folder", "url"]
    keys = first + sorted({k for c in cars for k in c} - set(first))
    with open(OUT_DIR / "cars.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(cars)


def year_of(car):
    m = re.search(r"\d{4}", car.get("year_of_manufacture") or car.get("first_registered") or "")
    return int(m.group()) if m else None


def main():
    ap = argparse.ArgumentParser(description="Scrape Carwow dealer stock")
    ap.add_argument("--max-mileage", type=int, default=80000)
    ap.add_argument("--min-year", type=int, default=2016, help="oldest year to include")
    ap.add_argument("--limit", type=int, default=0, help="only scrape this many cars (testing)")
    ap.add_argument("--no-images", action="store_true")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "raw").mkdir(exist_ok=True)
    session = make_session()

    filters = {
        "q[state]": "auction",
        "q[mileage_lteq]": str(args.max_mileage),
        # Carwow filters by age in whole years; we re-check the exact year below
        "q[age_in_years_lteq]": str(date.today().year - args.min_year),
    }
    print(f"Filters: max {args.max_mileage:,} miles, {args.min_year} or newer")
    try:
        ids = collect_listing_ids(session, filters)
    except SessionExpired as e:
        print(e)
        raise SystemExit(2)  # exit code 2 = session expired
    if args.limit:
        ids = ids[: args.limit]
    print(f"\nFetching details and photos for {len(ids)} cars...\n")

    existing = {}
    if (OUT_DIR / "cars.json").exists():
        existing = {c["listing_id"]: c for c in json.loads((OUT_DIR / "cars.json").read_text())}

    cars, skipped = [], 0
    for n, listing_id in enumerate(ids, 1):
        car = existing.get(listing_id)
        if car is None:
            try:
                html, fragments = fetch_listing(session, listing_id)
            except SessionExpired as e:
                print(e)
                save_outputs(cars)
                raise SystemExit(2)  # exit code 2 = session expired
            except Exception as e:
                print(f"[{n}/{len(ids)}] {listing_id}: failed ({e})")
                continue
            (OUT_DIR / "raw").mkdir(parents=True, exist_ok=True)
            (OUT_DIR / "raw" / f"{listing_id}.html").write_text(html)
            car, photos = parse_listing(html, fragments, listing_id)
            car["_photos"] = photos
            polite_pause()
        photos = car.pop("_photos", None) or [
            {"id": u.rsplit("/", 1)[1], "label": "photo"} for u in car.get("photo_urls", "").split(" | ") if u
        ]

        year = year_of(car)
        if (car.get("mileage") or 0) > args.max_mileage or (year and year < args.min_year):
            skipped += 1
            print(f"[{n}/{len(ids)}] {car.get('registration')} skipped ({year}, {car.get('mileage')} miles)")
            continue

        folder = OUT_DIR / "images" / f"{re.sub(r'[^A-Z0-9]', '', car.get('registration', '').upper())}_{listing_id}"
        car["image_folder"] = rel(folder)
        if not args.no_images:
            download_photos(car, photos, folder)
        cars.append(car)
        print(f"[{n}/{len(ids)}] {car.get('registration')} {car.get('make_model')} "
              f"{year} {car.get('mileage')} mi - {len(photos)} photos")

        if n % 10 == 0:
            save_outputs(cars)

    save_outputs(cars)
    print(f"\nDone: {len(cars)} cars saved to {rel(OUT_DIR)}/cars.csv ({skipped} skipped by filter)")


if __name__ == "__main__":
    main()
