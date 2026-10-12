import json
import re
from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand, CommandError

from apps.listings.models import Listing
from apps.listings.services.photos import InvalidPhoto, make_thumbnail, store_photo
from apps.sourcing.platforms import PLATFORMS
from apps.sourcing.services.ingest import IngestError, upsert_listing


def read_records(path):
    data = path.read_bytes()
    try:
        return json.loads(data.decode("utf-8"))
    except UnicodeDecodeError:
        return json.loads(data.decode("cp1252"))  # older exports were written in the Windows encoding


class Command(BaseCommand):
    help = ("Load an already-collected export (cars.json) into the listing database. For local development "
            "and back-filling only: the daily sync goes through the runner and the sync API.")

    def add_arguments(self, parser):
        parser.add_argument("platform", choices=list(PLATFORMS))
        parser.add_argument("cars_json", type=Path)
        parser.add_argument("--images-root", type=Path,
                            help="folder that each record's image_folder is relative to; photos are stored too")

    def handle(self, *args, platform, cars_json, images_root, **options):
        if not cars_json.exists():
            raise CommandError(f"{cars_json} does not exist.")
        saved = photos = skipped = 0
        for record in read_records(cars_json):
            try:
                listing, _ = upsert_listing(platform, record, source=Listing.Source.IMPORT)
            except IngestError as e:
                skipped += 1
                self.stderr.write(f"skipped: {e}")
                continue
            saved += 1
            if images_root and record.get("image_folder"):
                photos += self.store_photos(listing, images_root / record["image_folder"])
        self.stdout.write(f"{platform}: {saved} listings saved, {photos} photos stored, {skipped} skipped.")

    def store_photos(self, listing, folder):
        if not folder.is_dir():
            return 0
        files = {}
        for path in folder.iterdir():
            numbered = re.match(r"(\d+)(?:_.*)?\.jpe?g$", path.name, re.I)
            if numbered:
                files[int(numbered.group(1))] = path
        stored = 0
        for photo in listing.photos.filter(image=""):
            path = files.get(photo.position)
            if not path:
                continue
            try:
                with path.open("rb") as f:
                    store_photo(photo, File(f))
            except InvalidPhoto:
                continue
            make_thumbnail(photo)
            stored += 1
        return stored
