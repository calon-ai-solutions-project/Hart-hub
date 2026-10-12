"""
Manheim UK stock scraper.

Uses the logged-in session saved by manheim_login.py (manheim_session.json),
applies the search filters, then for every matching vehicle saves:
  - all vehicle details (vehicle info, CAP clean/average/retail, specification,
    sale/event info, vendor, inspection & service history, grade ...)
  - every photo in full ("zoom") size, including damage photos
  - the inspection report PDF link (download the PDFs too with --with-pdf)

Output (in ./export_data/manheim_export/):
  cars.csv / cars.json          one row per vehicle
  images/<REG>_<id>/            photos + inspection_report.pdf
  raw/<id>.html                 the original vehicle page, for reference

Usage:
    python scrapers/manheim_login.py              # once, to log in and save the session
    python scrapers/manheim_scraper.py            # defaults: max 80,000 miles, 2016 or newer
    python scrapers/manheim_scraper.py --limit 5  # quick test on 5 vehicles
    python scrapers/manheim_scraper.py --no-images

Re-running continues where it left off (vehicles already saved are skipped).
"""

import argparse
import csv
import html as htmllib
import json
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import io

import requests
from bs4 import BeautifulSoup
from PIL import Image

from paths import EXPORTS, SESSIONS, rel

BASE = "https://www.manheim.co.uk"
SEARCH_URL = f"{BASE}/search"
SESSION_FILE = SESSIONS / "manheim_session.json"
OUT_DIR = EXPORTS / "manheim_export"
PAGE_SIZE = 90
MAX_PHOTO_PX = 1280  # longest side; use --full-size to keep originals
FULL_SIZE = False

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


def key_of(label):
    return re.sub(r"[^a-z0-9]+", "_", clean(label).lower()).strip("_")


def money(text):
    m = re.search(r"£\s*([\d,]+)", text or "")
    return int(m.group(1).replace(",", "")) if m else None


def make_session():
    if not SESSION_FILE.exists():
        raise SystemExit("No saved session - run `python scrapers/manheim_login.py` first.")
    state = json.loads(SESSION_FILE.read_text())
    s = requests.Session()
    for ck in state["cookies"]:
        s.cookies.set(ck["name"], ck["value"], domain=ck["domain"], path=ck["path"])
    s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-GB,en;q=0.9",
                      "Accept-Encoding": "identity"})  # avoids broken-gzip errors
    return s


def get(session, url, check_login=True, **kwargs):
    for attempt in range(4):
        try:
            r = session.get(url, timeout=60, **kwargs)
        except requests.RequestException as e:
            print(f"  network error ({e}), retrying...")
            time.sleep(5 * (attempt + 1))
            continue
        if "/Account/LogIn" in r.url:
            raise SessionExpired("Session expired - run `python scrapers/manheim_login.py` again.")
        if r.status_code in (403, 429):
            print(f"Manheim answered HTTP {r.status_code} - stopping, nothing is retried.")
            raise SystemExit(3)
        if r.status_code >= 500:
            wait = 15 * (attempt + 1)
            print(f"  HTTP {r.status_code}, waiting {wait}s...")
            time.sleep(wait)
            continue
        r.raise_for_status()
        if check_login and "text/html" in r.headers.get("content-type", "") and "/logout" not in r.text.lower():
            raise SessionExpired("Not logged in - run `python scrapers/manheim_login.py` again.")
        return r
    raise RuntimeError(f"Failed to fetch {url}")


def is_logged_in():
    try:
        get(make_session(), f"{BASE}/mymanheim/dashboard")
        return True
    except (SessionExpired, SystemExit):
        return False


# ---------------------------------------------------------------- vehicle ids

def collect_vehicle_ids(session, filters):
    ids, page, total, pages = [], 1, None, None
    while True:
        r = get(session, SEARCH_URL, params={**filters, "Page": page, "PageSize": PAGE_SIZE})
        if page == 1:
            m = re.search(r"<b>(\d+)</b> results found", r.text)
            total = int(m.group(1)) if m else None
            pages = -(-total // PAGE_SIZE) if total else None
            print(f"Manheim search has {total if total is not None else '?'} vehicles "
                  f"({pages if pages else '?'} pages) - collecting...")
        found = {}
        for m in re.finditer(r'href="(/vehicle-detail/[^"?]+)\?id=(\d+)', r.text):
            found.setdefault(m.group(2), m.group(1))
        new = [(i, path) for i, path in found.items() if i not in dict(ids)]
        if not new:
            break
        ids.extend(new)
        print(f"  page {page}/{max(pages, page) if pages else '?'}: {len(ids)} vehicles found so far")
        if total and len(ids) >= total:
            break
        page += 1
        polite_pause(0.8, 1.6)
    return ids


# ---------------------------------------------------------------- detail page

def ms_date(value):
    """'/Date(1791932340000)/' -> '2026-10-13T22:59:00Z' (UTC)."""
    m = re.search(r"(\d{10,})", str(value or ""))
    if not m:
        return ""
    return datetime.fromtimestamp(int(m.group(1)) / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_sale_timing(html):
    """Sale channel, start and END time from the page's bidding widget data (read only)."""
    m = re.search(r'class="bidding-widget-container[^"]*"[^>]*data-model="([^"]+)"', html)
    if not m:
        if "isn't currently allocated to a sale" in html:
            return {"sale_status": "Preview stock - not in a sale yet"}
        return {"sale_status": "Unknown"}
    try:
        model = json.loads(htmllib.unescape(htmllib.unescape(m.group(1))))
    except ValueError:
        return {"sale_status": "Unknown"}
    sales = (model.get("OnlineSales") or []) + (model.get("InLaneSales") or [])
    sale = sales[0] if sales else {}
    info = model.get("BidInfo") or {}
    return {
        "sale_status": "Online auction" if model.get("OnlineSales") else "In-lane / Simulcast auction",
        "sale_channel_name": sale.get("ChannelName") or info.get("SalesChannelName"),
        "sale_event_name": sale.get("EventName") or info.get("SaleEventName"),
        "sale_location": sale.get("LocationName") or info.get("Location"),
        "sale_start_utc": ms_date(sale.get("Start") or info.get("Start")),
        "sale_end_utc": ms_date(sale.get("End") or info.get("End")),
        "sale_start_text": model.get("StartDateString"),   # as shown on Manheim (UK time)
        "sale_end_text": model.get("EndDateString"),       # as shown on Manheim (UK time)
        "lot_number": info.get("LotNumber"),
        "is_buy_now": info.get("IsBuyNow"),
        "buy_now_price": info.get("BuyNowPrice") or None,
        "current_bid": info.get("CurrentPrice"),
        "number_of_bids": info.get("NumberOfBids"),
        "has_reserve": info.get("HasReserve"),
        "reserve_met": info.get("ReserveMet"),
    }


def parse_vehicle(html, vehicle_id, url):
    soup = BeautifulSoup(html, "html.parser")
    car = {"vehicle_id": vehicle_id, "url": url}

    title = soup.select_one(".vehicle-details__title")
    car["title"] = clean(title.get_text(" ")) if title else ""
    subtitle = title.find_next() if title else None
    car["summary"] = clean(subtitle.get_text(" ")) if subtitle else ""

    seen_blocks = set()
    for block in soup.select(".vdb"):
        head = block.select_one(".vdb__title")
        name = clean(head.get_text()) if head else ""
        items = block.select(".vdb__item")
        sig = (name.lower(), len(items), clean(block.get_text())[:200])
        if sig in seen_blocks:
            continue
        seen_blocks.add(sig)

        for it in items:
            label, value = it.select_one(".vdb__label"), it.select_one(".vdb__value")
            if not label:
                continue
            k = key_of(label.get_text())
            if len(k) > 40:  # long notices (e.g. buyer fees text)
                k = "buyer_fees_note"
            link = value.find("a", href=True) if value else None
            if link and link["href"].lower().endswith(".pdf"):
                car.setdefault(k + "_url", link["href"])
                continue
            car.setdefault(k, clean((value or it).get_text(" ")))

        if not items and name:
            body = clean(block.get_text(" ").replace(name, "", 1))
            lname = name.lower()
            if "specification" in lname:
                feats = [clean(li.get_text()) for li in block.select("li")] or [body]
                car.setdefault("specification", " | ".join(f for f in feats if f))
            elif "service history" in lname:
                rows = [" / ".join(clean(td.get_text()) for td in tr.select("td"))
                        for tr in block.select("tr") if tr.select("td")]
                car.setdefault("service_history", " | ".join(rows) or body)
            elif "certification" in lname:
                car.setdefault("certifications", body)
            elif body:
                car[key_of(name)] = (car.get(key_of(name), "") + " " + body).strip()

    # Event / lot info box ("In Lane Buying", online auction etc.)
    for hdr in soup.select(".block__header"):
        box = hdr.parent
        car.setdefault("sale_" + key_of(hdr.get_text()), clean(box.get_text(" ")).replace(
            clean(hdr.get_text()), "", 1).replace("Add this event to my calendar", "").strip())

    # Normalised core fields
    car["registration"] = car.get("reg_no", "")
    car["auction_centre"] = car.get("auction_centre", "").lstrip("( ").rstrip(") ")
    m = re.search(r"([\d,]+)\s*(Miles|Km)", car.get("odometer", ""), re.I)
    car["mileage"] = int(m.group(1).replace(",", "")) if m else None
    car["year"] = int(car["mfr_year"]) if car.get("mfr_year", "").isdigit() else None
    for k in ("cap_clean", "cap_average", "cap_retail", "cap_below"):
        if k in car:
            car[k] = money(car[k])

    # Sale timing - start and END time of the sale this vehicle is in
    car.update(parse_sale_timing(html))

    # Photos (full-size "zoom" images), in gallery order
    photos, seen = [], set()
    for a in soup.select("a[imagehigh]"):
        src = a["imagehigh"].replace("http://", "https://")
        if src not in seen:
            seen.add(src)
            photos.append({"url": src, "label": a.get("title") or "photo"})
    car["photo_count"] = len(photos)
    car["photo_urls"] = " | ".join(p["url"] for p in photos)
    return car, photos


# ---------------------------------------------------------------- images

def shrink_jpeg(data):
    """Resize so the longest side is at most MAX_PHOTO_PX and re-save as JPEG (saves disk space)."""
    try:
        img = Image.open(io.BytesIO(data))
        img = img.convert("RGB")
        img.thumbnail((MAX_PHOTO_PX, MAX_PHOTO_PX))
        out = io.BytesIO()
        img.save(out, "JPEG", quality=80, optimize=True, progressive=True)
        return out.getvalue() if out.tell() < len(data) else data
    except Exception:
        return data


def download_files(files, folder):
    def one(item):
        idx, f = item
        name = re.sub(r"[^a-z0-9_]+", "_", f["label"].lower()).strip("_") or "photo"
        ext = ".pdf" if f["url"].lower().endswith(".pdf") else ".jpg"
        path = folder / (f"{idx:02d}_{name}{ext}" if idx else f"{name}{ext}")
        if path.exists() and path.stat().st_size > 0:
            return
        for attempt in range(3):
            try:
                r = requests.get(f["url"], timeout=60, headers={"User-Agent": USER_AGENT})
                if r.status_code == 404 and f["url"].startswith("https://"):
                    r = requests.get(f["url"].replace("https://", "http://"), timeout=60,
                                     headers={"User-Agent": USER_AGENT})
                r.raise_for_status()
                path.parent.mkdir(parents=True, exist_ok=True)
                if ext == ".jpg" and not FULL_SIZE:
                    path.write_bytes(shrink_jpeg(r.content))
                else:
                    path.write_bytes(r.content)
                return
            except requests.RequestException:
                time.sleep(3 * (attempt + 1))
        print(f"  could not download {f['url']}")

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(one, files))


# ---------------------------------------------------------------- output

def save_outputs(cars):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "cars.json").write_text(json.dumps(cars, indent=2, ensure_ascii=False))
    first = ["vehicle_id", "registration", "title", "summary", "year", "reg_date", "mileage",
             "cap_clean", "cap_average", "cap_retail", "grade", "sale_status", "sale_start_utc", "sale_end_utc",
             "sale_end_text", "auction_centre", "sales_channel",
             "vendor", "photo_count", "image_folder", "url"]
    keys = first + sorted({k for c in cars for k in c} - set(first))
    with open(OUT_DIR / "cars.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(cars)


def main():
    ap = argparse.ArgumentParser(description="Scrape Manheim UK stock")
    ap.add_argument("--max-mileage", type=int, default=80000)
    ap.add_argument("--min-year", type=int, default=2016, help="oldest year to include")
    ap.add_argument("--limit", type=int, default=0, help="only scrape this many vehicles (testing)")
    ap.add_argument("--no-images", action="store_true")
    ap.add_argument("--with-pdf", action="store_true", help="also download inspection report PDFs (~4 MB each)")
    ap.add_argument("--full-size", action="store_true", help="keep original photo size (uses ~3x more disk)")
    args = ap.parse_args()
    global FULL_SIZE
    FULL_SIZE = args.full_size

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session = make_session()

    filters = {
        "IsKm": "False",
        "RegistrationYear.Start": str(args.min_year),
        "OdometerMiles.Start": "0",
        "OdometerMiles.End": str(args.max_mileage),
    }
    print(f"Filters: max {args.max_mileage:,} miles, {args.min_year} or newer")
    try:
        ids = collect_vehicle_ids(session, filters)
    except SessionExpired as e:
        print(e)
        raise SystemExit(2)  # exit code 2 = session expired
    if args.limit:
        ids = ids[: args.limit]
    print(f"\nFetching details and photos for {len(ids)} vehicles...\n")

    existing = {}
    if (OUT_DIR / "cars.json").exists():
        existing = {c["vehicle_id"]: c for c in json.loads((OUT_DIR / "cars.json").read_text())}

    cars, skipped = [], 0
    for n, (vid, path) in enumerate(ids, 1):
        car = existing.get(vid)
        if car is None:
            url = f"{BASE}{path}?id={vid}"
            try:
                html = get(session, url).text
            except SessionExpired as e:
                print(e)
                save_outputs(cars)
                raise SystemExit(2)  # exit code 2 = session expired
            except Exception as e:
                print(f"[{n}/{len(ids)}] {vid}: failed ({e})")
                continue
            (OUT_DIR / "raw").mkdir(parents=True, exist_ok=True)
            (OUT_DIR / "raw" / f"{vid}.html").write_text(html)
            car, photos = parse_vehicle(html, vid, url)
            polite_pause()
        else:
            photos = [{"url": u, "label": "photo"} for u in car.get("photo_urls", "").split(" | ") if u]

        if (car.get("mileage") or 0) > args.max_mileage or (car.get("year") and car["year"] < args.min_year):
            skipped += 1
            print(f"[{n}/{len(ids)}] {car.get('registration')} skipped ({car.get('year')}, {car.get('mileage')} miles)")
            continue

        folder = OUT_DIR / "images" / f"{re.sub(r'[^A-Z0-9]', '', car.get('registration', '').upper())}_{vid}"
        car["image_folder"] = rel(folder)
        if not args.no_images:
            files = list(enumerate(photos, 1))
            if args.with_pdf and car.get("inspection_report_url"):
                files.append((0, {"url": car["inspection_report_url"], "label": "inspection_report"}))
            download_files(files, folder)
        cars.append(car)
        print(f"[{n}/{len(ids)}] {car.get('registration')} {car.get('title')} "
              f"{car.get('year')} {car.get('mileage')} mi - {len(photos)} photos")

        if n % 10 == 0:
            save_outputs(cars)

    save_outputs(cars)
    print(f"\nDone: {len(cars)} vehicles saved to {rel(OUT_DIR)}/cars.csv ({skipped} skipped by filter)")


if __name__ == "__main__":
    main()
