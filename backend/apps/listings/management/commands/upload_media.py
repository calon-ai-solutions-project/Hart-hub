from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = ("Copy the photos and quote documents in backend/media to the storage bucket, keeping their "
            "names. Run once from a machine that has the files, with the S3_* variables set.")

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Upload files the bucket already has")

    def handle(self, *args, force=False, **options):
        if not settings.S3_BUCKET:
            raise CommandError("S3_BUCKET is not set, so there is no bucket to upload to.")
        root = Path(settings.MEDIA_ROOT)
        files = sorted(path for path in root.rglob("*") if path.is_file())
        sent = kept = 0
        for path in files:
            name = path.relative_to(root).as_posix()
            if not force and default_storage.exists(name):
                kept += 1
                continue
            with path.open("rb") as handle:
                default_storage.save(name, File(handle))
            sent += 1
            if sent % 50 == 0:
                self.stdout.write(f"  {sent} uploaded...")
        self.stdout.write(self.style.SUCCESS(f"{sent} uploaded, {kept} already there, {len(files)} files in {root}"))
