from .common import buy_price, cap_prices, photos, text, to_datetime, to_mileage, to_pence, to_year

# makes whose name is more than one word (Carwow gives make + model as one text)
TWO_WORD_MAKES = ("Alfa Romeo", "Aston Martin", "Land Rover", "Rolls Royce", "Great Wall", "London Taxis",
                  "DS Automobiles")


def split_make_model(make_model):
    words = text(make_model).split()
    if not words:
        return "", ""
    for make in TWO_WORD_MAKES:
        if " ".join(words).lower().startswith(make.lower() + " "):
            n = len(make.split())
            return " ".join(words[:n]), " ".join(words[n:])
    return words[0], " ".join(words[1:])


def normalise(record):
    make, model = split_make_model(record.get("make_model"))
    ends_at = to_datetime(record.get("auction_ends"))
    caps = cap_prices(record)
    return {
        "external_id": text(record.get("listing_id")),
        "registration": text(record.get("registration")),
        "vin": text(record.get("vin")),
        "make": make,
        "model": model,
        "trim": text(record.get("derivative")),
        "title": text(f"{text(record.get('make_model'))} {text(record.get('derivative'))}"),
        "year": to_year(record.get("year_of_manufacture") or record.get("first_registered")),
        "mileage": to_mileage(record.get("mileage")),
        "fuel": text(record.get("fuel")),
        "gearbox": text(record.get("transmission")),
        "colour": text(record.get("colour")),
        "body": "",
        "grade": text(record.get("grade")),
        "spec": text(record.get("features")),
        # 'Bristol (74 m) Exact location provided after sale is confirmed' -> 'Bristol'
        "location": text(record.get("location")).split(" (")[0],
        # unsold cars stay listed after the auction closes, with no end time
        "sale_type": "auction" if ends_at else "buy_now",
        "sale_channel": text(record.get("selling_timeframe")),
        "lot_number": "",
        "starts_at": None,
        "ends_at": ends_at,
        "retail_valuation_pence": to_pence(record.get("autotrader_retail_valuation")),
        **caps,
        **buy_price([], caps["cap_clean_pence"]),
        "photos": photos(record),
    }
