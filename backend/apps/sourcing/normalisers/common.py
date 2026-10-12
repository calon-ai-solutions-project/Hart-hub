import re
from datetime import datetime, timezone

MAX_PHOTOS = 100


def text(value):
    return "" if value is None else re.sub(r"\s+", " ", str(value)).strip()


def to_int(value):
    """17848, '17,848', 4100.0, '£4,100' -> int; anything else -> None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    found = re.search(r"-?\d[\d,]*(?:\.\d+)?", str(value))
    return int(float(found.group().replace(",", ""))) if found else None


def to_pence(pounds):
    """Platform prices are whole pounds; we store integer pence."""
    pounds = to_int(pounds)
    return None if pounds is None or pounds < 0 else pounds * 100


def to_year(value):
    found = re.search(r"(?<!\d)(19|20)\d{2}(?!\d)", str(value or ""))
    return int(found.group()) if found else None


def to_mileage(value):
    miles = to_int(value)
    return miles if miles is not None and miles >= 0 else None


def to_datetime(value):
    """ISO date-time text -> aware datetime (UTC if no zone given), else None."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def first(record, *keys):
    """The first of `keys` with a real value in the record."""
    for key in keys:
        value = record.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def photos(record):
    """[(position, label, source_url)] from the runner's ' | ' separated photo columns."""
    urls = [u for u in str(record.get("photo_urls") or "").split(" | ") if u.startswith(("https://", "http://"))]
    labels = str(record.get("photo_labels") or "").split(" | ")
    rows = []
    for position, url in enumerate(urls[:MAX_PHOTOS], 1):
        label = labels[position - 1] if position - 1 < len(labels) else ""
        rows.append((position, "" if label == "photo" else text(label)[:120], url))
    return rows


def cap_prices(record):
    return {
        "cap_clean_pence": to_pence(first(record, "cap_clean", "price_capclean")),
        "cap_average_pence": to_pence(first(record, "cap_average", "price_capaverage")),
        "cap_below_pence": to_pence(first(record, "cap_below", "price_capbelowaverage")),
        "cap_retail_pence": to_pence(first(record, "cap_retail", "price_capretail")),
    }


def buy_price(candidates, cap_clean_pence):
    """The first platform price that exists, else CAP clean flagged as an estimate.

    `candidates` is [(pounds, kind)] in order of preference; a price of 0 means "none yet".
    """
    for pounds, kind in candidates:
        pence = to_pence(pounds)
        if pence:
            return {"buy_price_pence": pence, "buy_price_kind": kind}
    if cap_clean_pence:
        return {"buy_price_pence": cap_clean_pence, "buy_price_kind": "cap_clean"}
    return {"buy_price_pence": None, "buy_price_kind": ""}
