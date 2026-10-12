"""The platform sync rules (contract Schedule 1), enforced on the hub side.

- only platforms whose SYNC_ENABLED switch is on
- only URLs from Hart's saved-search alerts (the run's allowlist)
- once per platform per UK day
- a platform stop ends the whole run and alerts the team
- every URL opened is logged
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from apps.core.services import emit_event, get_setting, uk_date, uk_now, uk_slot_time
from apps.listings.models import Listing
from apps.listings.services.expiry import end_listings

from ..models import SyncLog, SyncRun
from ..platforms import PLATFORMS
from .ingest import IngestError, upsert_listing

logger = logging.getLogger(__name__)

GONE_STATUSES = (404, 410)  # the platform no longer has this listing


class RunStateError(Exception):
    """The run is not in a state that allows this step (for example a second run on the same day)."""


class NotAllowlisted(Exception):
    pass


def sync_enabled(platform):
    return bool(settings.SYNC_ENABLED.get(platform))


def notify_ops(subject, body):
    logger.warning("%s - %s", subject, body)
    if settings.OPS_ALERT_EMAILS:
        send_mail(f"[Hart Hub] {subject}", body, settings.DEFAULT_FROM_EMAIL, settings.OPS_ALERT_EMAILS,
                  fail_silently=True)


def _close(run, status, reason, now):
    run.status, run.stop_reason, run.finished_at = status, reason[:255], now
    run.save(update_fields=["status", "stop_reason", "finished_at"])
    return run


# ---------------------------------------------------------------- prepare

def prepare_run(platform, now=None):
    """Create today's run for a platform and build its allowlist. Returns (run, created).

    A second call on the same UK day returns the existing run: there is never a second run.
    """
    now = now or timezone.now()
    today = uk_date(now)
    with transaction.atomic():
        run, created = SyncRun.objects.get_or_create(platform=platform, uk_date=today, defaults={"created_at": now})
        if not created:
            return run, False
        if not sync_enabled(platform):
            return _close(run, SyncRun.Status.SKIPPED, "platform_not_enabled", now), True

        previous = SyncRun.objects.filter(platform=platform, uk_date__lt=today).order_by("-uk_date").first()
        since = previous.created_at if previous else now - timedelta(hours=24)
        live = Listing.objects.filter(platform=platform, status__in=Listing.LIVE_STATUSES)
        from_alerts = live.filter(source=Listing.Source.ALERT)
        alerted = from_alerts.filter(last_alert_at__gte=since)
        if alerted.exists():
            # an alert-sourced car that is no longer in the alerts has gone
            # (when no alerts arrive at all nothing is ended: the alert feed itself may be broken)
            end_listings(from_alerts.filter(last_alert_at__lt=since), "left_alerts", now)
        found = live.filter(source=Listing.Source.SEARCH)  # cars the scrape command found, re-checked daily
        definition = PLATFORMS[platform]
        run.allowlist = [url for url in (alerted | found).order_by("ends_at").values_list("url", flat=True)
                         if definition.match(url)]
        if not run.allowlist:
            return _close(run, SyncRun.Status.SKIPPED, "no_listings_to_sync", now), True
        run.save(update_fields=["allowlist"])
    return run, True


def due_platforms(now=None):
    """Platforms whose daily slot (UK time) has passed and that have no run yet today."""
    now = now or timezone.now()
    done = set(SyncRun.objects.filter(uk_date=uk_date(now)).values_list("platform", flat=True))
    clock = uk_now(now).time()
    return [p for p in PLATFORMS if p not in done and clock >= uk_slot_time(get_setting(f"sync_slot_{p}"))]


def close_stale_runs(now=None):
    """Runs the runner never collected, or went silent on, are closed so they cannot run late."""
    now = now or timezone.now()
    closed = 0
    for run in SyncRun.objects.filter(status=SyncRun.Status.READY, uk_date__lt=uk_date(now)):
        _close(run, SyncRun.Status.SKIPPED, "runner_did_not_collect", now)
        closed += 1
    silent = now - timedelta(hours=settings.SYNC_STALE_RUN_HOURS)
    for run in SyncRun.objects.filter(status=SyncRun.Status.RUNNING, started_at__lt=silent):
        finish_run(run, SyncRun.Status.FAILED, "runner_went_silent", now=now)
        closed += 1
    return closed


# ---------------------------------------------------------------- run

def run_for_runner(platform, now=None):
    """(run, reason): today's ready run for a platform, prepared now if its slot has passed.

    When there is nothing to run, `run` is None and `reason` says why in plain words.
    """
    now = now or timezone.now()
    if not sync_enabled(platform):
        return None, f"{platform} is switched off (SYNC_ENABLED_{platform.upper()} is not true)"
    run = SyncRun.objects.filter(platform=platform, uk_date=uk_date(now)).first()
    if run is None:
        slot = get_setting(f"sync_slot_{platform}")
        if uk_now(now).time() < uk_slot_time(slot):
            return None, f"today's slot is {slot} UK time (it is {uk_now(now):%H:%M} there now)"
        run, _ = prepare_run(platform, now)
    if run.status == SyncRun.Status.READY:
        return run, ""
    why = f": {run.stop_reason}" if run.stop_reason else ""
    return None, f"already has today's run ({run.get_status_display().lower()}{why}); one run per UK day"


def start_run(run_id, session_ok, now=None):
    """The runner claims a ready run. Without a logged-in session the run is skipped (manual fallback)."""
    now = now or timezone.now()
    with transaction.atomic():
        run = SyncRun.objects.select_for_update().get(pk=run_id)
        if run.status != SyncRun.Status.READY or run.uk_date != uk_date(now):
            raise RunStateError(f"Run is {run.status}; it cannot be started.")
        if not sync_enabled(run.platform):
            return _close(run, SyncRun.Status.SKIPPED, "platform_not_enabled", now)
        if not session_ok:
            _close(run, SyncRun.Status.SKIPPED, "session_logged_out", now)
        else:
            run.status, run.started_at = SyncRun.Status.RUNNING, now
            run.save(update_fields=["status", "started_at"])
            emit_event("sync.run_started", {"run_id": str(run.id), "platform": run.platform,
                                            "urls": len(run.allowlist)})
    if not session_ok:
        notify_ops(f"{run.platform} sync skipped: not logged in",
                   "The runner's session is logged out. A person must log in before the next slot; "
                   "today's listings go to the manual update queue.")
    return run


def record_url(run, url, outcome, *, record=None, http_status=None, detail="", now=None):
    """Log one URL the runner opened and, when captured, save the listing. Returns the listing or None."""
    now = now or timezone.now()
    if run.status != SyncRun.Status.RUNNING:
        raise RunStateError(f"Run is {run.status}; it is not accepting listings.")
    if url not in run.allowlist:
        SyncLog.objects.create(run=run, url=url[:500], outcome=SyncLog.Outcome.REFUSED, at=now,
                               detail="not on the allowlist")
        raise NotAllowlisted(url)

    listing = None
    if outcome == SyncLog.Outcome.CAPTURED:
        external_id, _ = PLATFORMS[run.platform].match(url)
        try:
            listing, _ = upsert_listing(run.platform, record, url=url, external_id=external_id, run=run, now=now)
        except IngestError as e:
            SyncLog.objects.create(run=run, url=url, outcome=SyncLog.Outcome.FAILED, at=now,
                                   http_status=http_status, detail=str(e)[:255])
            raise
    SyncLog.objects.create(run=run, url=url, outcome=outcome, http_status=http_status, detail=detail[:255], at=now)
    if outcome == SyncLog.Outcome.FAILED and http_status in GONE_STATUSES:
        external_id, _ = PLATFORMS[run.platform].match(url)
        end_listings(Listing.objects.filter(platform=run.platform, external_id=external_id,
                                            status__in=Listing.LIVE_STATUSES), "listing_gone", now)
    return listing


def finish_run(run, status, stop_reason="", now=None):
    """Close a running run. URLs never reached are logged as skipped; a stop or failure alerts the team."""
    now = now or timezone.now()
    with transaction.atomic():
        run = SyncRun.objects.select_for_update().get(pk=run.pk)
        if run.status != SyncRun.Status.RUNNING:
            raise RunStateError(f"Run is {run.status}; it cannot be finished.")
        seen = set(run.log.values_list("url", flat=True))
        SyncLog.objects.bulk_create([
            SyncLog(run=run, url=url, outcome=SyncLog.Outcome.SKIPPED, detail="not reached", at=now)
            for url in run.allowlist if url not in seen
        ])
        run.listings_captured = run.log.filter(outcome=SyncLog.Outcome.CAPTURED).values("url").distinct().count()
        run.status, run.stop_reason, run.finished_at = status, stop_reason[:255], now
        run.save(update_fields=["status", "stop_reason", "finished_at", "listings_captured"])
        event = {
            SyncRun.Status.COMPLETED: "sync.run_completed",
            SyncRun.Status.STOPPED_BY_PLATFORM: "sync.run_stopped_by_platform",
        }.get(status, "sync.run_failed")
        emit_event(event, {"run_id": str(run.id), "platform": run.platform, "reason": run.stop_reason,
                           "captured": run.listings_captured, "allowlisted": len(run.allowlist)})
    if status != SyncRun.Status.COMPLETED:
        notify_ops(f"{run.platform} sync {run.get_status_display().lower()}",
                   f"Reason: {run.stop_reason or 'not given'}. Captured {run.listings_captured} of "
                   f"{len(run.allowlist)} listings. The rest go to the manual update queue; the run "
                   f"will not be retried today.")
    return run
