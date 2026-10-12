from django.core.management.base import BaseCommand

from apps.listings.services.expiry import expire_listings


class Command(BaseCommand):
    help = "Mark listings past their end time as ended and flag those ending soon."

    def handle(self, *args, **options):
        result = expire_listings()
        self.stdout.write(f"Ended {result['ended']}, ending soon {result['ending_soon']}.")
