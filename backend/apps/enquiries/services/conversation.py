"""The chatbot: a short WhatsApp conversation that finds out what car the customer wants.

AI only reads the conversation and returns the customer's answers as data (rules do the same when AI is off
or fails). The bot's words are always written by code (texts.py), so AI never writes to a customer and
never states a finance figure. The answers use the form's fields, so the rest of the journey is the same as
for a filled-in form.
"""

import re
from functools import lru_cache
from pathlib import Path

from apps.ai.client import AiUnavailable, ai_enabled, complete_json
from apps.matching.services import parse

from .classify import by_rules

PROMPT_VERSION = "chat-v1"
PROMPT_FILE = Path(__file__).resolve().parent.parent / "prompts" / "chat_v1.md"
INTENTS = ("car_enquiry", "greeting", "other_business", "personal")

# asked in this order, each at most once; a customer can answer several in one message
QUESTIONS = ("make_model", "monthly_budget", "deposit", "gearbox", "part_exchange")
EXTRA = ("colour", "needed_by")  # kept if they say it, never asked
ANY = "any"
NO = r"^\s*(no|nope|nah|none|no thanks|not really|n/?a|nothing|i don'?t|i do not|no deposit|0|zero|£0)\b"
DONT_MIND = r"\b(any|either|don'?t mind|do not mind|not fussed|no preference|whatever|anything)\b"


@lru_cache(maxsize=1)
def system_prompt():
    return PROMPT_FILE.read_text(encoding="utf-8")


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
