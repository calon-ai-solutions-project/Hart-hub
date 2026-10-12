from django.core.management.base import BaseCommand

from apps.core.models import Setting
from apps.core.services import DEFAULTS, DESCRIPTIONS


class Command(BaseCommand):
    help = ("Create a settings row for every default that has none, so each one can be seen and changed in "
            "the admin. Rows that already exist are left exactly as they are.")

    def handle(self, *args, **options):
        for key, value in DEFAULTS.items():
            setting, created = Setting.objects.get_or_create(
                key=key, defaults={"value": value, "description": DESCRIPTIONS.get(key, "")})
            self.stdout.write(f"{'added ' if created else 'kept  '} {key} = {setting.value}")
