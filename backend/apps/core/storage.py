"""Cloudinary as the file store (car photos and quote documents), chosen by CLOUDINARY_URL.

A file keeps the same name it would have on disk, for example
`listings/motorway/30000004/thumbs/01.webp`, so nothing else in the code knows where files live.

- Photos are Cloudinary images with a public address: they are not secret and end up on customer cards.
- Anything else (quote PDFs) is stored as an "authenticated" raw file: it has no public address and is
  only ever read through the Hub, which signs the request.
"""

import cloudinary
import cloudinary.uploader
import cloudinary.utils
import requests
from django.core.files.base import ContentFile
from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible

IMAGE_TYPES = ("jpg", "jpeg", "png", "webp")
TIMEOUT = 60


def target(name):
    """Where a file name lives in Cloudinary: (public_id, resource_type, delivery type, format)."""
    name = name.replace("\\", "/").lstrip("/")
    stem, _, extension = name.rpartition(".")
    if stem and extension.lower() in IMAGE_TYPES:
        return stem, "image", "upload", extension.lower()
    return name, "raw", "authenticated", None


@deconstructible
class CloudinaryStorage(Storage):
    def __init__(self):
        cloudinary.config(secure=True)  # the account itself comes from CLOUDINARY_URL

    def get_available_name(self, name, max_length=None):
        return name  # one fixed name per file: saving again replaces it

    def _save(self, name, content):
        public_id, resource_type, delivery, _ = target(name)
        content.seek(0)
        cloudinary.uploader.upload(
            content.read(), public_id=public_id, resource_type=resource_type, type=delivery,
            overwrite=True, invalidate=True, unique_filename=False, use_filename=False, timeout=TIMEOUT)
        return name

    def url(self, name):
        public_id, resource_type, delivery, image_format = target(name)
        address, _ = cloudinary.utils.cloudinary_url(
            public_id, resource_type=resource_type, type=delivery, format=image_format, secure=True,
            sign_url=delivery != "upload")
        return address

    def _open(self, name, mode="rb"):
        response = requests.get(self.url(name), timeout=TIMEOUT)
        if response.status_code == 404:
            raise FileNotFoundError(name)
        response.raise_for_status()
        return ContentFile(response.content, name=name)

    def exists(self, name):
        return requests.head(self.url(name), timeout=TIMEOUT).status_code == 200

    def delete(self, name):
        public_id, resource_type, delivery, _ = target(name)
        cloudinary.uploader.destroy(public_id, resource_type=resource_type, type=delivery, invalidate=True)

    def size(self, name):
        return int(requests.head(self.url(name), timeout=TIMEOUT).headers.get("content-length", 0))
