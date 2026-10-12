from .common import buy_price, first, photos, text, to_datetime, to_mileage, to_pence, to_year


def normalise(record):
    make, model = text(record.get("make")), text(record.get("model"))
    channel = text(record.get("sale_channel"))
    return {
        "external_id": text(record.get("vehicle_id")),
        "registration": text(record.get("registration")),
        "vin": text(record.get("vin")),
        "make": make,
        "model": model,
        "trim": text(first(record, "spec_derivative", "derivative")),
        "title": text(f"{make} {model}"),
        "year": to_year(first(record, "year", "first_registered")),
        "mileage": to_mileage(record.get("mileage")),
        "fuel": text(record.get("fuel")),
        "gearbox": text(record.get("transmission")),
        "colour": text(record.get("colour")),
        "body": text(first(record, "spec_body", "body_type")),
        "grade": text(record.get("grade")),
        "spec": text(record.get("equipment")),
        "location": text(record.get("vehicle_location")),
        "sale_type": "buy_now" if "buy" in channel.lower() else "auction",
        "sale_channel": channel,
        "lot_number": "",
        "starts_at": to_datetime(record.get("sale_start_utc")),
        "ends_at": to_datetime(record.get("sale_end_utc")),
        "retail_valuation_pence": to_pence(record.get("price_retail")),
        "cap_clean_pence": None,
        "cap_average_pence": None,
        "cap_below_pence": None,
        "cap_retail_pence": None,
        **buy_price([
            (record.get("highest_bid"), "current_bid"),
            (first(record, "display_price", "price_reserve", "seller_will_accept_price"), "reserve"),
            (first(record, "minimum_bid", "minimum_bid_value"), "reserve"),
        ], None),
        "photos": photos(record),
    }
