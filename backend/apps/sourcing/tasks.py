from celery import shared_task

from .services import runs


@shared_task(name="sourcing.prepare_due_syncs")
def prepare_due_syncs():
    """Every 5 minutes: create the day's run for each platform whose slot has passed."""
    closed = runs.close_stale_runs()
    prepared = [str(runs.prepare_run(platform)[0]) for platform in runs.due_platforms()]
    return {"prepared": prepared, "closed": closed}
