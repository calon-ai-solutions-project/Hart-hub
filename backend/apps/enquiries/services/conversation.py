"""The chatbot: a WhatsApp conversation that finds out what car the customer wants.

Conversational (`enquiry_ai_replies` on): one AI call reads the conversation, returns the customer's answers
as data and writes the reply. Every reply is checked by code (`guard`) before it is sent: no prices, monthly
payments, rates or percentages the customer didn't give, no finance acceptance, no stock or delivery promises,
no links. A reply that fails the check is replaced by the scripted question.
Scripted (AI off, failed, or `enquiry_ai_replies` off): AI or rules only read the answers and the bot's words
come from texts.py.
The answers use the form's fields, so the rest of the journey is the same as for a filled-in form.
"""

import json
import re
from functools import lru_cache
from pathlib import Path

from apps.ai.client import AiUnavailable, ai_enabled, complete_json
from apps.matching.services import parse

from .classify import by_rules

PROMPT_VERSION = "chat-v1"
PROMPT_FILE = Path(__file__).resolve().parent.parent / "prompts" / "chat_v1.md"
REPLY_PROMPT_VERSION = "chat-v2"
REPLY_PROMPT_FILE = Path(__file__).resolve().parent.parent / "prompts" / "chat_v2.md"
INTENTS = ("car_enquiry", "greeting", "other_business", "personal")

# asked in this order, each at most once; a customer can answer several in one message
QUESTIONS = ("make_model", "monthly_budget", "deposit", "gearbox", "part_exchange")
EXTRA = ("colour", "needed_by")  # kept if they say it, never asked
ANY = "any"
NO = r"^\s*(no|nope|nah|none|no thanks|not really|n/?a|nothing|i don'?t|i do not|no deposit|0|zero|£0)\b"
DONT_MIND = r"\b(any|either|don'?t mind|do not mind|not fussed|no preference|whatever|anything)\b"


YES = r"^\s*(yes|yeah|yea|yep|yup|ya|sure|ok|okay|please|definitely|i am|i'?m|we are|y)\b|\b(buy|buying|purchase|a car)\b"


def said_yes(text):
    """A yes to "are you looking to buy a car?"."""
    return bool(re.search(YES, str(text or "").lower()))


def said_no(text):
    """A no to "are you looking to buy a car?"."""
    return bool(re.search(r"^\s*(no|nope|nah|not really|not buying)\b", str(text or "").lower()))


@lru_cache(maxsize=1)
def system_prompt():
    return PROMPT_FILE.read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def reply_prompt():
    return REPLY_PROMPT_FILE.read_text(encoding="utf-8")


def pounds_text(value):
    return f"£{value:,.0f}" if value else "£0"


def transcript(messages, limit=20):
    """The last messages, each on one line, as the AI reads them."""
    lines = []
    for message in list(messages)[-limit:]:
        who = "Customer" if message.direction == "in" else "Hub"
        lines.append(f"{who}: {' '.join(message.body.split())[:500]}")
    return "\n".join(lines)


def from_ai(messages):
    data = complete_json("enquiry-chat", PROMPT_VERSION, system_prompt(), transcript(messages))
    if not isinstance(data, dict):
        raise AiUnavailable("AI returned something that is not an object.")
    return fields_of(data)


def fields_of(data):
    """The AI's JSON -> (intent, answers in the form's fields, wants_person). Anything malformed is dropped."""
    intent = data.get("intent") if data.get("intent") in INTENTS else "greeting"
    answers = {}
    for name in ("make_model", "part_exchange", "colour", "needed_by"):
        if isinstance(data.get(name), str) and data[name].strip():
            answers[name] = data[name].strip()[:120]
    for name, key in (("monthly_budget_gbp", "monthly_budget"), ("deposit_gbp", "deposit")):
        value = data.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value < 1_000_000:
            answers[key] = pounds_text(value)
    if data.get("gearbox") in ("auto", "manual"):
        answers["gearbox"] = "Auto" if data["gearbox"] == "auto" else "Manual"
    elif data.get("gearbox") == ANY:
        answers["gearbox"] = ANY
    return intent, answers, data.get("wants_person") is True


def answer_to(question, text):
    """A short reply to the question just asked ('400', 'no', 'either') -> the answer, or None."""
    words = text.lower().strip()
    if question in ("monthly_budget", "deposit"):
        if question == "deposit" and re.search(NO, words):
            return "£0"
        pence = parse.to_pence(words) if re.fullmatch(r"[£\s\d,.k]*(a month|pm|per month|monthly|pounds)?\s*", words) \
            else None
        return pounds_text(pence / 100) if pence else None
    if question == "gearbox":
        found = parse.gearbox_of(words)
        return {"auto": "Auto", "manual": "Manual"}.get(found) or (ANY if re.search(DONT_MIND, words) else None)
    if question == "part_exchange":
        return "none" if re.search(NO, words) else text.strip()[:120] or None
    if question == "make_model":
        return ANY if re.search(DONT_MIND, words) else None
    return None


def from_rules(messages, last_question):
    """The same as the AI, by rules: what the latest message states, plus a short answer to the last question."""
    text = messages[-1].body if messages else ""
    fields, answers = parse.from_text(text), {}
    # "a 2015 Ford Focus" in reply to the part-exchange question is their own car, not the one they want
    if (fields.get("make") or fields.get("model")) and last_question != "part_exchange":
        answers["make_model"] = " ".join(part for part in (fields.get("make"), fields.get("model")) if part)
    if fields.get("monthly_budget_pence"):
        answers["monthly_budget"] = pounds_text(fields["monthly_budget_pence"] / 100)
    if fields.get("deposit_pence"):
        answers["deposit"] = pounds_text(fields["deposit_pence"] / 100)
    if fields.get("gearbox"):
        answers["gearbox"] = "Auto" if fields["gearbox"] == "auto" else "Manual"
    if fields.get("colours"):
        answers["colour"] = ", ".join(fields["colours"])
    if last_question and last_question not in answers:
        reply = answer_to(last_question, text)
        if reply:
            answers[last_question] = reply
    intent, _ = by_rules(text)
    intent = {"finance": "car_enquiry", "unsure": "greeting"}.get(intent, intent)
    if answers and intent == "greeting":
        intent = "car_enquiry"
    wants_person = bool(re.search(r"\b(speak|talk) to (someone|a person|a human|staff)|\bcall me\b", text.lower()))
    return intent, answers, wants_person


def understand(messages, last_question=""):
    """(intent, answers, wants_person, how) for the conversation so far."""
    messages = list(messages)
    if ai_enabled():
        try:
            intent, answers, wants_person = from_ai(messages)
            # a bare "400" or "no" is read by the rules too, in case the AI missed what it answered
            if last_question and last_question not in answers and messages:
                reply = answer_to(last_question, messages[-1].body)
                if reply:
                    answers[last_question] = reply
            return intent, answers, wants_person, "ai"
        except (AiUnavailable, TypeError, ValueError):
            pass
    return (*from_rules(messages, last_question), "rules")


def next_question(answers, asked):
    """The first question not yet answered or asked, or None when there is nothing left to ask."""
    for name in QUESTIONS:
        if name not in answers and name not in asked:
            return name
    return None


# ---------------------------------------------------------------- conversational replies

MONTH = r"(?:a month|per month|/ ?month|monthly|pm\b|p/m|pcm)"
# finance and promises the AI must never make (matched ignoring case)
NEVER = (r"%|\bper ?cent\b|\bapr\b|\binterest\b|\bguarantee|\bpre-?approv|\bapproved\b|\baccepted\b|"
         r"\bcredit (score|check|rating|history)\b|\bin stock\b|\bon (our|the) (forecourt|lot)\b|"
         r"\bdeliver(ed|y)? (by|on|today|tomorrow|this|next)\b|https?://|www\.|\.co\.uk|\.com\b|"
         r"\b(bank details|sort code|card number|passport|driving licence number)\b|\+?\d[\d ]{9,}\d")
MONEY_IN_REPLY = r"£\s*\d[\d,]*(?:\.\d+)?k?|\b\d[\d,]*(?:\.\d+)?k?\b(?=\s*" + MONTH + ")"


def amounts(text, pattern=MONEY_IN_REPLY):
    """Every money-like number in a text, in pence: '£2,000', '2k', '300 a month'."""
    return {p for p in (parse.to_pence(m.group(0)) for m in re.finditer(pattern, text, re.I)) if p}


def guard(reply, customer_texts):
    """The AI's reply if it is safe to send, else None. A money amount is allowed only if the customer said it."""
    reply = str(reply or "").strip()
    if not reply or len(reply) > 700 or re.search(NEVER, reply, re.I):
        return None
    said = set()
    for text in customer_texts:  # any number they typed: "400", "2k", "£1,000"
        said |= amounts(text, r"\d[\d,]*(?:\.\d+)?k?")
    if amounts(reply) - said:
        return None
    return reply


def converse(messages, *, stage, known, needed, facts="", cars=()):
    """One AI call: (intent, answers, wants_person, ready, reply) for the conversation so far.
    The reply is not checked here: the caller passes it through `guard`."""
    context = {
        "FACTS": facts or "The Hart Group Automotive, a UK used-car dealer. Finance quotes and part-exchange are "
                          "offered. Anything else: one of the team will confirm.",
        "STAGE": stage,
        "KNOWN": known,
        "STILL NEEDED": list(needed),
    }
    if cars:
        context["CARS"] = list(cars)
    user = json.dumps(context, ensure_ascii=False, indent=1) + "\n\nCONVERSATION:\n" + transcript(messages)
    data = complete_json("enquiry-chat", REPLY_PROMPT_VERSION, reply_prompt(), user, temperature=0.4)
    if not isinstance(data, dict):
        raise AiUnavailable("AI returned something that is not an object.")
    intent, answers, wants_person = fields_of(data)
    return intent, answers, wants_person, data.get("ready") is True, str(data.get("reply") or "")

