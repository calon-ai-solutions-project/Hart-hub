"""The customer journey, independent of the channel (the portal's simulator now, WhatsApp later).

new message -> AI decides what it is -> chat (or form link) -> quote cars -> approve -> 5 options -> hand-over

AI classifies the first message. While chatting, AI reads the conversation and writes the replies (each one checked
by code before it is sent; scripted questions when AI is off). Options, quotes and finance figures are only ever
built by code from Codeweavers.
Personal messages are never stored. Nothing is sent outside WhatsApp's 24-hour window.
"""

import re
import secrets
import threading
from datetime import timedelta

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from apps.ai.client import AiUnavailable, ai_enabled
from apps.core.services import emit_event, get_setting
from apps.listings.services.public import car_page_url, customer_photos, is_available, link_for
from apps.matching.models import Requirement
from apps.matching.services import parse, rerank, search
from apps.matching.services.cards import customer_card, staff_card
from apps.quotes import services as quotes
from apps.quotes.models import Quote

from . import conversation, texts
from .classify import classify
from ..models import Customer, Enquiry, EnquiryMessage, EnquiryOption

WINDOW = timedelta(hours=24)  # WhatsApp: free-form messages only within 24 hours of the customer's last message
FORM_FIELDS = ("make_model", "colour", "needed_by", "gearbox", "monthly_budget", "deposit", "part_exchange")
# "one" on its own is not a choice ("which one is cheaper?"); "number one" or "option one" is
WORD_NUMBERS = {r"(number|option|car|no\.?) one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "first": 1,
                "second": 2, "third": 3, "fourth": 4, "fifth": 5}
# a question about the cars is not a choice, unless it says so ("can I go with number 2?")
QUESTION = r"^\s*(which|what|whats|what's|does|do|is|are|has|have|how|why|when|where|any|could you|can you)\b"
CHOOSING = r"\b(i'?ll take|i'?ll have|i want|i'?d like|go with|go for|choose|pick|interested in)\b"


class CannotSend(Exception):
    """The options cannot go to the customer (for example outside the 24-hour window)."""


def e164(phone):
    """'07700 900123' -> '+447700900123'. UK numbers only for now."""
    digits = re.sub(r"[^\d+]", "", str(phone or ""))
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    if digits.startswith("0"):
        digits = "+44" + digits[1:]
    if not digits.startswith("+"):
        digits = "+" + digits
    return digits


def form_url(enquiry):
    return f"{settings.PUBLIC_SITE_URL}/f/{enquiry.form_token}"


def next_time(enquiry, now=None):
    """A message's time: now, but always after the conversation's last message. The conversation is ordered by
    time, and Windows' clock can give two messages the same time."""
    at = now or timezone.now()
    latest = enquiry.messages.order_by("-created_at").values_list("created_at", flat=True).first()
    return latest + timedelta(microseconds=1) if latest and at <= latest else at


def say(enquiry, body, *, media_url="", sender=EnquiryMessage.Sender.BOT, user=None):
    """Save a message to the customer; on WhatsApp it is delivered once saved, in the order it was said."""
    message = EnquiryMessage.objects.create(enquiry=enquiry, direction=EnquiryMessage.Direction.OUT, sender=sender,
                                            sent_by=user, body=body, media_url=media_url,
                                            created_at=next_time(enquiry))
    if enquiry.channel == "whatsapp":  # sent in order, each after the one before it has arrived
        transaction.on_commit(lambda: deliver(enquiry.id))
    return message


def deliver(enquiry_id):
    from . import whatsapp

    whatsapp.pump(enquiry_id)


def move(enquiry, step, reason="", actor=None):
    enquiry.step = step
    if reason:
        enquiry.needs_person_reason = reason[:200]
    enquiry.save()
    emit_event("enquiry.step", {"enquiry_id": str(enquiry.id), "step": step, "reason": reason}, actor=actor)


def active_enquiry(phone, now):
    quiet = now - timedelta(days=int(get_setting("enquiry_quiet_days")))
    return (Enquiry.objects.filter(customer__phone=phone, updated_at__gte=quiet)
            .exclude(step=Enquiry.Step.CLOSED).select_related("customer").first())


# ---------------------------------------------------------------- incoming messages

STOP = r"\s*(stop|stop all|unsubscribe|opt out|optout)\s*[.!]*\s*"


def stop(phone, now):
    """STOP: the customer is suppressed on every channel at once, and their open conversations are closed."""
    customer, _ = Customer.objects.get_or_create(phone=phone)
    customer.opted_out_at = now
    customer.save()
    for enquiry in customer.enquiries.exclude(step=Enquiry.Step.CLOSED):
        move(enquiry, Enquiry.Step.CLOSED, "Customer sent STOP")
    emit_event("customer.stopped", {"customer_id": str(customer.id)})
    return {"ignored": True, "intent": "stop", "enquiry": None, "replies": []}


def handle_inbound(phone, text, *, channel="simulator", business_number="", now=None, external_id=""):
    """One message from a customer. Returns {"ignored": bool, "intent", "enquiry", "replies": [messages]}."""
    now = now or timezone.now()
    phone, text = e164(phone), (text or "").strip()[:2000]
    if re.fullmatch(STOP, text, re.I):
        return stop(phone, now)
    enquiry = active_enquiry(phone, now)
    if enquiry is not None:
        return {"ignored": False, "intent": enquiry.intent, "enquiry": enquiry,
                "replies": continue_journey(enquiry, text, now, external_id)}

    intent, confidence, how = classify(text)
    if intent == "personal":  # friends and family: no reply, nothing stored
        emit_event("enquiry.ignored_personal", {"channel": channel})
        return {"ignored": True, "intent": intent, "enquiry": None, "replies": []}

    with transaction.atomic():
        customer, _ = Customer.objects.get_or_create(phone=phone)
        enquiry = Enquiry.objects.create(customer=customer, channel=channel, business_number=business_number,
                                         intent=intent, intent_confidence=confidence, intent_by=how,
                                         step=Enquiry.Step.NEEDS_PERSON, last_inbound_at=now)
        EnquiryMessage.objects.create(enquiry=enquiry, direction=EnquiryMessage.Direction.IN,
                                      sender=EnquiryMessage.Sender.CUSTOMER, body=text, created_at=now,
                                      external_id=external_id)
        emit_event("enquiry.started", {"enquiry_id": str(enquiry.id), "intent": intent, "by": how,
                                       "confidence": confidence})
        replies = []
        by_form = get_setting("enquiry_collect_by") == "form"
        if customer.opted_out_at:  # they sent STOP before: no bot messages; a person decides whether to reply
            move(enquiry, Enquiry.Step.NEEDS_PERSON, "This customer sent STOP before: the Hub will not reply")
        elif intent == Enquiry.Intent.OTHER:  # a booking, viewing or complaint: a person answers
            move(enquiry, Enquiry.Step.NEEDS_PERSON, "Not a car-buying enquiry")
            replies.append(say(enquiry, texts.person_will_reply()))
        elif by_form and intent in (Enquiry.Intent.CAR, Enquiry.Intent.FINANCE):
            replies.append(send_form_link(enquiry, now))
        else:  # just "hi" (or, with the chat setting, a car enquiry): the chatbot finds out what they want
            move(enquiry, Enquiry.Step.CHATTING)
    if enquiry.step == Enquiry.Step.CHATTING and intent == Enquiry.Intent.UNSURE:
        # just "hi": give them a minute to say more; if they don't, ask what they're messaging about
        transaction.on_commit(lambda: wait_then_ask_purpose(enquiry.id))
    elif enquiry.step == Enquiry.Step.CHATTING:
        replies = chat(enquiry)
    return {"ignored": False, "intent": intent, "enquiry": enquiry, "replies": replies}


def continue_journey(enquiry, text, now, external_id=""):
    """A message in the middle of a journey: handled by its step (AI reads it while chatting)."""
    EnquiryMessage.objects.create(enquiry=enquiry, direction=EnquiryMessage.Direction.IN,
                                  sender=EnquiryMessage.Sender.CUSTOMER, body=text, created_at=next_time(enquiry, now),
                                  external_id=external_id)
    enquiry.last_inbound_at = now
    enquiry.save()
    step = enquiry.step
    if step == Enquiry.Step.CHATTING:
        return chat(enquiry)
    if step == Enquiry.Step.FORM_SENT and not enquiry.nudged:
        enquiry.nudged = True
        enquiry.save()
        return [say(enquiry, texts.form_reminder(form_url(enquiry)))]
    waiting = step in (Enquiry.Step.FORM_DONE, Enquiry.Step.QUOTING, Enquiry.Step.AWAITING_APPROVAL)
    if waiting and ai_replies():
        return side_reply(enquiry, "waiting")
    if waiting and not enquiry.nudged:
        enquiry.nudged = True
        enquiry.save()
        return [say(enquiry, texts.still_working())]
    if step == Enquiry.Step.OPTIONS_SENT:
        number = chosen_number(enquiry, text)
        if number:
            return [hand_over(enquiry, number)]
        move(enquiry, Enquiry.Step.OPTIONS_SENT, "Replied to the options, but not with a car number")
        if ai_replies():
            return side_reply(enquiry, "options")
    return []  # a person has the conversation, or the Hub has already said it is working on it


def wait_then_ask_purpose(enquiry_id):
    """Ask what a bare "hi" is about, after `enquiry_greeting_wait_seconds`, unless they say more first."""
    wait = int(get_setting("enquiry_greeting_wait_seconds"))
    if settings.CELERY_TASK_ALWAYS_EAGER:
        timer = threading.Timer(wait, _run_on_thread, args=(ask_purpose, enquiry_id))
        timer.daemon = True
        timer.start()
    else:
        from ..tasks import ask_purpose as task

        task.apply_async(args=[str(enquiry_id)], countdown=wait)


def ask_purpose(enquiry_id, now=None):
    """The minute is up. Ask "are you looking to buy a car?" if nothing has been said since
    the greeting and the Hub has not replied yet."""
    now = now or timezone.now()
    wait = timedelta(seconds=int(get_setting("enquiry_greeting_wait_seconds")))
    with transaction.atomic():
        enquiry = Enquiry.objects.select_for_update().filter(pk=enquiry_id).first()
        if enquiry is None or enquiry.step != Enquiry.Step.CHATTING:
            return None
        if enquiry.messages.filter(direction=EnquiryMessage.Direction.OUT).exists():
            return None  # they wrote again and the chatbot has already answered
        since = now - (enquiry.last_inbound_at or now)
        if since < wait - timedelta(seconds=2) or since > WINDOW:
            return None  # a newer message is being answered, or it is too late for a free-form message
        enquiry.asked = list(enquiry.asked) + ["purpose"]
        enquiry.save()
        emit_event("enquiry.purpose_asked", {"enquiry_id": str(enquiry.id)})
        return say(enquiry, texts.purpose())


def ai_replies():
    """Conversational replies: the owner's switch, and AI configured."""
    return bool(get_setting("enquiry_ai_replies")) and ai_enabled()


def bot_replies(enquiry):
    return enquiry.messages.filter(direction=EnquiryMessage.Direction.OUT, sender=EnquiryMessage.Sender.BOT).count()


def customer_texts(messages):
    return [m.body for m in messages if m.direction == EnquiryMessage.Direction.IN]


def send_form_link(enquiry, now=None, first=True):
    """They want to buy a car: send the one-page form (a new link each time)."""
    enquiry.form_token, enquiry.form_sent_at = secrets.token_urlsafe(12), now or timezone.now()
    enquiry.form_submitted_at, enquiry.nudged = None, False
    move(enquiry, Enquiry.Step.FORM_SENT)
    return say(enquiry, texts.form_link(form_url(enquiry), first=first))


def form_chat(enquiry):
    """With the form: the chat only finds out whether they want to buy a car. Yes -> the form link; another
    reason -> a person; only hellos -> "are you looking to buy a car?" (twice at most)."""
    messages = list(enquiry.messages.all())
    first = not any(m.direction == EnquiryMessage.Direction.OUT for m in messages)
    asked = list(enquiry.asked)
    intent, found, wants_person, how = conversation.understand(messages, "")
    text = messages[-1].body if messages else ""
    if wants_person or intent == "other_business":
        move(enquiry, Enquiry.Step.NEEDS_PERSON,
             "Asked to speak to a person" if wants_person else "Not a car-buying enquiry")
        return [say(enquiry, texts.person_will_reply())]
    buying = intent == "car_enquiry" or bool(found) or ("purpose" in asked and conversation.said_yes(text))
    if buying:
        if enquiry.intent == Enquiry.Intent.UNSURE:
            enquiry.intent, enquiry.intent_by = Enquiry.Intent.CAR, how
        return [send_form_link(enquiry, first=first)]
    if intent == "personal" and "purpose" not in asked:
        return []  # not for the business: no reply
    if "purpose" in asked and (conversation.said_no(text) or asked.count("purpose") >= 2):
        move(enquiry, Enquiry.Step.NEEDS_PERSON, "Not looking to buy a car" if conversation.said_no(text)
             else "Did not say what they're messaging about")
        return [say(enquiry, texts.person_will_reply())]
    enquiry.asked = asked + ["purpose"]
    enquiry.save()
    return [say(enquiry, texts.purpose(first=first))]


def chat(enquiry):
    """The chatbot's turn: with the form, only "do you want to buy a car?"; otherwise conversational when AI
    replies are on, else the scripted questions."""
    if get_setting("enquiry_collect_by") == "form":
        return form_chat(enquiry)
    if ai_replies():
        try:
            return ai_chat(enquiry)
        except AiUnavailable:
            pass  # the scripted questions carry on the same conversation
    return scripted_chat(enquiry)


def ai_chat(enquiry):
    """AI reads the conversation and writes the reply; code keeps the answers, checks the reply and decides when
    there is enough to start quoting."""
    messages = list(enquiry.messages.all())
    first = not any(m.direction == EnquiryMessage.Direction.OUT for m in messages)
    again = searching_again(enquiry)
    needed = [] if again else [name for name in conversation.QUESTIONS if name not in enquiry.answers]
    note = ("No cars could be found or quoted for what is in KNOWN, and the customer has been told. Help them "
            "choose a different car, monthly budget, deposit or gearbox; don't suggest specific prices.") if again else ""
    intent, found, wants_person, ready, reply = conversation.converse(
        messages, stage="chatting", known=enquiry.answers, needed=needed, facts=get_setting("business_facts"),
        note=note)
    if wants_person or (intent == "other_business" and not enquiry.answers and not found):
        move(enquiry, Enquiry.Step.NEEDS_PERSON,
             "Asked to speak to a person" if wants_person else "Not a car-buying enquiry")
        return [say(enquiry, texts.person_will_reply())]
    if intent == "personal" and not enquiry.answers and not found:
        return []  # not for the business: no reply

    new = {name: value for name, value in found.items() if enquiry.answers.get(name) != value}
    enquiry.answers = {**enquiry.answers, **found}
    if (new or intent == "car_enquiry") and enquiry.intent == Enquiry.Intent.UNSURE:
        enquiry.intent, enquiry.intent_by = Enquiry.Intent.CAR, "ai"
    emit_event("enquiry.chat", {"enquiry_id": str(enquiry.id), "by": "ai", "fields": sorted(new)})

    if again:  # search again only once something that changes the search has changed
        if set(new) & set(SEARCH_FIELDS) and knows_what_they_want(enquiry):
            return finish_chat(enquiry)
    elif all(name in enquiry.answers for name in conversation.QUESTIONS) or (ready and knows_what_they_want(enquiry)):
        return finish_chat(enquiry)
    if bot_replies(enquiry) >= int(get_setting("enquiry_ai_max_replies")):
        move(enquiry, Enquiry.Step.NEEDS_PERSON, "Long conversation without enough details to quote")
        return [say(enquiry, texts.person_will_reply())]

    safe = conversation.guard(reply, customer_texts(messages))
    if safe is None:  # the reply broke a rule (a price, a rate, a promise...): the scripted question instead
        emit_event("enquiry.ai_reply_blocked", {"enquiry_id": str(enquiry.id), "stage": "chatting"})
        if enquiry.answers or intent == "car_enquiry":
            safe = texts.chat_reply(conversation.next_question(enquiry.answers, []), new, first=first)
        else:
            safe = texts.purpose(first=first)
    enquiry.save()
    return [say(enquiry, safe)]


def side_reply(enquiry, stage):
    """A conversational answer while the cars are being prepared ("waiting") or after they were sent
    ("options"). The car details come only from the customer cards that were sent."""
    if bot_replies(enquiry) >= int(get_setting("enquiry_ai_max_replies")):
        return []
    messages = list(enquiry.messages.all())
    cars = []
    if stage == "options":
        for option in enquiry.options.filter(sent=True):
            card = option.customer["card"]
            cars.append({"number": option.number, **{key: card.get(key) for key in (
                "title", "year", "mileage", "fuel", "gearbox", "colour", "body", "available_until")}})
    try:
        _, _, wants_person, _, reply = conversation.converse(
            messages, stage=stage, known=enquiry.answers, needed=[], facts=get_setting("business_facts"), cars=cars)
    except AiUnavailable:
        reply, wants_person = "", False
    if wants_person:
        move(enquiry, enquiry.step, "Asked to speak to a person")
        return [say(enquiry, texts.person_will_reply())]
    safe = conversation.guard(reply, customer_texts(messages))
    if safe is None:
        if reply:
            emit_event("enquiry.ai_reply_blocked", {"enquiry_id": str(enquiry.id), "stage": stage})
        if stage == "options" or enquiry.nudged:
            return []
        enquiry.nudged = True
        enquiry.save()
        safe = texts.still_working()
    return [say(enquiry, safe)]


def knows_what_they_want(enquiry):
    return bool({"make_model", "monthly_budget"} & {
        name for name, value in enquiry.answers.items() if value not in ("any", "none", "£0")})


def finish_chat(enquiry):
    """Enough to quote: save the request, thank them, start finding and quoting cars. Neither a car nor a budget
    means a person takes over."""
    if not knows_what_they_want(enquiry):
        move(enquiry, Enquiry.Step.NEEDS_PERSON, "The chatbot could not find out what car they want")
        return [say(enquiry, texts.person_will_reply())]
    with transaction.atomic():
        thanks = save_request(enquiry, enquiry.answers, timezone.now())
    start_preparing(enquiry.id)
    return [thanks]


def scripted_chat(enquiry):
    """The scripted chatbot: read the conversation, keep what the customer has told us, then ask the next
    question, or, once there is nothing left to ask, start finding and quoting cars."""
    messages = list(enquiry.messages.all())
    first = not any(m.direction == EnquiryMessage.Direction.OUT for m in messages)  # the Hub hasn't spoken yet
    asked = list(enquiry.asked)
    last_question = asked[-1] if asked else ""
    intent, found, wants_person, how = conversation.understand(messages, last_question)
    if wants_person or (intent == "other_business" and not enquiry.answers and not found):
        move(enquiry, Enquiry.Step.NEEDS_PERSON,
             "Asked to speak to a person" if wants_person else "Not a car-buying enquiry")
        return [say(enquiry, texts.person_will_reply())]

    text = messages[-1].body if messages else ""
    if last_question == "retry":  # nothing was found: a new car or budget searches again, anything else -> a person
        changed = {name: value for name, value in found.items()
                   if name in SEARCH_FIELDS and enquiry.answers.get(name) != value}
        if changed:
            enquiry.answers = {**enquiry.answers, **found}
            return finish_chat(enquiry)
        move(enquiry, Enquiry.Step.NEEDS_PERSON, "No car found, and the customer did not give another car or budget")
        return [say(enquiry, texts.person_will_reply())]

    # "are you looking to buy a car?": yes -> the questions; no -> a person; unclear -> ask once more
    buying = False
    if last_question == "purpose":
        buying = intent == "car_enquiry" or bool(found) or conversation.said_yes(text)
        if not buying:
            if conversation.said_no(text) or asked.count("purpose") >= 2:
                move(enquiry, Enquiry.Step.NEEDS_PERSON, "Not looking to buy a car" if conversation.said_no(text)
                     else "Did not say what they're messaging about")
                return [say(enquiry, texts.person_will_reply())]
            enquiry.asked = asked + ["purpose"]
            enquiry.save()
            return [say(enquiry, texts.purpose(first=False))]
    elif intent == "greeting" and not asked and not enquiry.answers and not found:
        enquiry.asked = asked + ["purpose"]  # still only hellos: find out what they want first
        enquiry.save()
        return [say(enquiry, texts.purpose(first=first))]
    if intent == "personal" and not enquiry.answers and not found:
        return []  # not for the business: no reply

    new = {name: value for name, value in found.items() if enquiry.answers.get(name) != value}
    enquiry.answers = {**enquiry.answers, **found}
    if new and enquiry.intent == Enquiry.Intent.UNSURE:
        enquiry.intent, enquiry.intent_by = Enquiry.Intent.CAR, how
    emit_event("enquiry.chat", {"enquiry_id": str(enquiry.id), "by": how, "fields": sorted(new)})

    # nothing new in answer to a question asked once: ask it again; otherwise move on to the next one
    if (not new and last_question in conversation.QUESTIONS and last_question not in enquiry.answers
            and asked.count(last_question) < 2):
        question = last_question
    else:
        question = conversation.next_question(enquiry.answers, asked)
    if question:
        enquiry.asked = asked + [question]
        enquiry.save()
        return [say(enquiry, texts.chat_reply(question, new, first=first, buying=buying))]
    return finish_chat(enquiry)


def chosen_number(enquiry, text):
    """'2', 'number 2', 'the second one', 'the Audi' -> the option number, or None."""
    sent = list(enquiry.options.filter(sent=True))
    numbers = {option.number for option in sent}
    words = text.lower()
    if re.search(QUESTION, words) and not re.search(CHOOSING, words):
        return None
    found = re.findall(r"\b([1-9])\b", words) + [str(n) for w, n in WORD_NUMBERS.items() if re.search(rf"\b{w}\b", words)]
    picked = {int(n) for n in found if int(n) in numbers}
    if len(picked) == 1:
        return picked.pop()
    matches = [o.number for o in sent if any(len(w) > 2 and w in words
                                             for w in re.findall(r"[a-z0-9]+", o.customer["card"]["title"].lower())[:2])]
    return matches[0] if len(matches) == 1 else None


def hand_over(enquiry, number):
    option = enquiry.options.get(number=number)
    enquiry.chosen_number = number
    enquiry.assigned_to = enquiry.assigned_to or enquiry.approved_by
    person = (enquiry.assigned_to.first_name or enquiry.assigned_to.email.split("@")[0].title()) \
        if enquiry.assigned_to else ""
    move(enquiry, Enquiry.Step.HANDED_OVER, actor=enquiry.assigned_to)
    emit_event("enquiry.car_chosen", {"enquiry_id": str(enquiry.id), "number": number,
                                      "listing_id": str(option.listing_id) if option.listing_id else None})
    return say(enquiry, texts.handed_over(option.customer["card"]["title"], person))


# ---------------------------------------------------------------- the form

def form_for(token, now=None):
    """The enquiry behind a form link, or None if it does not exist or has expired."""
    now = now or timezone.now()
    enquiry = Enquiry.objects.filter(form_token=token).select_related("customer").first()
    if enquiry is None or enquiry.form_sent_at < now - timedelta(days=int(get_setting("form_link_days"))):
        return None
    return enquiry


def submit_form(enquiry, answers, now=None):
    """The customer sent the form. Saves their request, thanks them and starts finding and quoting cars."""
    now = now or timezone.now()
    with transaction.atomic():
        enquiry = Enquiry.objects.select_for_update().get(pk=enquiry.pk)
        if enquiry.form_submitted_at:
            return enquiry, False
        save_request(enquiry, answers, now)
    start_preparing(enquiry.id)
    return enquiry, True


def save_request(enquiry, answers, now):
    """What the customer wants, from the form or the chat -> a saved requirement. Returns the thank-you."""
    answers = {name: str(answers.get(name) or "").strip()[:200] for name in FORM_FIELDS}
    enquiry.answers = {**enquiry.answers, **{name: value for name, value in answers.items() if value}}
    requirement = Requirement(channel=enquiry.channel)
    fields = parse.from_form(answers)
    if not fields.get("make"):  # "SUV" or "family car" is not a model: search by budget, keep their words in notes
        fields.pop("model", None)
    parse.apply_fields(requirement, fields)
    requirement.notes = "" if answers["make_model"].lower() == "any" else answers["make_model"]
    requirement.save()
    enquiry.requirement, enquiry.form_submitted_at, enquiry.nudged = requirement, now, False
    move(enquiry, Enquiry.Step.FORM_DONE)
    thanks = say(enquiry, texts.thanks(answers if enquiry.asked else None))
    emit_event("requirement.saved", {"requirement_id": str(requirement.id), "channel": enquiry.channel,
                                     "enquiry_id": str(enquiry.id)})
    return thanks


# ---------------------------------------------------------------- find, quote, then send

def start_preparing(enquiry_id):
    """With a worker the job is queued; without one (local development) it runs on a thread."""
    if settings.CELERY_TASK_ALWAYS_EAGER:
        threading.Thread(target=_run_on_thread, args=(prepare_options, enquiry_id), daemon=True).start()
    else:
        from ..tasks import prepare_options

        prepare_options.delay(str(enquiry_id))


def _run_on_thread(job, enquiry_id):
    try:
        job(enquiry_id)
    finally:
        connection.close()


def ranked_cars(requirement):
    """The cars to try, best first: the AI or rule ranking of the shortlist, then the rest of it."""
    candidates, _ = search.find(requirement)
    seen, unique = set(), []
    for c in candidates:  # Codeweavers needs the registration
        plate = "".join(c.listing.registration.split()).upper()
        if plate and plate not in seen:  # a platform can list the same car twice: offer it once
            seen.add(plate)
            unique.append(c)
    candidates = unique
    picks, _ = rerank.choose(requirement, candidates)
    chosen = [c for c, _ in picks]
    reasons = {c.listing.id: reason for c, reason in picks}
    return [(c, reasons.get(c.listing.id, rerank.rule_reason(c, requirement)))
            for c in chosen + [c for c in candidates if c not in chosen]]


def prepare_options(enquiry_id):
    """Quote cars one batch at a time until enough have a Codeweavers quote, then hold them for approval
    (or send them, when the owner has switched on auto-send). Cars that cannot be quoted are skipped."""
    enquiry = Enquiry.objects.select_related("requirement").get(pk=enquiry_id)
    if enquiry.step != Enquiry.Step.FORM_DONE:
        return
    enquiry.quoting_started_at = timezone.now()
    move(enquiry, Enquiry.Step.QUOTING)
    wanted, limit = int(get_setting("enquiry_options")), int(get_setting("enquiry_max_quotes"))
    deposit = enquiry.requirement.deposit_pence or 0
    queue, done = ranked_cars(enquiry.requirement), []
    while queue and len(done) < wanted and enquiry.quotes_tried < limit:
        batch_size = min(wanted - len(done) + 1, limit - enquiry.quotes_tried)
        batch, queue = queue[:batch_size], queue[batch_size:]
        made = []
        for candidate, reason in batch:
            listing = candidate.listing
            if deposit >= (listing.suggested_price_pence or 0):
                continue
            made.append((Quote.objects.create(listing=listing, **quotes.inputs_for(listing, deposit)), candidate, reason))
        enquiry.quotes_tried += len(made)
        enquiry.save()
        quotes.run_quotes([quote.id for quote, _, _ in made])
        for quote, candidate, reason in made:
            quote.refresh_from_db()
            if quote.status == Quote.Status.DONE:
                done.append((quote, candidate, reason))
    done = done[:wanted]

    enquiry.quoting_finished_at = timezone.now()
    with transaction.atomic():
        for number, (quote, candidate, reason) in enumerate(done, 1):
            listing = candidate.listing
            card = customer_card(listing)
            staff = staff_card(listing, reason, candidate.flags, candidate.score, candidate.similarity)
            staff.update(markup_pence=(listing.suggested_price_pence or 0) - (listing.buy_price_pence or 0),
                         quote_ref=quote.quote_ref, product_quoted=quote.product_quoted or quote.product,
                         quote_note="" if not quote.product_quoted or quote.product_quoted == quote.product
                         else f"Quoted on {quote.product_quoted}")
            EnquiryOption.objects.create(enquiry=enquiry, number=number, listing=listing, quote=quote,
                                         customer={"card": card, "quote": quotes.quote_json(quote)["customer"]},
                                         staff=staff)
        if not done:
            offer_another_search(enquiry)
            return
        move(enquiry, Enquiry.Step.AWAITING_APPROVAL)
    emit_event("enquiry.options_ready", {"enquiry_id": str(enquiry.id), "options": len(done),
                                         "tried": enquiry.quotes_tried})
    if get_setting("enquiry_auto_send"):
        try:
            send_options(enquiry)
        except CannotSend as e:
            enquiry.refresh_from_db()
            if enquiry.step == Enquiry.Step.AWAITING_APPROVAL:
                move(enquiry, Enquiry.Step.NEEDS_PERSON, f"The options could not be sent: {e}")


WHATSAPP_IMAGES = (".jpg", ".jpeg", ".png")  # WhatsApp image messages take JPEG or PNG only, never WebP


# what a new search can change: the car, the budget, the deposit or the gearbox
SEARCH_FIELDS = ("make_model", "monthly_budget", "deposit", "gearbox")


def searching_again(enquiry):
    return bool(enquiry.asked) and enquiry.asked[-1] == "retry"


def offer_another_search(enquiry):
    """No car could be quoted: tell the customer and ask for another car or budget, then search again. After
    `enquiry_max_searches` empty searches (or outside the 24-hour window) a person takes over."""
    tried = enquiry.quotes_tried
    searches = list(enquiry.asked).count("retry") + 1
    recent = enquiry.last_inbound_at and timezone.now() - enquiry.last_inbound_at <= WINDOW
    emit_event("enquiry.no_match", {"enquiry_id": str(enquiry.id), "tried": tried, "search": searches})
    if not recent or searches >= int(get_setting("enquiry_max_searches")):
        move(enquiry, Enquiry.Step.NEEDS_PERSON,
             f"No car could be quoted in {searches} search{'es' if searches > 1 else ''} ({tried} tried this time)")
        if recent:
            say(enquiry, texts.person_will_reply())
        return
    enquiry.asked = list(enquiry.asked) + ["retry"]
    enquiry.quotes_tried, enquiry.nudged = 0, False
    if get_setting("enquiry_collect_by") == "form":
        searched = texts.noted({name: enquiry.answers.get(name) for name in ("make_model", "monthly_budget", "gearbox")})
        enquiry.form_token, enquiry.form_sent_at, enquiry.form_submitted_at = secrets.token_urlsafe(12), timezone.now(), None
        move(enquiry, Enquiry.Step.FORM_SENT)
        say(enquiry, texts.no_cars_form(searched, form_url(enquiry)))
        return
    move(enquiry, Enquiry.Step.CHATTING)
    say(enquiry, texts.no_cars(enquiry.answers))


def first_photo_url(listing):
    """The car's first full-size JPEG or PNG photo, from the public page's address (where photos are stored names
    the platform). Not the thumbnail: thumbnails are WebP, which WhatsApp drops without telling the sender."""
    for position, name in customer_photos(listing).values_list("position", "image"):  # never a damage photo
        if name.lower().endswith(WHATSAPP_IMAGES):
            return f"{settings.PUBLIC_SITE_URL}/api/public/cars/{link_for(listing).token}/photos/{position}"
    return ""


def send_options(enquiry, user=None, now=None):
    """Send the intro, one message per car and the closing line. Ended cars are dropped first."""
    now = now or timezone.now()
    with transaction.atomic():
        enquiry = Enquiry.objects.select_for_update().get(pk=enquiry.pk)
        if enquiry.step != Enquiry.Step.AWAITING_APPROVAL:
            raise CannotSend("These options have already been sent or are not ready.")
        if not enquiry.last_inbound_at or now - enquiry.last_inbound_at > WINDOW:
            raise CannotSend("More than 24 hours since the customer's last message: WhatsApp only allows an "
                             "approved template now, so the options were not sent.")
        options = [o for o in enquiry.options.select_related("listing")
                   if o.listing and is_available(o.listing, now)]  # an expired car is never sent
        if not options:
            move(enquiry, Enquiry.Step.NEEDS_PERSON, "Every prepared car has ended. Nothing was sent.")
            raise CannotSend("Every prepared car has ended since it was quoted, so nothing was sent.")
        enquiry.options.exclude(pk__in=[o.pk for o in options]).delete()
        say(enquiry, texts.intro(len(options)))
        for number, option in enumerate(options, 1):
            option.number, option.sent = number, True
            option.save()
            say(enquiry, texts.car(number, option.customer["card"], option.customer["quote"], car_page_url(option.listing)),
                media_url=first_photo_url(option.listing))
        say(enquiry, texts.closing())
        enquiry.approved_by = enquiry.approved_by or user
        enquiry.assigned_to = enquiry.assigned_to or user
        enquiry.nudged = False
        move(enquiry, Enquiry.Step.OPTIONS_SENT, actor=user)
    emit_event("enquiry.options_sent", {"enquiry_id": str(enquiry.id), "options": len(options)}, actor=user)
    return enquiry
