import io

from django.conf import settings
from django.core.files.base import ContentFile
from PIL import Image, UnidentifiedImageError

from ..models import ListingPhoto, photo_path, thumbnail_path


class InvalidPhoto(ValueError):
    pass


def replace_file(field, name, data):
    """Store `data` at exactly `name`, replacing whatever is there: one fixed path per photo."""
    field.storage.delete(name)
    field.save(name, ContentFile(data), save=False)


def sync_photo_rows(listing, photos):
    """Make the listing's photo rows match `photos` = [(position, label, source_url)].

    A row whose source URL is unchanged keeps the file already stored for it.
    """
    existing = {p.position: p for p in listing.photos.all()}
    for position, label, source_url in photos:
        photo = existing.pop(position, None)
        if photo is None:
            ListingPhoto.objects.create(listing=listing, position=position, label=label, source_url=source_url)
        elif photo.source_url != source_url or photo.label != label:
            if photo.source_url != source_url:
                photo.image, photo.thumbnail = "", ""
            photo.label, photo.source_url = label, source_url
            photo.save()
    for photo in existing.values():
        photo.delete()
    listing.photo_count = len(photos)


def missing_positions(listing):
    return list(listing.photos.filter(image="").values_list("position", flat=True))


def store_photo(photo, upload):
    """Save an uploaded photo. Only real JPEG/PNG/WebP images under the size limit are accepted."""
    if upload.size > settings.PHOTO_MAX_BYTES:
        raise InvalidPhoto("Photo is too large.")
    data = upload.read()
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.verify()
            image_format = img.format
    except (UnidentifiedImageError, OSError, SyntaxError) as e:
        raise InvalidPhoto("Not a valid image.") from e
    if image_format not in ("JPEG", "PNG", "WEBP"):
        raise InvalidPhoto(f"Unsupported image type: {image_format}.")
    replace_file(photo.image, photo_path(photo, ""), data)
    if photo.thumbnail:
        photo.thumbnail.delete(save=False)
    photo.save()
    return photo


def make_thumbnail(photo):
    """Small WebP for list screens, so the portal never loads full-size photos in a grid."""
    if not photo.image:
        return None
    with photo.image.open("rb") as f:
        img = Image.open(f)
        img = img.convert("RGB")
    img.thumbnail((settings.THUMBNAIL_PX, settings.THUMBNAIL_PX))
    out = io.BytesIO()
    img.save(out, "WEBP", quality=78)
    replace_file(photo.thumbnail, thumbnail_path(photo, ""), out.getvalue())
    photo.save()
    if photo.position == 1:
        type(photo.listing).objects.filter(pk=photo.listing_id).update(cover_thumbnail=photo.thumbnail.name)
    return photo.thumbnail.name
