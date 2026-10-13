from django.db import models, transaction
from django.utils import timezone

from apps.core.services import emit_event
from apps.listings.models import Listing
from apps.listings.services.embedding import mark_if_changed
from apps.listings.services.expiry import status_for
from apps.listings.services.photos import sync_photo_rows
from apps.listings.services.pricing import price_listing

from ..normalisers import normalise
from ..normalisers.common import text
from ..platforms import PLATFORMS


class IngestError(ValueError):
    pass


CHAR_LIMITS = {f.name: f.max_length for f in Listing._meta.get_fields()
               if isinstance(f, models.CharField) and f.max_length}


def upsert_listing(platform, record, *, url="", external_id="", run=None, source=Listing.Source.ALERT, now=None):
    """Save one captured car: normalise, price, set its status and photo rows. Returns (listing, created).

    The same car seen twice is one row (platform + the platform's id); the latest price and end time win.
    """
    if not isinstance(record, dict):
        raise IngestError("The record must be an object.")
    now = now or timezone.now()
    fields = normalise(platform, record)
    photos = fields.pop("photos")
    external_id = external_id or fields["external_id"]
    fields.pop("external_id")
    if not external_id:
        raise IngestError("The record has no listing id.")
    url = url or text(record.get("url"))

    with transaction.atomic():
        listing = Listing.objects.select_for_update().filter(platform=platform, external_id=external_id).first()
        created = listing is None
        if created:
            listing = Listing(platform=platform, external_id=external_id, source=source, first_seen_at=now)
        for name, value in fields.items():
            if isinstance(value, str) and name in CHAR_LIMITS:
                value = value[:CHAR_LIMITS[name]]
            setattr(listing, name, value)
        listing.url = url or listing.url
        listing.raw = record
        listing.details_status = Listing.DetailsStatus.COMPLETE
        listing.last_seen_at = listing.last_captured_at = now
        if run is not None:
            listing.last_run = run
        if listing.status != Listing.Status.SOLD:
            listing.status = status_for(listing.ends_at, now)
            listing.ended_reason = "end_time_passed" if listing.status == Listing.Status.ENDED else ""
        price_listing(listing)
        listing.save()
        sync_photo_rows(listing, photos)
        listing.save(update_fields=["photo_count"])
        mark_if_changed(listing)  # its search vector is redone if the description changed
        emit_event("listing.upserted", {
            "listing_id": str(listing.id), "platform": platform, "external_id": external_id,
            "created": created, "run_id": str(run.id) if run else None,
        })
    return listing, created


def save_scraped(platform, record):
    """Save a car the scrape command found on a platform's search. Returns (listing, created).

    Its link must be a real listing page of that platform, so the daily sync can re-check it.
    """
    if not isinstance(record, dict):
        raise IngestError("The record must be an object.")
    match = PLATFORMS[platform].match(text(record.get("url")))
    if not match:
        raise IngestError(f"The record's url is not a {platform} listing page.")
    external_id, url = match
    return upsert_listing(platform, record, url=url, external_id=external_id, source=Listing.Source.SEARCH)
