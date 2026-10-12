import re

from .common import buy_price, cap_prices, first, photos, text, to_datetime, to_mileage, to_year

SALE_TYPES = {
    "internetauction": "bid_now",  # timed e-Auction
    "liveonline": "live_sale",
    "fixedprice": "buy_now",
    "tender": "auction",
}
BODIES = ("hatchback", "saloon", "estate", "coupe", "convertible", "suv", "mpv", "van", "pickup", "cabriolet")


def body_from(title):
    """BCA ends its description with the body style: '... T-JET 140 Hatchback' -> 'Hatchback'."""
    last = title.split()[-1] if title else ""
    return last if last.lower() in BODIES else ""


def normalise(record):
    registration = text(first(record, "registration", "registration_number"))
    title = text(first(record, "description", "vehicle_description"))
    caps = cap_prices(record)
    # BCA labels its own prices; pick up a guide or buy-now figure when the lot shows one
    prices = [(v, "buy_now") for k, v in record.items() if k.startswith("price_") and "buy" in k]
    prices += [(v, "guide") for k, v in record.items() if k.startswith("price_") and "guide" in k]
    return {
        "external_id": re.sub(r"[^A-Z0-9]", "", registration.upper()),
        "registration": registration,
        "vin": text(record.get("vin")),
        "make": text(record.get("make")),
        "model": text(record.get("model")),
        "trim": text(record.get("derivative")),
        "title": title,
        "year": to_year(first(record, "year", "plate")) or to_year(
            first(record, "first_registered_date", "dateregistered")),
        "mileage": to_mileage(record.get("mileage")),
        "fuel": text(first(record, "fuel", "fuel_type")),
        "gearbox": text(first(record, "transmission", "gearbox")),
        "colour": text(first(record, "colour", "manufacturer_colour", "colour_manufacturer")),
        "body": text(record.get("body_type")) or body_from(title),
        "grade": text(first(record, "grade", "vehicle_grade")),
        "spec": text(record.get("equipment")),
        "location": text(first(record, "vehicle_location", "sale_location")),
        "sale_type": SALE_TYPES.get(text(record.get("sale_channel")).lower(), "unknown"),
        "sale_channel": text(first(record, "sale_type", "sale_channel")),
        "lot_number": text(record.get("lot_number")),
        "starts_at": to_datetime(record.get("sale_date")),
        "ends_at": to_datetime(record.get("sale_end_date")),
        "retail_valuation_pence": None,
        **caps,
        **buy_price(prices, caps["cap_clean_pence"]),
        "photos": photos(record),
    }
