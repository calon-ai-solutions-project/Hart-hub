from datetime import datetime
from zoneinfo import ZoneInfo

from django.conf import settings as django_settings
from django.utils import timezone

from .models import Event, Setting

UK = ZoneInfo(django_settings.UK_TIME_ZONE)

# Starting values; each can be overridden by a row in `settings` without new code.
DEFAULTS = {
    "prep_cost_pence": 110000,
    "markup_pence": 150000,  # added to the platform price to make the customer price
    "ending_soon_hours": 24,
    "sync_delete_sold_listings": True,
    "sync_slot_motorway": "16:45",
    "sync_slot_carwow": "17:15",
    "sync_slot_bca": "08:00",  # to confirm from real alert times
    "sync_slot_manheim": "08:30",  # to confirm from real alert times
    "scrape_max_mileage": 80000,
    "scrape_min_year": 2016,
    "finance_estimate_apr_percent": 12.9,
    "finance_estimate_term_months": 48,
    "chat_over_budget_percent": 15,
    "codeweavers_term_months": 48,
    "codeweavers_extra_mileage": 500,
    "codeweavers_annual_mileage": 8000,
    "codeweavers_product": "(MotoNovo Finance) PCP",
    "codeweavers_fallback_product": "(MotoNovo Finance) HP",
    "codeweavers_credit_tier": "Excellent",
    "finance_disclaimer": "Finance is subject to status. Terms and conditions apply.",
}

DESCRIPTIONS = {
    "prep_cost_pence": "Prep cost per car, in pence (110000 = £1,100). Editable per car on the listing. It is not "
                       "added to the price: margin = markup - prep cost.",
    "markup_pence": "Added to the platform (buy) price to make the customer price, in pence (150000 = £1,500). "
                    "After changing it run: python manage.py reprice_listings",
    "ending_soon_hours": "A car with less than this many hours left is flagged 'ending soon'.",
    "sync_delete_sold_listings": "true: a car whose page has gone from the platform (sold or withdrawn) is deleted "
                                 "at the sync, with its photos and quotes. false: it is kept and marked ended.",
    "sync_slot_motorway": "Daily sync time for Motorway, UK time, HH:MM. The sync will not run before it.",
    "sync_slot_carwow": "Daily sync time for Carwow, UK time, HH:MM. The sync will not run before it.",
    "sync_slot_bca": "Daily sync time for BCA, UK time, HH:MM. The sync will not run before it.",
    "sync_slot_manheim": "Daily sync time for Manheim, UK time, HH:MM. The sync will not run before it.",
    "scrape_max_mileage": "The scrape command only collects cars with this mileage or less.",
    "scrape_min_year": "The scrape command only collects cars registered in this year or newer.",
    "finance_estimate_apr_percent": "Chatbot only: APR assumed when turning a monthly budget into a price "
                                    "ceiling. A rough guide for filtering, never a quote.",
    "finance_estimate_term_months": "Chatbot only: finance term assumed for the same price ceiling.",
    "chat_over_budget_percent": "When nothing fits the budget, the chatbot may show cars up to this much over.",
    "codeweavers_term_months": "Finance term used for every Codeweavers quote, in months.",
    "codeweavers_extra_mileage": "Miles added to a car's mileage when it is quoted (delivery and test drives).",
    "codeweavers_annual_mileage": "Annual Mileage chosen on every quote. Codeweavers only asks for it on "
                                  "mileage-based products such as PCP; Hire Purchase has no such field.",
    "codeweavers_product": "The Codeweavers product to quote, as worded in the Showroom product list. If that "
                           "lender does not offer it on a car, another lender's product of the same kind is tried.",
    "codeweavers_fallback_product": "Quoted when no product of the first kind (PCP) is available at the term on a "
                                    "car. Leave empty for no fallback.",
    "codeweavers_credit_tier": "Customer credit rating used for quotes: Excellent, Very Good, Good or Fair.",
    "finance_disclaimer": "Wording shown under every finance quote. Must be approved by Hart before customers see it.",
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
