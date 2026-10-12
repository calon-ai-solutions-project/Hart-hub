import re
from urllib.parse import unquote

from .common import buy_price, cap_prices, first, photos, text, to_datetime, to_mileage, to_year


def make_model_trim(record):
    info = re.search(r"Make (.+?) Model (.+?) Reg no", text(record.get("vehicle_information")))
    make, model = (info.group(1), info.group(2)) if info else (text(record.get("make")), text(record.get("model")))
    title = text(record.get("title"))
    if not make:  # some pages have no vehicle information box - the make is in the page address
        in_url = re.search(r"/vehicle-detail/([^/?]+)/", text(record.get("url")))
        make = unquote(in_url.group(1)).replace("+", " ") if in_url else ""
        if make and title.upper().startswith(make.upper()):
            model = (title[len(make):].split() or [""])[0]
    trim = title
    for part in (make, model):
        if part and trim.upper().startswith(part.upper()):
            trim = trim[len(part):].strip()
    return make, model, trim


def sale_type(record):
    if record.get("is_buy_now"):
        return "buy_now"
    status = text(record.get("sale_status")).lower()
    if status.startswith("online"):
        return "bid_now"
    if "in-lane" in status or "simulcast" in status:
        return "live_sale"
    return "unknown"


def normalise(record):
    make, model, trim = make_model_trim(record)
    # 'Automatic - Diesel - 2.2L - 5 Door Estate GRADE 3 ...'
    summary = [p.strip() for p in text(record.get("summary")).split(" - ")]
    body = re.search(r"\d Door (\w+)", summary[-1]) if summary else None
    caps = cap_prices(record)
    prices = [(record.get("buy_now_price"), "buy_now")] if record.get("is_buy_now") else []
    prices.append((record.get("current_bid"), "current_bid"))
    return {
        "external_id": text(record.get("vehicle_id")),
        "registration": text(record.get("registration")),
        "vin": text(record.get("vin")),
        "make": make,
        "model": model,
        "trim": trim,
        "title": text(record.get("title")),
        "year": to_year(record.get("year")),
        "mileage": to_mileage(record.get("mileage")),
        "fuel": text(record.get("fuel")) or (summary[1] if len(summary) > 1 else ""),
        "gearbox": text(record.get("transmission")) or (summary[0] if len(summary) > 1 else ""),
        "colour": text(record.get("colour")),
        "body": body.group(1) if body else "",
        "grade": text(record.get("grade")),
        "spec": text(record.get("specification")),
        "location": text(first(record, "vehicle_location", "sale_location", "auction_centre")),
        "sale_type": sale_type(record),
        "sale_channel": text(first(record, "sale_channel_name", "sales_channel")),
        "lot_number": text(record.get("lot_number")),
        "starts_at": to_datetime(record.get("sale_start_utc")),
        "ends_at": to_datetime(record.get("sale_end_utc")),
        "retail_valuation_pence": None,
        **caps,
        **buy_price(prices, caps["cap_clean_pence"]),
        "photos": photos(record),
    }
