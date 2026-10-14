from django.core.management.base import BaseCommand

from apps.core.services import emit_event, get_setting
from apps.listings.models import Listing
from apps.listings.services.pricing import price_listing


class Command(BaseCommand):
    help = ("Work out every car's customer price again from the current markup setting. Run after changing "
            "markup_pence. Prices a person has set by hand are kept.")

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Show what would change without saving")

    def handle(self, *args, dry_run=False, **options):
        changed = kept = 0
        for listing in Listing.objects.filter(price_overridden=False).iterator():
            before = listing.suggested_price_pence
            price_listing(listing)
            if listing.suggested_price_pence == before:
                kept += 1
                continue
            changed += 1
            if not dry_run:
                listing.save(update_fields=["suggested_price_pence", "prep_cost_pence", "updated_at"])
        if changed and not dry_run:
            emit_event("listings.repriced", {"changed": changed, "markup_pence": get_setting("markup_pence")})
        overridden = Listing.objects.filter(price_overridden=True).count()
        self.stdout.write(self.style.SUCCESS(
            f"{'Would change' if dry_run else 'Changed'} {changed}, unchanged {kept}, set by hand and kept {overridden}"))
