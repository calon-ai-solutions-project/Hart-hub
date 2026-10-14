"""The public car page ("more photos" link): what a customer may see about one car, and nothing else."""

import secrets

from django.conf import settings
from django.db import IntegrityError
from django.utils import timezone

from ..models import CarLink, Listing


def link_for(listing):
    """The car's one public link, made the first time it is asked for."""
    try:
        return listing.public_link
    except CarLink.DoesNotExist:
        pass
    try:
        return CarLink.objects.create(listing=listing, token=secrets.token_urlsafe(8))  # 11 characters, unguessable
    except IntegrityError:  # made at the same moment by another request
        return CarLink.objects.get(listing=listing)


def car_page_url(listing):
    return f"{settings.PUBLIC_SITE_URL}/c/{link_for(listing).token}"


def is_available(listing, now=None):
    now = now or timezone.now()
    return (listing.status in Listing.LIVE_STATUSES and listing.suggested_price_pence is not None
            and (listing.ends_at is None or listing.ends_at > now))


def page(token, now=None):
    """What the page shows for a code, or None for a code that does not exist.

    A car that has ended or sold says so and shows nothing else. Built only from the customer card.
    """
    from apps.core.services import get_setting
    from apps.matching.services.cards import customer_card

    link = CarLink.objects.select_related("listing").filter(token=token).first()
    if link is None:
        return None
    CarLink.objects.filter(pk=link.pk).update(opened_count=link.opened_count + 1, last_opened_at=timezone.now())
    whatsapp = "".join(ch for ch in str(get_setting("public_whatsapp_number") or "") if ch.isdigit())
    listing = link.listing
    if not is_available(listing, now):
        return {"available": False, "whatsapp": whatsapp}
    card = customer_card(listing, now)
    card.pop("id")  # nothing that identifies the car in the Hub
    card.pop("photo")  # the staff photo address needs a login: the page lists every photo below instead
    card.pop("price_pence")  # no price on the public page (decided 14 Oct 2026)
    # photos are served through the page's own address: where they are stored names the platform
    base = f"/api/public/cars/{token}/photos"
    photos = [{"full": f"{base}/{p.position}", "thumb": f"{base}/{p.position}?size=thumb"}
              for p in listing.photos.exclude(image="").order_by("position")]
    return {"available": True, "whatsapp": whatsapp, "car": card, "photos": photos,
            "disclaimer": get_setting("finance_disclaimer")}


def photo(token, position, thumb=False, now=None):
    """The bytes of one photo of an available car, or None."""
    link = CarLink.objects.select_related("listing").filter(token=token).first()
    if link is None or not is_available(link.listing, now):
        return None
    found = link.listing.photos.filter(position=position).exclude(image="").first()
    if found is None:
        return None
    field = found.thumbnail if thumb and found.thumbnail else found.image
    with field.open("rb") as handle:
        return handle.read(), ("image/webp" if field.name.endswith(".webp") else "image/jpeg")
