"""The real WhatsApp channel: Meta's WhatsApp Cloud API, through Kapso (kapso.ai) or straight from Meta.

Kapso forwards Meta's API both ways unchanged, so only the address, the key and the webhook signature differ:
- kapso: send to KAPSO_API_URL with X-API-Key; its "Meta webhook" forwards Meta's payload, signed with our
  secret_key (X-Webhook-Signature: hex HMAC-SHA256 of the raw body).
- meta:  send to the Graph API with a Bearer token; Meta signs with the app secret (X-Hub-Signature-256: sha256=...).

In: each customer message is checked, then goes to the same journey engine as the simulator. Out: every message the Hub saves for a WhatsApp enquiry is delivered from
the business number the customer messaged.

Staging never talks to real customers: unless WHATSAPP_REAL_CUSTOMERS is on, only WHATSAPP_TEST_NUMBERS are read
and answered, and nothing about anyone else is stored. Credentials come only from environment variables; message
text is never logged.
"""

import hashlib
import hmac
import logging

import requests
from django.conf import settings

from apps.core.services import emit_event

logger = logging.getLogger(__name__)


def kapso():
    return settings.WHATSAPP_PROVIDER == "kapso"


def enabled():
    key = settings.KAPSO_API_KEY if kapso() else settings.WHATSAPP_ACCESS_TOKEN
    return bool(key and settings.WHATSAPP_PHONE_NUMBER_ID)


def api_url(path=""):
    base = settings.KAPSO_API_URL if kapso() else settings.WHATSAPP_GRAPH_URL
    return f"{base}/{settings.WHATSAPP_PHONE_NUMBER_ID}{path}"


def auth_headers():
    if kapso():
        return {"X-API-Key": settings.KAPSO_API_KEY}
    return {"Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}"}


def simulator_on():
    """The portal's simulator: on when switched on, else only while WhatsApp is not connected."""
    if settings.SIMULATOR_ENABLED is not None:
        return settings.SIMULATOR_ENABLED
    return not enabled()


def channel():
    """What the WhatsApp page shows about the channel."""
    return {"connected": enabled(), "number": settings.WHATSAPP_BUSINESS_NUMBER if enabled() else "",
            "real_customers": bool(settings.WHATSAPP_REAL_CUSTOMERS), "simulator": simulator_on()}


def digits(phone):
    return "".join(ch for ch in str(phone or "") if ch.isdigit())


def allowed(phone):
    """May the Hub read and answer this number? Everyone in production; only the test numbers elsewhere."""
    if settings.WHATSAPP_REAL_CUSTOMERS:
        return True
    return digits(phone) in {digits(n) for n in settings.WHATSAPP_TEST_NUMBERS if digits(n)}


def signature_ok(body, headers):
    """Is this webhook call really from Kapso (or Meta)? An HMAC-SHA256 of the raw body with our secret."""
    if kapso():
        secret, given = settings.KAPSO_WEBHOOK_SECRET, headers.get("X-Webhook-Signature", "")
    else:
        secret, given = settings.WHATSAPP_APP_SECRET, headers.get("X-Hub-Signature-256", "")
        if not given.startswith("sha256="):
            return False
        given = given.removeprefix("sha256=")
    if not secret or not given:
        return False
    return hmac.compare_digest(hmac.new(secret.encode(), body, hashlib.sha256).hexdigest(), given.strip().lower())


KAPSO_RECEIVED = "whatsapp.message.received"


def text_of(message):
    """What the customer said; a photo or voice note becomes a short note so the journey still sees it."""
    kind = message.get("type")
    if kind == "text":
        return (message.get("text") or {}).get("body", "")
    if kind == "button":
        return (message.get("button") or {}).get("text", "")
    if kind == "interactive":
        reply = message.get("interactive") or {}
        return (reply.get("button_reply") or reply.get("list_reply") or {}).get("title", "")
    return f"[{kind or 'message'} sent]"  # image, audio, video, document, sticker, location...


def incoming(payload, event=""):
    """Customer messages in a webhook call: [{"id", "phone" (E.164), "text"}].

    Two formats: Meta's (also what a Kapso "Meta" webhook forwards), and Kapso's own v2 events (one event, or a
    batch). Only messages received from customers on our number count: Kapso also reports the messages we send,
    deliveries and reads, and those must never be read as a customer speaking.
    """
    payload = payload or {}
    found = []
    if "entry" in payload:  # Meta's format
        for entry in payload.get("entry") or []:
            for change in entry.get("changes") or []:
                value = change.get("value") or {}
                if (value.get("metadata") or {}).get("phone_number_id") != settings.WHATSAPP_PHONE_NUMBER_ID:
                    continue
                for message in value.get("messages") or []:
                    found.append((message, message.get("from")))
    elif event == KAPSO_RECEIVED:  # Kapso v2: one event, or a batch of them
        for item in payload.get("data") or [] if payload.get("batch") else [payload]:
            message = item.get("message") or {}
            conversation = item.get("conversation") or {}
            number_id = item.get("phone_number_id") or conversation.get("phone_number_id")
            direction = (message.get("kapso") or {}).get("direction", "inbound")
            if str(number_id) != settings.WHATSAPP_PHONE_NUMBER_ID or direction != "inbound":
                continue
            found.append((message, message.get("from") or conversation.get("phone_number")))
    messages = []
    for message, sender in found:
        text = text_of(message)
        if message.get("id") and sender and text.strip():
            messages.append({"id": message["id"], "phone": "+" + digits(sender), "text": text})
    return messages


def send(message):
    """Deliver one saved Hub message. Records the outcome on the message; never raises."""
    from ..models import EnquiryMessage

    enquiry = message.enquiry
    phone = enquiry.customer.phone
    if not enabled() or not allowed(phone) or enquiry.customer.opted_out_at:
        EnquiryMessage.objects.filter(pk=message.pk).update(delivery="skipped")
        return False
    if message.media_url:  # a car: its photo with the message as the caption
        body = {"type": "image", "image": {"link": message.media_url, "caption": message.body[:1024]}}
    else:
        body = {"type": "text", "text": {"body": message.body[:4096], "preview_url": True}}
    try:
        response = requests.post(
            api_url("/messages"),
            headers=auth_headers(),
            json={"messaging_product": "whatsapp", "recipient_type": "individual", "to": digits(phone), **body},
            timeout=20,
        )
        data = response.json() if response.content else {}
        if not response.ok:
            error = data.get("error") or {}
            raise requests.HTTPError(f"{response.status_code} {error.get('code', '')} {error.get('message', '')}")
        wamid = ((data.get("messages") or [{}])[0]).get("id", "")
    except (requests.RequestException, ValueError) as e:
        EnquiryMessage.objects.filter(pk=message.pk).update(delivery="failed")
        logger.warning("WhatsApp send failed for enquiry %s: %s", enquiry.id, str(e)[:200])
        emit_event("whatsapp.send_failed", {"enquiry_id": str(enquiry.id), "message_id": str(message.id),
                                            "error": str(e)[:200]})
        return False
    EnquiryMessage.objects.filter(pk=message.pk).update(delivery="sent", external_id=wamid[:128])
    return True


def check():
    """Ask about the configured number: proves the key and phone number ID work. Sends nothing."""
    response = requests.get(
        api_url(),
        headers=auth_headers(),
        params={"fields": "display_phone_number,verified_name,quality_rating,code_verification_status"},
        timeout=20,
    )
    data = response.json()
    if not response.ok:
        error = data.get("error") or {}
        raise RuntimeError(f"{settings.WHATSAPP_PROVIDER.title()} said {response.status_code}: {error.get('message', 'unknown error')}")
    return data
