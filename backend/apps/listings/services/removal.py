import logging

from django.db import transaction
from django.utils import timezone

from apps.core.models import Event

from ..models import Listing, ListingPhoto

logger = logging.getLogger(__name__)


def delete_listings(queryset, reason, now=None):
    """Delete listings with everything stored for them and write one listing.deleted event each.

    Used when the platform no longer has the car (sold or withdrawn). The rows that hang off a
    listing (photos, search vector, matches, finance quotes) go with it, and so do the stored
    photo and quote files. The event keeps what was removed and why. Returns how many.
    """
    now = now or timezone.now()
    files = []
    with transaction.atomic():
        listings = list(queryset.select_for_update())
        if not listings:
            return 0
        ids = [listing.id for listing in listings]
        for photo in ListingPhoto.objects.filter(listing_id__in=ids):
            files += [field for field in (photo.image, photo.thumbnail) if field]
        for listing in listings:
            files += [quote.pdf for quote in listing.quotes.all() if quote.pdf]
        Event.objects.bulk_create([
            Event(type="listing.deleted", occurred_at=now,
                  payload={"listing_id": str(listing.id), "platform": listing.platform,
                           "external_id": listing.external_id, "title": listing.title, "reason": reason})
            for listing in listings
        ])
        Listing.objects.filter(id__in=ids).delete()
    for field in files:  # after the rows have gone, so a failed file delete never leaves half a car
        try:
            field.storage.delete(field.name)
        except Exception:
            logger.warning("Could not delete stored file %s", field.name, exc_info=True)
    return len(listings)
