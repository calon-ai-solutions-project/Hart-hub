from django.core.management.base import BaseCommand

from apps.sourcing.platforms import PLATFORMS
from apps.sourcing.services.runs import prepare_run


class Command(BaseCommand):
    help = "Create today's sync run for a platform now (the scheduler does this at the platform's slot)."

    def add_arguments(self, parser):
        parser.add_argument("platform", choices=list(PLATFORMS))

    def handle(self, *args, platform, **options):
        run, created = prepare_run(platform)
        if not created:
            self.stdout.write(f"{platform} already has a run for {run.uk_date} ({run.status}). "
                              f"Only one run per platform per UK day is allowed.")
            return
        note = f" - {run.stop_reason}" if run.stop_reason else ""
        self.stdout.write(f"{platform} {run.uk_date}: {run.status}{note}, {len(run.allowlist)} URLs allowlisted.")
