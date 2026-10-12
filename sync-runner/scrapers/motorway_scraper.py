"""
Motorway Pro (pro.motorway.co.uk) stock scraper - read only, never bids.

Runs Chrome in the background (no window; use --show to watch it) using the session saved
by motorway_login.py and reads the same data the Motorway vehicle list / vehicle page load
for themselves.

Stage 1 - filter first:
  Walks Motorway's vehicle list (the daily live sale by default) and keeps only
  vehicles with mileage <= --max-mileage that were registered in --min-year or newer.
Stage 2 - fetch:
  For each vehicle that passed, saves all details (prices, spec, features, grade,
  condition & damage, HPI check, MOT, service history, keys, location, sale times)
  and downloads every photo, including damage photos.

Output (in ./export_data/motorway_export/):
  cars.csv / cars.json      one row per vehicle
  filtered_list.json        the vehicles that passed stage 1
  images/<REG>_<id>/        all photos for that vehicle
  raw/<id>.json             the full Motorway detail record, for reference

Usage:
    python scrapers/motorway_login.py                 # once, to log in and save the session
    python scrapers/motorway_scraper.py               # defaults: live sale, max 80,000 miles, 2016 or newer
    python scrapers/motorway_scraper.py --max-mileage 60000 --min-year 2018
    python scrapers/motorway_scraper.py --limit 5     # quick test on 5 vehicles
    python scrapers/motorway_scraper.py --no-images

Re-running continues where it left off (vehicles already saved are skipped).
"""

import argparse
import csv
import io
import json
import random
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from PIL import Image
from playwright.sync_api import sync_playwright

from paths import EXPORTS, SESSIONS, rel

BASE = "https://pro.motorway.co.uk"
LIST_API = "/api/vehicle/list"
SESSION_FILE = SESSIONS / "motorway_session.json"
OUT_DIR = EXPORTS / "motorway_export"
MAX_PHOTO_PX = 1280  # longest side; use --full-size to keep originals
PAGE_SIZE = 36       # vehicles per page of Motorway's list
MAX_PAGES = 1000     # safety stop

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)

FETCH_JSON = """async (u) => {
    const r = await fetch(u, {headers: {accept: 'application/json'}, credentials: 'include'});
    return [r.status, await r.text()];
}"""

# Private sellers' contact details are never saved (not needed for stock data)
SELLER_CONTACT_KEYS = {"name", "email", "mobile", "phone", "address1", "address2", "address3",
                       "latitude", "longitude"}
PERSONAL_KEYS = {"sellerDetails", "keepersList", "keepers", "keeperName"}
IMAGE_LIST_KEYS = {"images", "vehicleImages", "additionalImages", "heroImages", "previewDamageImages",
                   "wheelsAndTyresDamageImages"}


class SessionExpired(Exception):
    pass


def polite_pause(low=1.0, high=2.5):
    time.sleep(random.uniform(low, high))


def key_of(label):
    """'priceGoodCondition' / 'Price good' -> 'price_good_condition' / 'price_good'."""
    label = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(label or ""))
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")


def pick(data, *paths):
    """First non-empty value found at any of the dotted paths."""
    for path in paths:
        cur = data
        for part in path.split("."):
            cur = cur.get(part) if isinstance(cur, dict) else None
            if cur is None:
                break
        if cur not in (None, "", [], {}):
            return cur
    return None


def to_utc(value):
    """'2026-10-11T15:30:00.000+01:00' -> '2026-10-11T14:30:00Z'."""
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def uk_time(value):
    """'2026-10-11T15:30:00.000+01:00' -> 'Sun 11 Oct 15:30' (Motorway gives UK local time)."""
    try:
        return datetime.fromisoformat(str(value)).strftime("%a %d %b %H:%M")
    except ValueError:
        return str(value or "?")


def year_of(value):
    m = re.match(r"(\d{4})", str(value or ""))
    return int(m.group(1)) if m else None


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, data, indent=1):
    path.write_text(json.dumps(data, indent=indent, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------- session

def load_cookies():
    """Only the cookies - the site's saved list filters (browser storage) are left behind."""
    return {"cookies": read_json(SESSION_FILE).get("cookies", []), "origins": []}


def is_logged_in():
    """Quick check without a browser: /vehicles redirects to /signin when logged out."""
    if not SESSION_FILE.exists():
        return False
    try:
        s = requests.Session()
        for ck in load_cookies()["cookies"]:
            s.cookies.set(ck["name"], ck["value"], domain=ck["domain"], path=ck["path"])
        s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-GB,en;q=0.9"})
        r = s.get(f"{BASE}/vehicles", timeout=60, allow_redirects=False)
    except Exception:
        return False
    if r.status_code in (401, 403) or "/signin" in r.headers.get("location", ""):
        return False
    return r.status_code < 400


def still_logged_in(context):
    try:
        r = context.request.get(f"{BASE}/vehicles", max_redirects=0, timeout=60000)
    except Exception:
        return True  # network problem, not a login problem
    return r.status not in (401, 403) and "/signin" not in (r.headers.get("location") or "")


# ---------------------------------------------------------------- browser helpers

def api_get(page, context, path, retries=4):
    for attempt in range(retries):
        try:
            status, text = page.evaluate(FETCH_JSON, path)
        except Exception as e:
            print(f"  browser fetch error ({e}), retrying...")
            time.sleep(5 * (attempt + 1))
            continue
        if status in (401, 403):
            if not still_logged_in(context):
                raise SessionExpired("Motorway session expired - run `python scrapers/motorway_login.py` again.")
            raise RuntimeError(f"HTTP {status} (not allowed) for {path}")
        if status == 429:
            print("Motorway answered HTTP 429 - stopping, nothing is retried.")
            raise SystemExit(3)
        if status >= 500:
            wait = 15 * (attempt + 1)
            print(f"  HTTP {status}, waiting {wait}s...")
            time.sleep(wait)
            continue
        if status == 404:
            raise RuntimeError(f"HTTP 404 for {path}")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"Failed to fetch {path}")


def get_sale_times(page, context):
    """Motorway's daily sale window (same for every vehicle in the live sale)."""
    try:
        sale = api_get(page, context, "/api/sale")
    except SessionExpired:
        raise
    except Exception as e:
        print(f"Could not read sale times ({e})")
        return {}
    return sale if isinstance(sale, dict) else {}


def find_list_request(page, seen_requests, timeout=45):
    """Let the vehicle list page make its own list request and return that request's path.

    Re-using the page's own request keeps Motorway's query format exactly as the site sends it.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if seen_requests:
            return seen_requests[0].split(BASE, 1)[-1]
        try:
            page.mouse.wheel(0, 5000)  # scrolling loads the next page of the list
        except Exception:
            pass
        page.wait_for_timeout(1500)
    return None


def with_page(path, page_no, loaded):
    """Set page / loadedCount on a list request path, leaving the rest untouched."""
    for name, value in (("page", page_no), ("loadedCount", loaded)):
        pattern = rf"([?&]){name}=[^&]*"
        if re.search(pattern, path):
            path = re.sub(pattern, rf"\g<1>{name}={value}", path, count=1)
        else:
            path += ("&" if "?" in path else "?") + f"{name}={value}"
    return path


# ---------------------------------------------------------------- stage 1: filter

def item_year(item):
    return item.get("year") or year_of(pick(item, "spec.firstRegistered", "firstRegistered"))


def collect_filtered(page, context, list_path, args):
    kept, seen, loaded, pages = [], set(), 0, None
    counts = {"total": 0, "mileage": 0, "year": 0}

    for page_no in range(MAX_PAGES):
        data = api_get(page, context, with_page(list_path, page_no, loaded))
        if isinstance(data, dict) and isinstance(data.get("data"), dict):
            data = data["data"]
        vehicles = data.get("vehicles") or [] if isinstance(data, dict) else []
        if page_no == 0:
            total = data.get("totalCount") if isinstance(data, dict) else None
            pages = -(-total // PAGE_SIZE) if total else None
            print(f"Motorway search has {total if total is not None else '?'} vehicles "
                  f"({pages if pages else '?'} pages) - filtering...")

        new = 0
        for it in vehicles:
            vid = it.get("id")
            if vid is None or vid in seen:
                continue
            seen.add(vid)
            new += 1
            counts["total"] += 1
            if it.get("mileage") is None or it["mileage"] > args.max_mileage:
                counts["mileage"] += 1
                continue
            year = item_year(it)
            if not year or year < args.min_year:
                counts["year"] += 1
                continue
            kept.append(it)

        loaded += len(vehicles)
        print(f"  page {page_no + 1}/{max(pages, page_no + 1) if pages else '?'}: {len(kept)} vehicles match so far")
        if not vehicles or not new or not data.get("hasMore"):
            break
        polite_pause(0.8, 1.8)

    print(f"\nFilter summary: {counts['total']} checked -> removed {counts['mileage']} over "
          f"{args.max_mileage:,} miles, {counts['year']} older than {args.min_year} -> {len(kept)} kept\n")
    return kept


# ---------------------------------------------------------------- stage 2: details

def strip_personal(node, parent_key=""):
    """Remove private sellers' contact details from a Motorway record (in place)."""
    if isinstance(node, dict):
        for k in list(node):
            if k in PERSONAL_KEYS or (parent_key == "seller" and k in SELLER_CONTACT_KEYS):
                del node[k]
            else:
                strip_personal(node[k], k)
    elif isinstance(node, list):
        for v in node:
            strip_personal(v, parent_key)
    return node


def flatten(node, prefix, out):
    """Every plain value in the record as its own column (photo lists are handled separately)."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k in IMAGE_LIST_KEYS:
                continue
            flatten(v, f"{prefix}_{key_of(k)}" if prefix else key_of(k), out)
    elif isinstance(node, list):
        if not node:
            return
        if all(not isinstance(v, (dict, list)) for v in node):
            out.setdefault(prefix, " | ".join(str(v) for v in node))
        else:
            out.setdefault(prefix, json.dumps(node, ensure_ascii=False))
    elif node not in (None, ""):
        out.setdefault(prefix, node)


def image_url(img):
    if isinstance(img, str):
        return img
    if isinstance(img, dict):
        return img.get("url") or img.get("redactedUrl") or img.get("croppedUrl") or img.get("originalUrl") or ""
    return ""


def image_label(img):
    if isinstance(img, dict):
        for k in ("kind", "title", "category"):
            if isinstance(img.get(k), str) and img[k]:
                return img[k]
    return "photo"


def collect_photos(item, detail):
    """All photos in gallery order: exterior, interior, wheels/tyres, damage, seller extras."""
    images = (pick(detail, "gallery.images") or []) or (
        (detail.get("vehicleImages") or []) + (detail.get("additionalImages") or []))
    if not images:
        lead = item.get("leadPhoto") or detail.get("leadPhoto")
        images = (item.get("heroImages") or []) or ([lead] if lead else [])
    photos, seen = [], set()
    for img in images:
        url = image_url(img)
        if not url:
            continue
        url = urljoin(BASE, url)
        if url not in seen:
            seen.add(url)
            photos.append({"url": url, "label": image_label(img)})
    return photos


def sale_fields(item, sale, list_type):
    """Live fields from the list (price, bids, state) plus the sale window."""
    state = item.get("state") or {}
    car = {
        "display_price": item.get("displayPrice"),
        "highest_bid": item.get("highestBid"),
        "sale_channel": "Live sale" if list_type == "auction" else key_of(list_type).replace("_", " ").title(),
        "sale_status": state.get("name") or state.get("slug"),
        "state_slug": state.get("slug"),
    }
    if list_type == "auction" and sale:
        car.update({
            "sale_start_utc": to_utc(sale.get("todaysSaleStartedAt")),
            "sale_end_utc": to_utc(sale.get("todaysSaleEndsAt")),
            "sale_end_text": sale.get("todaysSaleEndsAt"),   # as given by Motorway (UK time)
            "next_sale_start_utc": to_utc(sale.get("nextSaleStartsAt")),
        })
    return car


def flatten_detail(item, detail, sale, list_type):
    vid = item.get("id") or detail.get("id")
    first_reg = pick(detail, "bidding.spec.firstRegistered", "spec.firstRegistered")
    car = {
        "vehicle_id": vid,
        "registration": pick(item, "prettyVrm") or pick(detail, "details.registration", "mainInfo.prettyVrm", "prettyVrm"),
        "vrm": pick(detail, "details.vrm", "bidding.vrm", "vrm"),
        "vin": pick(detail, "details.vin", "bidding.spec.vin", "spec.vin"),
        "make": pick(item, "make") or pick(detail, "mainInfo.make", "spec.make"),
        "model": pick(item, "model") or pick(detail, "mainInfo.model", "spec.model"),
        "year": item_year(item) or pick(detail, "mainInfo.year") or year_of(first_reg),
        "first_registered": first_reg,
        "mileage": item.get("mileage") if item.get("mileage") is not None else pick(detail, "mainInfo.mileage", "mileage"),
        "fuel": pick(item, "fuel") or pick(detail, "mainInfo.fuel", "spec.fuel"),
        "transmission": pick(item, "transmission") or pick(detail, "mainInfo.transmission", "spec.transmission"),
        "body_type": pick(detail, "bidding.spec.bodyCategory", "spec.bodyCategory", "gallery.bodyType"),
        "colour": pick(detail, "spec.colour", "details.colour", "mainInfo.colour"),
        "grade": pick(item, "exteriorGrade") or pick(detail, "ratings.grade", "grade"),
        "numeric_grade": pick(item, "numericGrade") or pick(detail, "ratings.numericGrade", "numericGrade"),
        "is_vat_qualifying": pick(item, "isVatQualifying") if item.get("isVatQualifying") is not None
        else pick(detail, "bidding.isVatQualifying", "isVatQualifying"),
        "price_reserve": pick(detail, "bidding.priceReserve", "sellerWillAcceptPrice") or item.get("sellerWillAcceptPrice"),
        "price_retail": pick(detail, "bidding.priceRetail", "priceRetail"),
        "price_good_condition": pick(detail, "bidding.priceGoodCondition", "priceGoodCondition"),
        "price_average_condition": pick(detail, "bidding.priceAverageCondition", "priceAverageCondition"),
        "minimum_bid": pick(detail, "bidding.minimumBid.value", "minimumBid.value"),
        "active_bid_count": pick(detail, "bidding.activeBidCount", "bids.activeBidCount"),
        "previous_owners": pick(detail, "ratings.previousOwners", "details.previousOwners.count", "previousKeepersCount"),
        "service_history": pick(detail, "ratings.serviceHistory", "serviceHistory.serviceRecord", "serviceRecord"),
        "vehicle_class": pick(detail, "spec.vehicleClass", "bidding.spec.vehicleClass"),
        "number_of_keys": pick(detail, "details.numberOfKeys", "keysCount"),
        "equipment": pick(detail, "features.equipment", "equipment"),
        "seller_type": "Trade" if (item.get("isTrade") or pick(detail, "seller.isTrade", "isTrade")) else "Private",
        "source_partner": item.get("sourcePartner") or detail.get("sourcePartner"),
        "vehicle_location": ", ".join(dict.fromkeys(str(v) for v in (
            pick(detail, "location.seller.town", "seller.town"),
            pick(detail, "location.seller.area", "seller.area")) if v)),
        "distance_miles": pick(item, "distance") or pick(detail, "location.seller.distance"),
        "url": f"{BASE}/vehicles/{vid}",
    }
    car.update(sale_fields(item, sale, list_type))

    photos = collect_photos(item, detail)
    car["photo_count"] = len(photos)
    car["photo_urls"] = " | ".join(p["url"] for p in photos)
    car["photo_labels"] = " | ".join(p["label"] for p in photos)

    # Everything else Motorway returns (condition & damage, HPI check, MOT, service history ...)
    flatten(detail, "", car)
    return car, photos


# ---------------------------------------------------------------- images

def shrink_jpeg(data):
    """Resize so the longest side is at most MAX_PHOTO_PX and re-save as JPEG (saves disk space)."""
    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
        img.thumbnail((MAX_PHOTO_PX, MAX_PHOTO_PX))
        out = io.BytesIO()
        img.save(out, "JPEG", quality=80, optimize=True, progressive=True)
        return out.getvalue() if out.tell() < len(data) else data
    except Exception:
        return data


def download_photos(context, photos, folder, full_size):
    folder.mkdir(parents=True, exist_ok=True)
    for idx, photo in enumerate(photos, 1):
        name = re.sub(r"[^a-z0-9_]+", "_", key_of(photo["label"])).strip("_") or "photo"
        path = folder / f"{idx:02d}_{name}.jpg"
        if path.exists() and path.stat().st_size > 0:
            continue
        for attempt in range(3):
            try:
                r = context.request.get(photo["url"], timeout=60000)
                if r.ok:
                    path.write_bytes(r.body() if full_size else shrink_jpeg(r.body()))
                    break
            except Exception:
                pass
            time.sleep(3 * (attempt + 1))
        else:
            print(f"  could not download {photo['url']}")


# ---------------------------------------------------------------- output

def save_outputs(cars):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_json(OUT_DIR / "cars.json", cars, indent=2)
    first = ["vehicle_id", "registration", "vin", "make", "model", "year", "first_registered", "mileage",
             "fuel", "transmission", "grade", "numeric_grade", "display_price", "highest_bid", "price_reserve",
             "price_retail", "sale_channel", "sale_status", "sale_start_utc", "sale_end_utc", "sale_end_text",
             "vehicle_location", "photo_count", "image_folder", "url"]
    keys = first + sorted({k for c in cars for k in c} - set(first))
    with open(OUT_DIR / "cars.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(cars)


def main():
    ap = argparse.ArgumentParser(description="Scrape Motorway Pro stock (read only)")
    ap.add_argument("--max-mileage", type=int, default=80000)
    ap.add_argument("--min-year", type=int, default=2016, help="oldest year to include")
    ap.add_argument("--list-type", default="auction", choices=["auction", "buyItNow", "shortlist"],
                    help="auction = the daily live sale (default)")
    ap.add_argument("--limit", type=int, default=0, help="only fetch this many vehicles (testing)")
    ap.add_argument("--no-images", action="store_true")
    ap.add_argument("--full-size", action="store_true", help="keep original photo size (uses more disk)")
    ap.add_argument("--show", action="store_true", help="show the browser window while it works")
    args = ap.parse_args()

    if not SESSION_FILE.exists():
        raise SystemExit("No saved session - run `python scrapers/motorway_login.py` first.")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Filters: {args.list_type} list, max {args.max_mileage:,} miles, {args.min_year} or newer")

    with sync_playwright() as p:
        # Motorway has no security check to complete, so no window is shown (--show to watch it)
        browser = p.chromium.launch(headless=not args.show)
        context = browser.new_context(storage_state=load_cookies(), user_agent=USER_AGENT,
                                      viewport={"width": 1366, "height": 850}, locale="en-GB")
        page = context.new_page()
        list_requests = []
        page.on("request", lambda r: list_requests.append(r.url) if LIST_API in r.url else None)

        page.goto(f"{BASE}/vehicles?listType={args.list_type}&mileageTo={args.max_mileage}", wait_until="load")
        page.wait_for_timeout(3000)
        if "/signin" in page.url:
            browser.close()
            print("Motorway session expired - run `python scrapers/motorway_login.py` again.")
            raise SystemExit(2)

        try:
            sale = get_sale_times(page, context)
        except SessionExpired as e:
            browser.close()
            print(e)
            raise SystemExit(2)
        if sale:
            print(f"Live sale is {'OPEN' if sale.get('isSaleActive') else 'CLOSED'} - today's sale ends "
                  f"{uk_time(sale.get('todaysSaleEndsAt'))}, next sale starts {uk_time(sale.get('nextSaleStartsAt'))}"
                  f" (UK time)")

        list_path = find_list_request(page, list_requests)
        if list_path is None:
            if args.list_type == "auction" and sale and not sale.get("isSaleActive"):
                browser.close()
                print(f"The live sale is closed, so there is no stock to collect right now. "
                      f"Run again after {uk_time(sale.get('nextSaleStartsAt'))} (UK time).")
                return
            # the page did not ask for its list - ask for it directly
            list_path = f"{LIST_API}?listType={args.list_type}&mileageTo={args.max_mileage}&page=0&loadedCount=0"
            print("The vehicle list page did not load its list - requesting it directly.")

        # ---- Stage 1: filter
        try:
            items = collect_filtered(page, context, list_path, args)
        except SessionExpired as e:
            browser.close()
            print(e)
            raise SystemExit(2)
        summary = [{k: it.get(k) for k in ("id", "prettyVrm", "make", "model", "year", "mileage", "displayPrice",
                                           "exteriorGrade", "fuel", "transmission")} for it in items]
        write_json(OUT_DIR / "filtered_list.json", summary)
        if args.limit:
            items = items[: args.limit]

        existing = {}
        if (OUT_DIR / "cars.json").exists():
            existing = {c["vehicle_id"]: c for c in read_json(OUT_DIR / "cars.json")}

        # ---- Stage 2: details + photos
        cars = []
        for n, item in enumerate(items, 1):
            vid = item["id"]
            car = existing.get(vid)
            if car is None:
                try:
                    detail = api_get(page, context, f"/api/vehicle?vehicleId={vid}")
                except SessionExpired as e:
                    print(e)
                    save_outputs(cars)
                    browser.close()
                    raise SystemExit(2)  # exit code 2 = session expired
                except Exception as e:
                    print(f"[{n}/{len(items)}] {item.get('prettyVrm') or vid}: failed ({e})")
                    continue
                if isinstance(detail, list):
                    detail = detail[0] if detail else {}
                strip_personal(detail)
                (OUT_DIR / "raw").mkdir(exist_ok=True)
                write_json(OUT_DIR / "raw" / f"{vid}.json", detail)
                car, photos = flatten_detail(item, detail, sale, args.list_type)
                polite_pause()
            else:
                car.update(sale_fields(item, sale, args.list_type))  # price / bids / sale times move during the sale
                urls = [u for u in car.get("photo_urls", "").split(" | ") if u]
                labels = car.get("photo_labels", "").split(" | ")
                photos = [{"url": u, "label": labels[i] if i < len(labels) and labels[i] else "photo"}
                          for i, u in enumerate(urls)]

            reg = re.sub(r"[^A-Z0-9]", "", str(car.get("registration") or "").upper())
            folder = OUT_DIR / "images" / f"{reg}_{vid}"
            car["image_folder"] = rel(folder)
            if not args.no_images:
                download_photos(context, photos, folder, args.full_size)
            cars.append(car)
            print(f"[{n}/{len(items)}] {car.get('registration')} {car.get('make')} {car.get('model')} "
                  f"{car.get('year')} {car.get('mileage')} mi - sale ends {car.get('sale_end_utc') or '-'} "
                  f"- {len(photos)} photos")
            if n % 10 == 0:
                save_outputs(cars)
                context.storage_state(path=str(SESSION_FILE))

        save_outputs(cars)
        context.storage_state(path=str(SESSION_FILE))
        browser.close()
    print(f"\nDone: {len(cars)} vehicles saved to {rel(OUT_DIR)}/cars.csv")


if __name__ == "__main__":
    main()
