"""
BCA (bca.co.uk) stock scraper - read only, never bids.

BCA protects its site with Cloudflare, so this needs a normal (not headless) Chrome,
using the session saved by bca_login.py. The window is kept minimised so the work
happens in the background; use --show to watch it. If BCA shows a security check, the
window comes forward and the script waits for YOU to complete it, then it minimises again.

Stage 1 - filter first:
  Walks BCA's vehicle search and keeps only vehicles that
    - are in an auction sale (online e-Auction or live bidding), not Buy Now / Bid Now
    - have a sale date within the next 7 days (or are live right now)
    - have mileage <= --max-mileage and are registered in --min-year or newer
Stage 2 - fetch:
  For each vehicle that passed, saves all details (CAP prices, spec, equipment,
  condition report, tyres, service history, MOT, keys, declarations, sale/lot info)
  and downloads every photo.

Output (in ./export_data/bca_export/):
  cars.csv / cars.json      one row per vehicle
  filtered_list.json        the vehicles that passed stage 1
  images/<REG>/             all photos for that vehicle
  raw/<REG>.json            the full BCA detail record, for reference

Usage:
    python scrapers/bca_login.py                 # once, to log in and save the session
    python scrapers/bca_scraper.py               # defaults: 7 days, max 80,000 miles, 2016 or newer
    python scrapers/bca_scraper.py --days 3 --max-mileage 60000 --min-year 2018
    python scrapers/bca_scraper.py --limit 5     # quick test on 5 vehicles
    python scrapers/bca_scraper.py --no-images

Re-running continues where it left off (vehicles already saved are skipped).
"""

import argparse
import csv
import io
import json
import random
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from PIL import Image
from playwright.sync_api import sync_playwright

from paths import EXPORTS, SESSIONS, rel

BASE = "https://www.bca.co.uk"
SESSION_FILE = SESSIONS / "bca_session.json"
OUT_DIR = EXPORTS / "bca_export"
PAGE_SIZE = 200
AUCTION_CHANNELS = {"InternetAuction", "LiveOnline"}  # e-Auction + live bidding (not FixedPrice/Tender)

FETCH_JSON = """async (u) => {
    const r = await fetch(u, {headers: {accept: 'application/json'}, credentials: 'include'});
    return [r.status, await r.text()];
}"""


# keep the page working at full speed while its window is minimised
BACKGROUND_ARGS = ["--disable-background-timer-throttling", "--disable-renderer-backgrounding",
                   "--disable-backgrounding-occluded-windows"]
IN_BACKGROUND = True  # --show turns this off


class SessionExpired(Exception):
    pass


def set_window(page, state):
    """'minimized' keeps the browser out of the way; 'normal' brings it back (for a security check)."""
    try:
        cdp = page.context.new_cdp_session(page)
        window = cdp.send("Browser.getWindowForTarget")
        cdp.send("Browser.setWindowBounds", {"windowId": window["windowId"], "bounds": {"windowState": state}})
        cdp.detach()
    except Exception:
        pass  # only cosmetic: the scrape works the same with the window visible


def polite_pause(low=1.0, high=2.5):
    time.sleep(random.uniform(low, high))


def money(text):
    m = re.search(r"£\s*([\d,]+)", text or "")
    return int(m.group(1).replace(",", "")) if m else None


def key_of(label):
    return re.sub(r"[^a-z0-9]+", "_", (label or "").lower()).strip("_")


def parse_date(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def reg_year(item):
    m = re.match(r"(\d{4})", item.get("plate") or "")
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------- browser helpers

def wait_for_security_check(page, timeout=600):
    """If Cloudflare shows a check, wait for the user to complete it in the window."""
    deadline = time.time() + timeout
    warned = False
    while time.time() < deadline:
        title = page.title()
        if "Just a moment" not in title and "security check" not in page.content()[:5000].lower():
            if warned and IN_BACKGROUND:
                set_window(page, "minimized")
            return
        if not warned:
            print(">> BCA is showing a security check - please complete it in the browser window. Waiting...")
            warned = True
            set_window(page, "normal")  # a person has to see it
        time.sleep(3)
    raise RuntimeError("Security check was not completed in time.")


def api_get(page, path, retries=4):
    for attempt in range(retries):
        try:
            status, text = page.evaluate(FETCH_JSON, path)
        except Exception as e:
            print(f"  browser fetch error ({e}), retrying...")
            time.sleep(5 * (attempt + 1))
            continue
        if status in (401, 403):
            # could be Cloudflare re-checking or the login expiring
            page.reload(wait_until="load")
            wait_for_security_check(page)
            if not logged_in(page):
                raise SessionExpired("BCA session expired - run `python scrapers/bca_login.py` again.")
            continue
        if status == 429:
            print("BCA answered HTTP 429 - stopping, nothing is retried.")
            raise SystemExit(3)
        if status >= 500:
            wait = 15 * (attempt + 1)
            print(f"  HTTP {status}, waiting {wait}s...")
            time.sleep(wait)
            continue
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            wait_for_security_check(page)
            continue
    raise RuntimeError(f"Failed to fetch {path}")


def logged_in(page):
    try:
        status, text = page.evaluate(FETCH_JSON, "/api/bff/search/me")
        return status == 200 and json.loads(text).get("loggedIn") is True
    except Exception:
        return False


# ---------------------------------------------------------------- stage 1: filter

def collect_filtered(page, args):
    now = datetime.now(timezone.utc)
    until = now + timedelta(days=args.days)
    bq = "|".join(f"VehicleType:{t}" for t in args.types.split(","))
    kept, seen, page_no, pages = [], set(), 1, None
    counts = {"total": 0, "channel": 0, "date": 0, "mileage": 0, "year": 0}

    while True:
        url = (f"/api/bff/search/proxy/search?q=&bq={quote(bq)}"
               f"&pageSize={PAGE_SIZE}&page={page_no}&sort=SaleDate")
        data = api_get(page, url)
        pages = pages or data.get("numberOfPages") or 1
        if page_no == 1:
            print(f"BCA search has {data.get('totalResults')} vehicles ({pages} pages) - filtering...")

        for it in data.get("items", []):
            vrm = it.get("vrm")
            if not vrm or vrm in seen:
                continue
            seen.add(vrm)
            counts["total"] += 1
            if it.get("saleChannel") not in AUCTION_CHANNELS:
                counts["channel"] += 1
                continue
            start, end = parse_date(it.get("saleDate")), parse_date(it.get("saleEndDate"))
            live_now = start and end and start <= now <= end
            if not (live_now or (start and now <= start <= until)):
                counts["date"] += 1
                continue
            if it.get("mileage") is None or it["mileage"] > args.max_mileage:
                counts["mileage"] += 1
                continue
            year = reg_year(it)
            if not year or year < args.min_year:
                counts["year"] += 1
                continue
            kept.append(it)

        print(f"  page {page_no}/{pages}: {len(kept)} vehicles match so far")
        starts = [d for d in (parse_date(it.get("saleDate")) for it in data.get("items", [])) if d]
        if starts and min(starts) > until:
            print(f"  every sale on this page is more than {args.days} days away - not reading the later pages")
            break
        if page_no >= pages:
            break
        page_no += 1
        polite_pause(0.8, 1.8)

    print(f"\nFilter summary: {counts['total']} checked -> removed {counts['channel']} not auction/live, "
          f"{counts['date']} outside {args.days} days, {counts['mileage']} over {args.max_mileage:,} miles, "
          f"{counts['year']} older than {args.min_year} -> {len(kept)} kept\n")
    return kept


# ---------------------------------------------------------------- stage 2: details

def flatten_detail(item, detail):
    vd = detail.get("vehicleDetails") or {}
    sd = detail.get("saleDetails") or {}
    ld = detail.get("lotDetails") or {}
    car = {
        "registration": item.get("vrm"),
        "vin": vd.get("vin") or item.get("vin"),
        "make": item.get("make"),
        "model": item.get("model"),
        "derivative": item.get("derivative"),
        "description": item.get("primaryVehicleDescription"),
        "plate": item.get("plate"),
        "year": reg_year(item),
        "mileage": item.get("mileage"),
        "mileage_warranted": item.get("mileageWarranted"),
        "cap_clean": item.get("capCleanPrice"),
        "grade": item.get("grade"),
        "mechanical_grade": item.get("mechanicalGrade"),
        "fuel": item.get("fuelType"),
        "transmission": item.get("transmission"),
        "body_type": item.get("bodyType"),
        "engine_size": item.get("engineCapacity"),
        "doors": item.get("numberOfDoors"),
        "owners": item.get("numberOfOwners"),
        "colour": item.get("manufacturerColour"),
        "v5": item.get("logBookStatusIndicator"),
        "service_history": item.get("serviceHistoryType"),
        "vat": item.get("vatType"),
        "non_runner": item.get("nonRunner"),
        "sale_channel": item.get("saleChannel"),
        "sale_channel_tags": ", ".join(item.get("saleChannelTags") or []),
        "sale_date": item.get("saleDate"),
        "sale_end_date": item.get("saleEndDate"),
        "sale_type": item.get("saleType"),
        "sale_location": item.get("saleLocation"),
        "vehicle_location": item.get("localSaleLocation"),
        "lot_number": item.get("lotNumber"),
        "sale_code": item.get("saleCode"),
        "sale_status": sd.get("saleStatus"),
        "lots_in_sale": sd.get("numberOfLotsTotal"),
        "url": f"{BASE}/lot/{(item.get('vrm') or '').replace(' ', '')}",
    }
    # Every price shown (CAP clean / average / below / retail, guide price ...)
    for p in vd.get("priceItems") or []:
        car[f"price_{key_of(p.get('invariantKey') or p.get('label'))}"] = money(p.get("information")) \
            if money(p.get("information")) is not None else p.get("information")
    # Description items (owners, keys, colour, ... as BCA labels them)
    for d in vd.get("vehicleDescriptionItems") or []:
        car.setdefault(key_of(d.get("label")), d.get("information"))
    for k, v in ((vd.get("significantFields") or {}).get("fields") or {}).items():
        car.setdefault(key_of(k), v)

    car["equipment"] = vd.get("equipment")
    sh = vd.get("serviceHistory") or {}
    last = sh.get("lastService") or {}
    car["service_history_status"] = sh.get("status")
    car["services_total"] = (sh.get("serviceCount") or {}).get("total")
    car["services_main_dealer"] = (sh.get("serviceCount") or {}).get("mainDealer")
    car["last_service_date"] = (last.get("date") or "")[:10]
    car["last_service_mileage"] = last.get("mileage")

    ai = vd.get("additionalInformation") or {}
    car["number_of_keys"] = ai.get("numberOfKeys")
    car["mot_expiry"] = ((ai.get("mot") or {}).get("expiryDate") or "")[:10]
    car["co2"] = (ai.get("emissions") or {}).get("cO2")
    car["mot_advisories"] = " | ".join(str(a) for a in ai.get("advisoryItems") or [])
    car["dvsa_mileage_history"] = " | ".join(
        f"{(e.get('completedDate') or '')[:10]}: {e.get('mileage')}" for e in ai.get("dvsaMileageEntries") or [])

    decl = vd.get("declaration") or {}
    for k in ("majorDamage", "ownedByPolice", "usedAsTaxi", "reregistered", "modifiedVehicle", "salvagedVehicle"):
        car[f"declared_{key_of(k)}"] = decl.get(k)
    car["insurance_total_loss"] = json.dumps(vd.get("insuranceTotalLoss") or [])

    asm = vd.get("assessment") or {}
    car["condition_summary"] = " | ".join(
        f"{c.get('reportType')} {c.get('severityType')}: {c.get('numberOfItems')}" for c in asm.get("conditionSummaries") or [])
    car["condition_report"] = " | ".join(
        f"{cat.get('name')} [{cat.get('severityCode')}]: " + ", ".join(
            f"{comp.get('name')}={comp.get('severityCode')}" for comp in cat.get("components") or [])
        for cat in asm.get("reportCategories") or [])
    tyres = (asm.get("tyreCategory") or {}).get("components") or []
    car["tyres"] = " | ".join(
        f"{t.get('name')}: {((t.get('treadDepth') or {}).get('middle'))}mm {t.get('severityCode')}" for t in tyres)
    car["condition_notes"] = " | ".join(str(n) for n in asm.get("notes") or [])
    for r in vd.get("reportUrls") or item.get("reportUrls") or []:
        car[f"{key_of(r.get('rel'))}"] = r.get("href")

    photos = []
    for img in ld.get("images") or item.get("images") or []:
        uri = img.get("imageURI") or ""
        if "docId=" in uri:
            photos.append(re.sub(r"&?width=\d+", "", uri))
    car["photo_count"] = len(photos)
    car["photo_urls"] = " | ".join(photos)
    return car, photos


def shrink_jpeg(data):
    """Re-save as a lighter JPEG (BCA's 1280px photos are ~400 KB each)."""
    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
        img.thumbnail((1280, 1280))
        out = io.BytesIO()
        img.save(out, "JPEG", quality=80, optimize=True, progressive=True)
        return out.getvalue() if out.tell() < len(data) else data
    except Exception:
        return data


def download_photos(context, photos, folder, full_size):
    folder.mkdir(parents=True, exist_ok=True)
    for idx, url in enumerate(photos, 1):
        path = folder / f"{idx:02d}.jpg"
        if path.exists() and path.stat().st_size > 0:
            continue
        src = url if full_size else url + "&width=1280"
        for attempt in range(3):
            try:
                r = context.request.get(src, timeout=60000)
                if r.ok:
                    path.write_bytes(r.body() if full_size else shrink_jpeg(r.body()))
                    break
            except Exception:
                pass
            time.sleep(3 * (attempt + 1))
        else:
            print(f"  could not download {src}")


# ---------------------------------------------------------------- output

def save_outputs(cars):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "cars.json").write_text(json.dumps(cars, indent=2, ensure_ascii=False))
    first = ["registration", "vin", "description", "make", "model", "derivative", "year", "plate", "mileage",
             "cap_clean", "grade", "sale_channel", "sale_date", "sale_end_date", "sale_type",
             "vehicle_location", "lot_number", "photo_count", "image_folder", "url"]
    keys = first + sorted({k for c in cars for k in c} - set(first))
    with open(OUT_DIR / "cars.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(cars)


def main():
    ap = argparse.ArgumentParser(description="Scrape BCA auction stock (read only)")
    ap.add_argument("--days", type=int, default=7, help="sales within this many days")
    ap.add_argument("--max-mileage", type=int, default=80000)
    ap.add_argument("--min-year", type=int, default=2016)
    ap.add_argument("--types", default="Cars", help="BCA vehicle types, comma separated (e.g. Cars,LCV)")
    ap.add_argument("--limit", type=int, default=0, help="only fetch this many vehicles (testing)")
    ap.add_argument("--no-images", action="store_true")
    ap.add_argument("--full-size", action="store_true", help="keep original photo size (~1.5x more disk)")
    ap.add_argument("--show", action="store_true", help="keep the browser window visible while it works")
    args = ap.parse_args()
    global IN_BACKGROUND
    IN_BACKGROUND = not args.show

    if not SESSION_FILE.exists():
        raise SystemExit("No saved session - run `python scrapers/bca_login.py` first.")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Filters: auction + live bidding, next {args.days} days, max {args.max_mileage:,} miles, "
          f"{args.min_year} or newer, types: {args.types}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=BACKGROUND_ARGS)
        context = browser.new_context(storage_state=str(SESSION_FILE),
                                      viewport={"width": 1366, "height": 850}, locale="en-GB")
        page = context.new_page()
        if IN_BACKGROUND:
            set_window(page, "minimized")
        page.goto(f"{BASE}/search?q=&bq=VehicleType%3ACars", wait_until="load")
        wait_for_security_check(page)
        page.wait_for_timeout(4000)
        if not logged_in(page):
            browser.close()
            print("BCA session expired - run `python scrapers/bca_login.py` again.")
            raise SystemExit(2)

        # ---- Stage 1: filter
        items = collect_filtered(page, args)
        summary = [{k: it.get(k) for k in ("vrm", "primaryVehicleDescription", "plate", "mileage", "capCleanPrice",
                                           "saleChannel", "saleDate", "localSaleLocation", "lotNumber")}
                   for it in items]
        (OUT_DIR / "filtered_list.json").write_text(json.dumps(summary, indent=1))
        if args.limit:
            items = items[: args.limit]

        existing = {}
        if (OUT_DIR / "cars.json").exists():
            existing = {c["registration"]: c for c in json.loads((OUT_DIR / "cars.json").read_text())}

        # ---- Stage 2: details + photos
        cars = []
        for n, item in enumerate(items, 1):
            vrm = item["vrm"]
            car = existing.get(vrm)
            if car is None:
                try:
                    detail = api_get(page, f"/api/bff/lot/proxy/buyer/inventorydetail/{quote(vrm.replace(' ', ''))}?")
                except SessionExpired as e:
                    print(e)
                    save_outputs(cars)
                    browser.close()
                    raise SystemExit(2)  # exit code 2 = session expired
                except Exception as e:
                    print(f"[{n}/{len(items)}] {vrm}: failed ({e})")
                    continue
                (OUT_DIR / "raw").mkdir(exist_ok=True)
                (OUT_DIR / "raw" / f"{vrm.replace(' ', '')}.json").write_text(json.dumps(detail, indent=1))
                car, photos = flatten_detail(item, detail)
                polite_pause()
            else:
                photos = [u for u in car.get("photo_urls", "").split(" | ") if u]

            folder = OUT_DIR / "images" / vrm.replace(" ", "")
            car["image_folder"] = rel(folder)
            if not args.no_images:
                download_photos(context, photos, folder, args.full_size)
            cars.append(car)
            print(f"[{n}/{len(items)}] {vrm} {car.get('description')} {car.get('year')} "
                  f"{car.get('mileage')} mi - sale {(car.get('sale_date') or '')[:10]} - {len(photos)} photos")
            if n % 10 == 0:
                save_outputs(cars)
                context.storage_state(path=str(SESSION_FILE))

        save_outputs(cars)
        context.storage_state(path=str(SESSION_FILE))
        browser.close()
    print(f"\nDone: {len(cars)} vehicles saved to {rel(OUT_DIR)}/cars.csv")


if __name__ == "__main__":
    main()
