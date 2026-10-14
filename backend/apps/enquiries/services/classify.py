"""What kind of first message is this? One small AI call per new conversation; rules when AI is off or fails.

A message the classifier is not sure about is treated as "unsure": the Hub stays quiet and a person reads it.
"""

import re
from functools import lru_cache
from pathlib import Path

from apps.ai.client import AiUnavailable, ai_enabled, complete_json
from apps.core.services import get_setting

PROMPT_VERSION = "intent-v1"
PROMPT_FILE = Path(__file__).resolve().parent.parent / "prompts" / "intent_v1.md"
INTENTS = ("car_enquiry", "finance", "other_business", "personal")

# Rules, used without AI. Checked in this order: a booking or viewing is never a sale on its own.
BUSINESS = r"\b(mot|service|servicing|book(ing)?|appointment|view(ing)?|come and see|test ?drive|collect(ion)?|" \
           r"logbook|v5|warranty|warning light|complain(t)?|repair|broken|refund)\b"
FINANCE = r"\b(finance|pcp|hp|hire purchase|credit|quote|apr|monthly payments?)\b"
MONTHLY = r"\b(a month|per month|monthly|pm|deposit)\b"
SHOPPING = r"\b(looking for|buy|buying|purchase|after a|need a)\b"
CAR = r"\b(car|cars|looking for|buy|buying|purchase|change my|suv|hatchback|estate|auto(matic)?|manual|diesel|" \
      r"petrol|electric|hybrid|budget|seater|golf|audi|bmw|merc(edes)?|ford|vw|volkswagen|toyota|nissan|kia|" \
      r"hyundai|vauxhall|peugeot|tesla|range rover|land rover|stock|available)s?\b"


@lru_cache(maxsize=1)
def system_prompt():
    return PROMPT_FILE.read_text(encoding="utf-8")


def by_rules(text):
    """(intent, confidence). Rules only claim a sale or a booking; anything else is left for a person."""
    words = text.lower()
    car = bool(re.search(CAR, words))
    if re.search(BUSINESS, words) and not re.search(SHOPPING, words):
        return "other_business", 0.7
    # "what would the Audi be a month?" asks for finance; "looking for a car around £300 a month" is shopping
    if car and (re.search(FINANCE, words) or (re.search(MONTHLY, words) and not re.search(SHOPPING, words))):
        return "finance", 0.7
    if car:
        return "car_enquiry", 0.7
    return "unsure", 0.3


def classify(text):
    """(intent, confidence, how): intent is car_enquiry, finance, other_business, personal or unsure."""
    text = (text or "").strip()
    if not text:
        return "unsure", 0.0, "rules"
    minimum = float(get_setting("enquiry_min_confidence"))
    if ai_enabled():
        try:
            data = complete_json("intent", PROMPT_VERSION, system_prompt(), text[:1000])
            intent, confidence = data.get("intent"), float(data.get("confidence") or 0)
            if intent in INTENTS:
                return (intent if confidence >= minimum else "unsure"), confidence, "ai"
        except (AiUnavailable, TypeError, ValueError):
            pass
    intent, confidence = by_rules(text)
    return (intent if confidence >= minimum else "unsure"), confidence, "rules"
