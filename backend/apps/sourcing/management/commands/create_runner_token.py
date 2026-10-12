from django.core.management.base import BaseCommand

from apps.sourcing.models import RunnerToken


class Command(BaseCommand):
    help = "Issue an API token for the sync runner. The key is printed once and only its hash is stored."

    def add_arguments(self, parser):
        parser.add_argument("name", help="who or what holds this token, e.g. 'calon-runner-1'")

    def handle(self, *args, name, **options):
        _, key = RunnerToken.issue(name)
        self.stdout.write("Put this in the runner's .env as HUB_RUNNER_TOKEN (it cannot be shown again):")
        self.stdout.write(key)
