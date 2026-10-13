from celery import shared_task

from . import services


@shared_task(name="quotes.run_quotes")
def run_quotes(quote_ids):
    services.run_quotes(quote_ids)
