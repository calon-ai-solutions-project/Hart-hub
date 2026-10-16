"""/api/whatsapp/webhook: Kapso's Meta webhook (or Meta itself) calls this.

GET  Meta only, once, when the webhook is set up: we answer the challenge if the verify token matches.
POST every customer message and delivery receipt, in Meta's format. Only correctly signed calls are read. Each
     message is handled once (retries are dropped) and in the background, so the caller gets its 200 at once.
"""

import json
import threading

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.http import HttpResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from apps.core.services import emit_event

from .services import whatsapp

SEEN_FOR = 3 * 24 * 3600  # Meta retries a call for up to a few days


@csrf_exempt
@require_http_methods(["GET", "POST"])
def webhook(request):
    if request.method == "GET":
        if (request.GET.get("hub.mode") == "subscribe" and settings.WHATSAPP_VERIFY_TOKEN
                and request.GET.get("hub.verify_token") == settings.WHATSAPP_VERIFY_TOKEN):
            return HttpResponse(request.GET.get("hub.challenge", ""), content_type="text/plain")
        return HttpResponseForbidden("Verify token does not match.")

    if not whatsapp.signature_ok(request.body, request.headers):
        emit_event("whatsapp.bad_signature", {})
        return HttpResponseForbidden("Bad signature.")
    try:
        payload = json.loads(request.body)
    except ValueError:
        return HttpResponse(status=400)
    for report in whatsapp.statuses(payload):  # delivered, read, or failed after Meta accepted it
        whatsapp.record_status(report)
    for message in whatsapp.incoming(payload, request.headers.get("X-Webhook-Event", "")):
        if not cache.add(f"wa-seen:{message['id']}", 1, SEEN_FOR):
            continue  # already handled: Meta sent it again
        if not whatsapp.allowed(message["phone"]):
            # staging: a real customer's message is not read, answered or stored (only that one arrived)
            emit_event("whatsapp.ignored_not_test_number", {})
            continue
        handle(message)
    return HttpResponse("ok")


def handle(message):
    args = (message["phone"], message["text"], message["id"])
    if settings.CELERY_TASK_ALWAYS_EAGER:  # no worker (local): a thread, so Meta is answered at once
        threading.Thread(target=_on_thread, args=args, daemon=True).start()
    else:
        from .tasks import whatsapp_inbound

        whatsapp_inbound.delay(*args)


def _on_thread(*args):
    from .tasks import whatsapp_inbound

    try:
        whatsapp_inbound(*args)
    finally:
        connection.close()
