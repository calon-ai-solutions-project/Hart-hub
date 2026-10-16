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
    "enquiry_min_confidence": 0.6,  # below this a first message counts as "not sure"
    "enquiry_quiet_days": 14,  # after this long without messages, a new message starts a new journey
    "enquiry_options": 5,  # cars sent to a customer
    "enquiry_max_quotes": 12,  # cars tried at Codeweavers before giving up
    "enquiry_auto_send": False,  # off: a person approves the options before they are sent
    "form_link_days": 7,  # how long the form link works
    "enquiry_collect_by": "chat",  # chat: the chatbot asks what they want; form: a link to the one-page form
    "enquiry_ai_replies": True,  # owner switch: the chatbot's replies are written by AI (checked by code)
    "enquiry_ai_max_replies": 20,
    "enquiry_max_searches": 3,  # searches with no quotable car before a person takes over  # after this many bot replies in one enquiry, a person takes over
    "business_facts": "",  # what the chatbot may tell customers about Hart (hours, address...); owner-approved
    "enquiry_greeting_wait_seconds": 60,  # after a bare "hi", wait this long for more before asking what it's about
    "public_whatsapp_number": "",  # Hart's WhatsApp number in international form, e.g. 447700900100
    "sync_slot_motorway": "16:45",
    "sync_slot_carwow": "17:15",
    "sync_slot_bca": "08:00",  # to confirm from real alert times
    "sync_slot_manheim": "08:30",  # to confirm from real alert times
    "scrape_max_mileage": 80000,
    "scrape_min_year": 2016,
    "finance_estimate_apr_percent": 12.9,
    "finance_estimate_term_months": 48,
    "chat_over_budget_percent": 15,
    "codeweavers_method": "api",  # api: the JSON Finance API (about a second); browser: drive the Showroom
    "codeweavers_term_months": 48,
    "codeweavers_extra_mileage": 500,
    "codeweavers_annual_mileage": 8000,
    "codeweavers_product": "(MotoNovo Finance) PCP",
    "codeweavers_fallback_product": "",  # PCP only (decided 14 Oct 2026): a car with no PCP is not quoted
    "codeweavers_credit_tier": "Excellent",
    "finance_disclaimer": "Finance is subject to status. Terms and conditions apply.",
}

DESCRIPTIONS = {
    "prep_cost_pence": "Prep cost per car, in pence (110000 = £1,100). Editable per car on the listing. It is not "
                       "added to the price: margin = markup - prep cost.",
    "markup_pence": "Added to the platform (buy) price to make the customer price, in pence (150000 = £1,500). "
                    "After changing it run: python manage.py reprice_listings",
    "ending_soon_hours": "A car with less than this many hours left is flagged 'ending soon'.",
    "enquiry_min_confidence": "How sure (0 to 1) the AI must be about a first message. Below it the message "
                              "counts as 'not sure': the chatbot greets them and asks what they're looking for "
                              "(with the form setting, it waits for a person instead).",
    "enquiry_collect_by": "chat: the WhatsApp chatbot asks the customer what car they want, one question at a "
                          "time. form: the Hub sends a link to the one-page enquiry form instead.",
    "enquiry_quiet_days": "After this many days without messages, a customer's next message starts a new journey.",
    "enquiry_options": "How many quoted cars are sent to a customer.",
    "enquiry_max_quotes": "How many cars are tried at Codeweavers per customer before giving up (about 45 seconds each).",
    "enquiry_auto_send": "true: options go to the customer as soon as they are quoted. false: a person presses "
                         "'Approve & send'. Owner decision.",
    "enquiry_ai_replies": "true: the WhatsApp chatbot is conversational: AI writes each reply, and code checks it "
                          "before it is sent (no prices, monthly payments, rates, finance acceptance, stock or "
                          "delivery promises, links). false: scripted questions. Owner decision.",
    "enquiry_max_searches": "When no car can be quoted, the bot tells the customer and asks for another car or "
                            "budget. After this many searches with no car, a person takes over.",
    "enquiry_ai_max_replies": "After this many chatbot replies in one enquiry without enough details, a person "
                              "takes over.",
    "business_facts": "Facts the chatbot may tell customers about Hart (opening hours, address, what you offer). "
                      "Anything not here, it says the team will confirm. Approved by the owner.",
    "enquiry_greeting_wait_seconds": "When the first message is only a greeting ('hi', 'hello'), the chatbot waits "
                                     "this many seconds for the customer to say more. If they don't, it asks "
                                     "whether they are looking to buy a car.",
    "form_link_days": "How many days the customer's form link keeps working.",
    "public_whatsapp_number": "Hart's WhatsApp Business number, digits only with the country code (447700900100). "
                              "Shown as the 'Reply on WhatsApp' button on the public car page; empty hides it.",
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
    "codeweavers_method": "How quotes are fetched. api = Codeweavers' JSON Finance API (fast, all cars at once, no PDF). "
                          "browser = drive the Showroom website (slow, one car at a time, includes the PDF).",
    "codeweavers_term_months": "Finance term used for every Codeweavers quote, in months.",
    "codeweavers_extra_mileage": "Miles added to a car's mileage when it is quoted (delivery and test drives).",
    "codeweavers_annual_mileage": "Annual Mileage chosen on every quote. Codeweavers only asks for it on "
                                  "mileage-based products such as PCP; Hire Purchase has no such field.",
    "codeweavers_product": "The Codeweavers product to quote, as worded in the Showroom product list. If that "
                           "lender does not offer it on a car, another lender's product of the same kind is tried.",
    "codeweavers_fallback_product": "Empty (the default): PCP only, so a car with no PCP at the term is not quoted "
                                    "and is not offered to customers. A product here, e.g. (MotoNovo Finance) HP, "
                                    "is quoted instead when there is no PCP.",
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
