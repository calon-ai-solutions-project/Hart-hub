from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.sourcing.platforms import PLATFORMS
from apps.sourcing.services.alerts import UnknownPlatform, ingest_alert


class Command(BaseCommand):
    help = "Ingest a saved alert email (.eml, .html or .txt) by hand, as the inbound webhook would."

    def add_arguments(self, parser):
        parser.add_argument("file", type=Path)
        parser.add_argument("--platform", choices=list(PLATFORMS), help="needed when the file has no From header")

    def handle(self, *args, file, platform, **options):
        raw = file.read_text(encoding="utf-8", errors="replace")
        sender = next((line.split(":", 1)[1].strip() for line in raw.splitlines()[:80]
                       if line.lower().startswith("from:")), "")
        try:
            alert = ingest_alert(raw, sender=sender, platform=platform)
        except UnknownPlatform as e:
            raise CommandError(f"{e} Pass --platform.")
        self.stdout.write(f"{alert.platform}: {alert.parsed_count} listings found in the alert.")
