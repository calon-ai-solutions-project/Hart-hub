"""python manage.py whatsapp_check: do the WhatsApp token and phone number ID work? Asks Meta; sends nothing."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.enquiries.services import whatsapp


class Command(BaseCommand):
    help = "Check the WhatsApp Cloud API credentials with Meta (sends no message)."

    def handle(self, *args, **options):
        if not whatsapp.enabled():
            raise CommandError("Set WHATSAPP_PHONE_NUMBER_ID and KAPSO_API_KEY (or, with WHATSAPP_PROVIDER=meta, "
                               "WHATSAPP_ACCESS_TOKEN) first.")
        try:
            number = whatsapp.check()
        except Exception as e:  # the token itself is never printed
            raise CommandError(str(e)) from e
        self.stdout.write(self.style.SUCCESS(
            f"OK: {number.get('verified_name')} ({number.get('display_phone_number')}), "
            f"quality {number.get('quality_rating', '?')}"))
        for name in (("KAPSO_WEBHOOK_SECRET",) if whatsapp.kapso() else ("WHATSAPP_APP_SECRET", "WHATSAPP_VERIFY_TOKEN")):
            if not getattr(settings, name):
                self.stdout.write(self.style.WARNING(f"{name} is not set: the webhook cannot receive messages yet."))
        if settings.WHATSAPP_REAL_CUSTOMERS:
            self.stdout.write(self.style.WARNING("WHATSAPP_REAL_CUSTOMERS is on: real customers are answered."))
        else:
            self.stdout.write(f"Test numbers only: {len(settings.WHATSAPP_TEST_NUMBERS)} allowed.")
