"""Allowlist collectors: one per platform, used by run_sync.py.

Each collector opens ONLY the listing URLs it is given (the run's allowlist), one at a time, through
the sync guard, and re-uses the parsing code of the matching <site>_scraper.py. Nothing here walks
a platform's search, logs in, retries a block or waits out a security check.

A collector yields one result per URL:
    {"url", "outcome": "captured" | "failed", "record", "folder", "http_status", "detail"}
and raises PlatformStop / SessionLoggedOut (with `.url` set) when the run must end.
"""

import json
import re
from urllib.parse import parse_qs, urlsplit

import bca_scraper as bca
import carwow_scraper as cw
import manheim_scraper as mh
import motorway_scraper as mw
from guard import PlatformStop, SessionLoggedOut
from paths import rel


def failed(url, detail, http_status=None):
    return {"url": url, "outcome": "failed", "record": None, "folder": None,
            "http_status": http_status, "detail": str(detail)[:255]}


def captured(url, record, folder, http_status=200):
    return {"url": url, "outcome": "captured", "record": record, "folder": folder,
            "http_status": http_status, "detail": ""}


def reg_key(registration):
    return re.sub(r"[^A-Z0-9]", "", str(registration or "").upper())


def tagged(url, collect_one):
    """Run one URL's collection, attaching the URL to a stop so the run log shows where it happened."""
    try:
        return collect_one()
    except (PlatformStop, SessionLoggedOut) as e:
        e.url = url
        raise
    except Exception as e:  # one bad page must not lose the rest of the run
        return failed(url, f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------- records (no network: testable)

def carwow_record(url, html, fragments):
    listing_id = urlsplit(url).path.rstrip("/").rsplit("/", 1)[1]
    car, photos = cw.parse_listing(html, fragments, listing_id)
    car["url"] = url
    return car, photos


def manheim_record(url, html):
    vehicle_id = parse_qs(urlsplit(url).query)["id"][0]
    return mh.parse_vehicle(html, vehicle_id, url)


def bca_record(url, detail):
    """BCA's detail record carries what the search row would have: rebuild that row from it."""
    vd = detail.get("vehicleDetails") or {}
    sd = detail.get("saleDetails") or {}
    ld = detail.get("lotDetails") or {}
    fields = (vd.get("significantFields") or {}).get("fields") or {}
    labels = {d.get("invariantKey"): d.get("information") for d in vd.get("vehicleDescriptionItems") or []}
    year = re.search(r"(19|20)\d{2}", str(fields.get("DateRegistered") or labels.get("DateRegistered") or ""))
    mileage = re.search(r"\d[\d,]*", str(labels.get("Mileage") or ""))  # as BCA shows it on the lot
    odometer = ((vd.get("assessment") or {}).get("odometer") or {}).get("reading")
    item = {
        "vrm": vd.get("vrm"),
        "vin": vd.get("vin"),
        "make": vd.get("make") or fields.get("Make"),
        "model": vd.get("model") or fields.get("Model"),
        "derivative": fields.get("Derivative"),
        "primaryVehicleDescription": labels.get("VehicleDescription"),
        "plate": year.group() if year else None,
        "mileage": int(mileage.group().replace(",", "")) if mileage else odometer,
        "mileageWarranted": vd.get("mileageWarranted"),
        "grade": labels.get("VehicleGrade"),
        "mechanicalGrade": vd.get("mechanicalGrade"),
        "fuelType": labels.get("FuelType"),
        "transmission": labels.get("Gearbox"),
        "numberOfDoors": labels.get("NumberOfDoors") or fields.get("Doors"),
        "numberOfOwners": labels.get("NumberOfOwners"),
        "manufacturerColour": vd.get("manufacturerColour"),
        "logBookStatusIndicator": labels.get("LogBookStatusIndicator"),
        "serviceHistoryType": labels.get("ServiceHistoryIndicator"),
        "vatType": labels.get("VATType"),
        "nonRunner": vd.get("nonRunner"),
        "saleChannel": sd.get("saleChannel"),
        "saleDate": sd.get("saleDate"),
        "saleEndDate": sd.get("saleEndDate"),
        "saleType": sd.get("saleTypeName"),
        "saleLocation": sd.get("saleLocation"),
        "localSaleLocation": sd.get("localSaleLocation"),
        "lotNumber": ld.get("lotNumber"),
        "saleCode": sd.get("saleCode"),
    }
    car, photos = bca.flatten_detail(item, detail)
    car["url"] = url
    return car, photos


def motorway_record(url, detail, sale):
    mw.strip_personal(detail)  # private sellers' contact details are never kept
    spec = detail.get("spec") or {}
    item = {k: detail.get(k) for k in ("id", "prettyVrm", "year", "mileage", "displayPrice", "highestBid", "state",
                                       "exteriorGrade", "numericGrade", "isVatQualifying", "sellerWillAcceptPrice",
                                       "isTrade", "sourcePartner", "heroImages", "leadPhoto")}
    item.update({k: spec.get(k) for k in ("make", "model", "fuel", "transmission")})
    car, photos = mw.flatten_detail(item, detail, sale, "auction")
    car["url"] = url
    return car, photos


# ---------------------------------------------------------------- requests-based platforms

def fetch_page(session, url, guard, logged_out):
    """One GET, no retries. Raises on a logged-out session or a platform stop."""
    r = session.get(url, timeout=60)
    if logged_out(r):
        raise SessionLoggedOut("the saved session is logged out")
    guard.check_response(r.status_code, r.text)
    return r


def carwow_logged_out(r):
    return any(mark in r.url for mark in ("auth.carwow.co.uk", "/dealers/login", "/sign_in"))


def manheim_logged_out(r):
    is_page = "text/html" in r.headers.get("content-type", "")
    return "/Account/LogIn" in r.url or (r.status_code == 200 and is_page and "/logout" not in r.text.lower())


def collect_carwow(urls, guard, images=True):
    session = cw.make_session()
    (cw.OUT_DIR / "raw").mkdir(parents=True, exist_ok=True)

    def one(url):
        r = fetch_page(session, url, guard, carwow_logged_out)
        if r.status_code != 200:
            return failed(url, f"HTTP {r.status_code}", r.status_code)
        listing_id = urlsplit(url).path.rstrip("/").rsplit("/", 1)[1]
        fragments = []  # the condition report and history load separately, as on the page itself
        for part in ("condition_reports", "provenance_sections"):
            extra = fetch_page(session, f"{cw.BASE}/dealers/listings/{part}/{listing_id}", guard, carwow_logged_out)
            fragments.append(extra.text if extra.status_code == 200 else "")
        car, photos = carwow_record(url, r.text, fragments)
        folder = cw.OUT_DIR / "images" / f"{reg_key(car.get('registration'))}_{listing_id}"
        car["image_folder"] = rel(folder)
        if images:
            cw.download_photos(car, photos, folder)
        return captured(url, car, folder)

    for url in urls:
        guard.check_url(url)
        guard.pause()
        yield tagged(url, lambda: one(url))


def collect_manheim(urls, guard, images=True):
    session = mh.make_session()

    def one(url):
        r = fetch_page(session, url, guard, manheim_logged_out)
        if r.status_code != 200:
            return failed(url, f"HTTP {r.status_code}", r.status_code)
        car, photos = manheim_record(url, r.text)
        folder = mh.OUT_DIR / "images" / f"{reg_key(car.get('registration'))}_{car['vehicle_id']}"
        car["image_folder"] = rel(folder)
        if images:
            mh.download_files(list(enumerate(photos, 1)), folder)
        return captured(url, car, folder)

    for url in urls:
        guard.check_url(url)
        guard.pause()
        yield tagged(url, lambda: one(url))


# ---------------------------------------------------------------- browser-based platforms

def open_listing(page, url, guard, settle_ms):
    """Open one listing page in the browser and judge what came back."""
    response = page.goto(url, wait_until="load")
    page.wait_for_timeout(settle_ms)
    guard.check_response(response.status if response else 0, page.content(), page.title())
    return response.status if response else 0


def page_api(page, path, guard):
    """Read the JSON the listing page itself loads. Returns (status, data or None)."""
    status, text = page.evaluate(bca.FETCH_JSON, path)
    if status == 401:
        raise SessionLoggedOut("the saved session is logged out")
    guard.check_response(status, is_page=False)
    if status != 200:
        return status, None
    try:
        return status, json.loads(text)
    except json.JSONDecodeError:
        guard.check_response(status, text)  # a challenge page where JSON was expected
        return status, None


def collect_bca(urls, guard, images=True):
    from playwright.sync_api import sync_playwright

    def one(page, context, url):
        status = open_listing(page, url, guard, settle_ms=4000)
        if status != 200:
            return failed(url, f"HTTP {status}", status)
        vrm = urlsplit(url).path.rstrip("/").rsplit("/", 1)[1]
        status, detail = page_api(page, f"/api/bff/lot/proxy/buyer/inventorydetail/{vrm}?", guard)
        if detail is None:
            return failed(url, f"detail HTTP {status}", status)
        car, photos = bca_record(url, detail)
        folder = bca.OUT_DIR / "images" / vrm
        car["image_folder"] = rel(folder)
        if images:
            bca.download_photos(context, photos, folder, False)
        return captured(url, car, folder)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=bca.BACKGROUND_ARGS)  # BCA needs a real window...
        try:
            context = browser.new_context(storage_state=str(bca.SESSION_FILE),
                                          viewport={"width": 1366, "height": 850}, locale="en-GB")
            page = context.new_page()
            bca.set_window(page, "minimized")  # ...but it stays out of the way
            for url in urls:
                guard.check_url(url)
                guard.pause()
                yield tagged(url, lambda: one(page, context, url))
            context.storage_state(path=str(bca.SESSION_FILE))
        finally:
            browser.close()


def collect_motorway(urls, guard, images=True):
    from playwright.sync_api import sync_playwright

    sale = {}

    def one(page, context, url):
        status = open_listing(page, url, guard, settle_ms=2000)
        if "/signin" in page.url:
            raise SessionLoggedOut("the saved session is logged out")
        if status != 200:
            return failed(url, f"HTTP {status}", status)
        if not sale:  # the daily sale window: the end time shown on every car in the live sale
            sale.update(page_api(page, "/api/sale", guard)[1] or {})
        vehicle_id = urlsplit(url).path.rstrip("/").rsplit("/", 1)[1]
        status, detail = page_api(page, f"/api/vehicle?vehicleId={vehicle_id}", guard)
        if isinstance(detail, list):
            detail = detail[0] if detail else None
        if detail is None:
            return failed(url, f"detail HTTP {status}", status)
        car, photos = motorway_record(url, detail, sale)
        folder = mw.OUT_DIR / "images" / f"{reg_key(car.get('registration'))}_{vehicle_id}"
        car["image_folder"] = rel(folder)
        if images:
            mw.download_photos(context, photos, folder, False)
        return captured(url, car, folder)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(storage_state=mw.load_cookies(), user_agent=mw.USER_AGENT,
                                          viewport={"width": 1366, "height": 850}, locale="en-GB")
            page = context.new_page()
            for url in urls:
                guard.check_url(url)
                guard.pause()
                yield tagged(url, lambda: one(page, context, url))
            context.storage_state(path=str(mw.SESSION_FILE))
        finally:
            browser.close()


COLLECTORS = {
    "carwow": collect_carwow,
    "manheim": collect_manheim,
    "bca": collect_bca,
    "motorway": collect_motorway,
}
SESSION_FILES = {
    "carwow": cw.SESSION_FILE,
    "manheim": mh.SESSION_FILE,
    "bca": bca.SESSION_FILE,
    "motorway": mw.SESSION_FILE,
}
