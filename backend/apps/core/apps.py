from django.apps import AppConfig
from django.conf import settings
from django.utils.autoreload import autoreload_started


def watch_env_file(sender, **kwargs):
    """Restart the dev server when backend/.env is edited, like it does for code."""
    sender.watch_file(settings.BASE_DIR / ".env")


class CoreConfig(AppConfig):
    name = "apps.core"
    label = "core"

    def ready(self):
        autoreload_started.connect(watch_env_file)
