"""Option cards. A customer only ever receives `customer_card`; staff fields live in `staff_card`."""

from django.conf import settings
from django.utils import timezone

from apps.core.services import uk_now
from apps.listings.models import Listing
from apps.listings.services.public import car_page_url

# The complete list of what a customer may see. Nothing else is ever added to a customer payload.
CUSTOMER_FIELDS = ("id", "title", "year", "mileage", "fuel", "gearbox", "colour", "body", "spec", "price_pence",
                   "photo", "photo_count", "available_until", "ends_at", "ending_soon")


def clock(moment):
    """15:30 -> '3.30pm', as Hart writes times."""
    return f"{moment.hour % 12 or 12}.{moment.minute:02d}{'am' if moment.hour < 12 else 'pm'}"


def available_until(listing, now=None):
    """The 'this deal ends' line, from the platform's end time (UK time)."""
    if listing.ends_at is None:
        return "Available: Immediate."  # no end time from the platform
    now, ends = uk_now(now or timezone.now()), uk_now(listing.ends_at)
    days = (ends.date() - now.date()).days
    if days == 0:
        return f"This deal ends today at {clock(ends)}. After that it's gone."
    if days == 1:
        return f"This deal ends tomorrow at {clock(ends)}. After that it's gone."
    return f"This deal ends on {ends:%A} {ends.day} {ends:%B} at {clock(ends)}."


def customer_card(listing, now=None):
    card = {
        "id": str(listing.id),
        "title": listing.title or f"{listing.make} {listing.model}".strip(),
        "year": listing.year,
        "mileage": listing.mileage,
        "fuel": listing.fuel,
        "gearbox": listing.gearbox,
        "colour": listing.colour.title(),
        "body": listing.body,
        "spec": listing.spec[:300],
        "price_pence": listing.suggested_price_pence,
        # a fixed address (apps/listings/views.py), so cards saved in a chat keep their photo
        "photo": f"{settings.MEDIA_URL}{listing.cover_thumbnail}" if listing.cover_thumbnail else "",
        "photo_count": listing.photo_count,
        "available_until": available_until(listing, now),
        "ends_at": listing.ends_at.isoformat() if listing.ends_at else None,  # the platform's end time, UTC
        "ending_soon": listing.status == Listing.Status.ENDING_SOON,
    }
    assert set(card) == set(CUSTOMER_FIELDS)
    return card


def margin_band(margin_pence):
    if margin_pence is None:
        return ""
    return "green" if margin_pence >= 200000 else "amber" if margin_pence >= 100000 else "red"


def staff_card(listing, reason="", flags=(), score=None, similarity=None):
    """Staff only: never send this to a customer."""
    return {
        "platform": listing.get_platform_display(),
        "listing_url": listing.url,
        "registration": listing.registration,
        "buy_price_pence": listing.buy_price_pence,
        "buy_price_kind": listing.get_buy_price_kind_display() if listing.buy_price_kind else "",
        "prep_cost_pence": listing.prep_cost_pence,
        "margin_pence": listing.margin_pence,
        "margin_band": margin_band(listing.margin_pence),
        "match_reason": reason,
        "match_score": score,
        "similarity": None if similarity is None else round(similarity, 3),
        "flags": list(flags),
        "customer_page": car_page_url(listing),
    }
