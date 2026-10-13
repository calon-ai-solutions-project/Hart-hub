from django.core.management.base import BaseCommand, CommandError

from apps.ai.client import embeddings_enabled
from apps.listings.services.embedding import embed_pending, pending


class Command(BaseCommand):
    help = "Create the search vector for every car that has none, or whose description has changed."

    def handle(self, *args, **options):
        if not embeddings_enabled():
            raise CommandError("Set OPENROUTER_API_KEY and OPENROUTER_EMBEDDING_MODEL first.")
        total = 0
        while True:
            done, waiting = embed_pending()
            total += done
            self.stdout.write(f"embedded {total}, {waiting} waiting")
            if not done or not waiting:
                break
        if pending().exists():
            raise CommandError("Some cars could not be embedded; see the AI usage log, then run this again.")
