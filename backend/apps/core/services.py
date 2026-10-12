from datetime import datetime
from zoneinfo import ZoneInfo

from django.conf import settings as django_settings
from django.utils import timezone

from .models import Event, Setting

UK = ZoneInfo(django_settings.UK_TIME_ZONE)

# Starting values; each can be overridden by a row in `settings` without new code.
DEFAULTS = {
    "prep_cost_pence": 110000,
    "target_margin_pence": 200000,  # to confirm with James (onboarding form)
    "ending_soon_hours": 24,
    "sync_slot_motorway": "16:45",
    "sync_slot_carwow": "17:15",
    "sync_slot_bca": "08:00",  # to confirm from real alert times
    "sync_slot_manheim": "08:30",  # to confirm from real alert times
    "scrape_max_mileage": 80000,
    "scrape_min_year": 2016,
}

DESCRIPTIONS = {
    "prep_cost_pence": "Prep cost per car, in pence (110000 = £1,100). Editable per car on the listing.",
    "target_margin_pence": "Target margin in pence. Selling price = buy price + prep cost + this.",
    "ending_soon_hours": "A car with less than this many hours left is flagged 'ending soon'.",
    "sync_slot_motorway": "Daily sync time for Motorway, UK time, HH:MM. The sync will not run before it.",
    "sync_slot_carwow": "Daily sync time for Carwow, UK time, HH:MM. The sync will not run before it.",
    "sync_slot_bca": "Daily sync time for BCA, UK time, HH:MM. The sync will not run before it.",
    "sync_slot_manheim": "Daily sync time for Manheim, UK time, HH:MM. The sync will not run before it.",
    "scrape_max_mileage": "The scrape command only collects cars with this mileage or less.",
    "scrape_min_year": "The scrape command only collects cars registered in this year or newer.",
}


def get_setting(key):
    row = Setting.objects.filter(key=key).values_list("value", flat=True).first()
    return DEFAULTS[key] if row is None else row


def emit_event(type, payload=None, actor=None):
    return Event.objects.create(type=type, payload=payload or {}, actor=actor)


def uk_now(now=None):
    return (now or timezone.now()).astimezone(UK)


def uk_date(now=None):
    return uk_now(now).date()


def uk_slot_time(slot):
    """'16:45' -> time(16, 45)."""
    return datetime.strptime(slot, "%H:%M").time()
