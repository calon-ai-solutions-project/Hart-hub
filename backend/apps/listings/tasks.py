from celery import shared_task

from .models import ListingPhoto
from .services import embedding, expiry, photos


@shared_task(name="listings.expire_listings")
def expire_listings():
    return expiry.expire_listings()


@shared_task(name="listings.make_thumbnail")
def make_thumbnail(photo_id):
    photo = ListingPhoto.objects.select_related("listing").filter(pk=photo_id).first()
    return photos.make_thumbnail(photo) if photo else None


@shared_task(name="listings.embed_pending")
def embed_pending():
    """Every 5 minutes: give new and changed cars their search vector."""
    done, waiting = embedding.embed_pending()
    return {"embedded": done, "waiting": waiting}
