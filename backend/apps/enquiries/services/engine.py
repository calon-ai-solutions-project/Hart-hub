"""The customer journey, independent of the channel (the portal's simulator now, WhatsApp later).

new message -> AI decides once -> form link -> form filled -> quote cars -> approve -> 5 options -> hand-over

Only the first message of a journey is read by AI. Later messages are handled by the journey's step.
Personal messages are never stored. Nothing is sent outside WhatsApp's 24-hour window.
"""

import re
import secrets
import threading
from datetime import timedelta

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from apps.core.services import emit_event, get_setting
from apps.listings.services.public import car_page_url, is_available, link_for
from apps.matching.models import Requirement
from apps.matching.services import parse, rerank, search
from apps.matching.services.cards import customer_card, staff_card
from apps.quotes import services as quotes
from apps.quotes.models import Quote

from . import texts
from .classify import classify
from ..models import Customer, Enquiry, EnquiryMessage, EnquiryOption

WINDOW = timedelta(hours=24)  # WhatsApp: free-form messages only within 24 hours of the customer's last message
FORM_FIELDS = ("make_model", "colour", "needed_by", "gearbox", "monthly_budget", "deposit", "part_exchange")
WORD_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "first": 1, "second": 2, "third": 3,
                "fourth": 4, "fifth": 5}


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


def say(enquiry, body, *, media_url="", sender=EnquiryMessage.Sender.BOT, user=None):
    return EnquiryMessage.objects.create(enquiry=enquiry, direction=EnquiryMessage.Direction.OUT, sender=sender,
                                         sent_by=user, body=body, media_url=media_url)


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

def handle_inbound(phone, text, *, channel="simulator", business_number="", now=None):
    """One message from a customer. Returns {"ignored": bool, "intent", "enquiry", "replies": [messages]}."""
    now = now or timezone.now()
    phone, text = e164(phone), (text or "").strip()[:2000]
    enquiry = active_enquiry(phone, now)
    if enquiry is not None:
        return {"ignored": False, "intent": enquiry.intent, "enquiry": enquiry,
                "replies": continue_journey(enquiry, text, now)}

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
                                      sender=EnquiryMessage.Sender.CUSTOMER, body=text, created_at=now)
        emit_event("enquiry.started", {"enquiry_id": str(enquiry.id), "intent": intent, "by": how,
                                       "confidence": confidence})
        replies = []
        if intent in (Enquiry.Intent.CAR, Enquiry.Intent.FINANCE):
            enquiry.form_token, enquiry.form_sent_at = secrets.token_urlsafe(12), now
            move(enquiry, Enquiry.Step.FORM_SENT)
            replies.append(say(enquiry, texts.form_link(form_url(enquiry))))
        else:  # a booking, viewing, complaint, or anything the classifier was unsure about: a person answers
            move(enquiry, Enquiry.Step.NEEDS_PERSON,
                 "Not a car-buying enquiry" if intent == Enquiry.Intent.OTHER else "The Hub was not sure what this is")
    return {"ignored": False, "intent": intent, "enquiry": enquiry, "replies": replies}


def continue_journey(enquiry, text, now):
    """A message in the middle of a journey: handled by its step, never by AI."""
    EnquiryMessage.objects.create(enquiry=enquiry, direction=EnquiryMessage.Direction.IN,
                                  sender=EnquiryMessage.Sender.CUSTOMER, body=text, created_at=now)
    enquiry.last_inbound_at = now
    enquiry.save()
    step = enquiry.step
    if step == Enquiry.Step.FORM_SENT and not enquiry.nudged:
        enquiry.nudged = True
        enquiry.save()
        return [say(enquiry, texts.form_reminder(form_url(enquiry)))]
    if step in (Enquiry.Step.FORM_DONE, Enquiry.Step.QUOTING, Enquiry.Step.AWAITING_APPROVAL) and not enquiry.nudged:
        enquiry.nudged = True
        enquiry.save()
        return [say(enquiry, texts.still_working())]
    if step == Enquiry.Step.OPTIONS_SENT:
        number = chosen_number(enquiry, text)
        if number:
            return [hand_over(enquiry, number)]
        move(enquiry, Enquiry.Step.OPTIONS_SENT, "Replied to the options, but not with a car number")
    return []  # a person has the conversation, or the Hub has already said it is working on it


def chosen_number(enquiry, text):
    """'2', 'number 2', 'the second one', 'the Audi' -> the option number, or None."""
    sent = list(enquiry.options.filter(sent=True))
    numbers = {option.number for option in sent}
    words = text.lower()
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
    answers = {name: str(answers.get(name) or "").strip()[:200] for name in FORM_FIELDS}
    with transaction.atomic():
        enquiry = Enquiry.objects.select_for_update().get(pk=enquiry.pk)
        if enquiry.form_submitted_at:
            return enquiry, False
        requirement = Requirement(channel=enquiry.channel)
        parse.apply_fields(requirement, parse.from_form(answers))
        requirement.notes = answers["make_model"]
        requirement.save()
        enquiry.requirement, enquiry.form_submitted_at, enquiry.nudged = requirement, now, False
        move(enquiry, Enquiry.Step.FORM_DONE)
        say(enquiry, texts.thanks())
        emit_event("requirement.saved", {"requirement_id": str(requirement.id), "channel": enquiry.channel,
                                         "enquiry_id": str(enquiry.id)})
    start_preparing(enquiry.id)
    return enquiry, True


# ---------------------------------------------------------------- find, quote, then send

def start_preparing(enquiry_id):
    """With a worker the job is queued; without one (local development) it runs on a thread."""
    if settings.CELERY_TASK_ALWAYS_EAGER:
        threading.Thread(target=_prepare_on_thread, args=(enquiry_id,), daemon=True).start()
    else:
        from ..tasks import prepare_options

        prepare_options.delay(str(enquiry_id))


def _prepare_on_thread(enquiry_id):
    try:
        prepare_options(enquiry_id)
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
            move(enquiry, Enquiry.Step.NEEDS_PERSON,
                 f"No car could be quoted ({enquiry.quotes_tried} tried). Nothing was sent to the customer.")
            return
        move(enquiry, Enquiry.Step.AWAITING_APPROVAL)
    emit_event("enquiry.options_ready", {"enquiry_id": str(enquiry.id), "options": len(done),
                                         "tried": enquiry.quotes_tried})
    if get_setting("enquiry_auto_send"):
        try:
            send_options(enquiry)
        except CannotSend as e:
            move(enquiry, Enquiry.Step.AWAITING_APPROVAL, str(e))


def first_photo_url(listing):
    """The car's first photo, from the public page's address (where photos are stored names the platform)."""
    position = listing.photos.exclude(image="").order_by("position").values_list("position", flat=True).first()
    if position is None:
        return ""
    return f"{settings.PUBLIC_SITE_URL}/api/public/cars/{link_for(listing).token}/photos/{position}?size=thumb"


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
