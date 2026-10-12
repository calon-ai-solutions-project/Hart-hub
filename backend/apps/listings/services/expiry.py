from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.core.models import Event
from apps.core.services import get_setting

from ..models import Listing


def status_for(ends_at, now):
    """The status a still-listed car should have for its end time."""
    if ends_at is None:
        return Listing.Status.LIVE  # Buy Now: can sell at any time, re-checked at the next sync
    if ends_at <= now:
        return Listing.Status.ENDED
    if ends_at <= now + timedelta(hours=get_setting("ending_soon_hours")):
        return Listing.Status.ENDING_SOON
    return Listing.Status.LIVE


def end_listings(queryset, reason, now=None):
    """Mark listings ended and write one listing.expired event each. Returns how many."""
    now = now or timezone.now()
    with transaction.atomic():
        rows = list(queryset.select_for_update().values_list("id", "platform", "external_id"))
        if not rows:
            return 0
        Listing.objects.filter(id__in=[r[0] for r in rows]).update(
            status=Listing.Status.ENDED, ended_reason=reason, updated_at=now)
        Event.objects.bulk_create([
            Event(type="listing.expired", occurred_at=now,
                  payload={"listing_id": str(pk), "platform": platform, "external_id": external_id,
                           "reason": reason})
            for pk, platform, external_id in rows
        ])
    return len(rows)


def expire_listings(now=None):
    """Run every 15 minutes: past the end time -> ended; under 24 hours left -> ending soon."""
    now = now or timezone.now()
    live = Listing.objects.filter(status__in=Listing.LIVE_STATUSES)
    ended = end_listings(live.filter(ends_at__lte=now), "end_time_passed", now)
    soon = live.filter(
        status=Listing.Status.LIVE,
        ends_at__gt=now,
        ends_at__lte=now + timedelta(hours=get_setting("ending_soon_hours")),
    ).update(status=Listing.Status.ENDING_SOON, updated_at=now)
    return {"ended": ended, "ending_soon": soon}
