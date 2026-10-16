"""The real WhatsApp channel, with Meta faked. Fake numbers only (Ofcom drama range)."""

import hashlib
import hmac
import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.core.models import Event
from apps.enquiries import tasks, webhook
from apps.enquiries.models import Customer, Enquiry, EnquiryMessage
from apps.enquiries.services import engine, whatsapp

TEST_PHONE = "+447700900321"  # a "test number"
OTHER_PHONE = "+447700900654"  # someone else: on staging, never read, answered or stored
SECRET = "test-app-secret"
WA = dict(WHATSAPP_PROVIDER="meta", WHATSAPP_ACCESS_TOKEN="EAA-test-token", WHATSAPP_PHONE_NUMBER_ID="111", WHATSAPP_APP_SECRET=SECRET,
          WHATSAPP_VERIFY_TOKEN="verify-me", WHATSAPP_BUSINESS_NUMBER="+447700900100",
          WHATSAPP_TEST_NUMBERS=[TEST_PHONE], WHATSAPP_REAL_CUSTOMERS=False, PUBLIC_SITE_URL="https://hub.example")


def call(*messages, phone_number_id="111"):
    return {"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "messages", "value": {
        "metadata": {"phone_number_id": phone_number_id}, "messages": list(messages)}}]}]}


def text(wamid, phone, body):
    return {"id": wamid, "from": phone.lstrip("+"), "type": "text", "text": {"body": body}}


class FakeMeta:
    def __init__(self):
        self.sent = []

    def post(self, url, headers=None, json=None, timeout=None):
        auth = {"auth": headers["Authorization"]} if "Authorization" in headers else {}
        self.sent.append({"url": url, **auth, **json})
        return mock.Mock(ok=True, status_code=200, content=b"x",
                         json=lambda: {"messages": [{"id": f"wamid.out{len(self.sent)}"}]})


@override_settings(**WA)
class WhatsAppTests(TestCase):
    def setUp(self):
        cache.clear()
        self.meta = FakeMeta()
        for target, name, value in ((whatsapp.requests, "post", self.meta.post),
                                    (webhook, "handle", lambda m: tasks.whatsapp_inbound(m["phone"], m["text"], m["id"])),
                                    (engine, "wait_then_ask_purpose", lambda *_: None),
                                    (engine, "start_preparing", lambda *_: None),
                                    (whatsapp, "pump_later", lambda *_: None)):
            patch = mock.patch.object(target, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def deliver(self, payload, secret=SECRET):
        body = json.dumps(payload).encode()
        signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post("/api/whatsapp/webhook", body, content_type="application/json",
                                    HTTP_X_HUB_SIGNATURE_256=signature)

    def test_meta_setup_check(self):
        url = "/api/whatsapp/webhook?hub.mode=subscribe&hub.challenge=12345&hub.verify_token="
        self.assertEqual(self.client.get(url + "verify-me").content, b"12345")
        self.assertEqual(self.client.get(url + "wrong").status_code, 403)

    def test_a_customer_message_is_answered_from_the_same_business_number(self):
        with mock.patch.object(engine, "classify", return_value=("car_enquiry", 0.9, "ai")):
            response = self.deliver(call(text("wamid.in1", TEST_PHONE, "Looking for a BMW 1 Series")))
        self.assertEqual(response.status_code, 200)
        enquiry = Enquiry.objects.get()
        self.assertEqual((enquiry.channel, enquiry.business_number), ("whatsapp", "+447700900100"))
        self.assertEqual(enquiry.messages.get(direction="in").external_id, "wamid.in1")
        [sent] = self.meta.sent
        self.assertEqual(sent["url"], "https://graph.facebook.com/v21.0/111/messages")  # our number's id
        self.assertEqual((sent["to"], sent["type"], sent["auth"]), ("447700900321", "text", "Bearer EAA-test-token"))
        self.assertIn("/f/", sent["text"]["body"])  # a buyer gets the form link
        reply = enquiry.messages.get(direction="out")
        self.assertEqual((reply.delivery, reply.external_id), ("sent", "wamid.out1"))

    def test_an_unsigned_or_forged_call_is_refused(self):
        self.assertEqual(self.deliver(call(text("wamid.x", TEST_PHONE, "hi")), secret="wrong").status_code, 403)
        self.assertFalse(Customer.objects.exists())

    def test_meta_sending_the_same_message_twice_is_handled_once(self):
        payload = call(text("wamid.dup", TEST_PHONE, "Looking for a BMW 1 Series"))
        with mock.patch.object(engine, "classify", return_value=("car_enquiry", 0.9, "ai")):
            self.deliver(payload)
            self.deliver(payload)
        self.assertEqual(EnquiryMessage.objects.filter(direction="in").count(), 1)
        self.assertEqual(len(self.meta.sent), 1)

    def test_on_staging_other_numbers_are_not_read_answered_or_stored(self):
        self.deliver(call(text("wamid.real", OTHER_PHONE, "Looking for a BMW 1 Series")))
        self.assertFalse(Customer.objects.exists())
        self.assertEqual(self.meta.sent, [])
        self.assertTrue(Event.objects.filter(type="whatsapp.ignored_not_test_number").exists())

    @override_settings(WHATSAPP_REAL_CUSTOMERS=True)
    def test_production_answers_everyone(self):
        with mock.patch.object(engine, "classify", return_value=("car_enquiry", 0.9, "ai")):
            self.deliver(call(text("wamid.real", OTHER_PHONE, "Looking for a BMW 1 Series")))
        self.assertEqual(self.meta.sent[0]["to"], "447700900654")

    def test_messages_for_another_business_number_are_left_alone(self):
        self.deliver(call(text("wamid.other", TEST_PHONE, "hi"), phone_number_id="999"))
        self.assertFalse(Customer.objects.exists())

    def test_stop_suppresses_the_customer_and_closes_the_conversation(self):
        with mock.patch.object(engine, "classify", return_value=("car_enquiry", 0.9, "ai")):
            self.deliver(call(text("wamid.1", TEST_PHONE, "Looking for a BMW 1 Series")))
        self.deliver(call(text("wamid.2", TEST_PHONE, "STOP")))
        customer = Customer.objects.get()
        self.assertIsNotNone(customer.opted_out_at)
        self.assertEqual(Enquiry.objects.get().step, "closed")
        self.assertEqual(len(self.meta.sent), 1)  # nothing in answer to STOP
        # if they write again, the Hub stays quiet and a person decides
        with mock.patch.object(engine, "classify", return_value=("car_enquiry", 0.9, "ai")):
            self.deliver(call(text("wamid.3", TEST_PHONE, "Actually, any Golfs?")))
        self.assertEqual(Enquiry.objects.exclude(step="closed").get().step, "needs_person")
        self.assertEqual(len(self.meta.sent), 1)

    def test_a_car_goes_as_its_photo_with_the_message_as_caption(self):
        customer = Customer.objects.create(phone=TEST_PHONE)
        enquiry = Enquiry.objects.create(customer=customer, channel="whatsapp", intent="car_enquiry", step="chatting")
        with self.captureOnCommitCallbacks(execute=True):
            engine.say(enquiry, "1️⃣ *BMW 1 Series*", media_url="https://hub.example/api/public/cars/abc/photos/1")
        sent = self.meta.sent[0]
        self.assertEqual(sent["type"], "image")
        self.assertEqual(sent["image"], {"link": "https://hub.example/api/public/cars/abc/photos/1",
                                         "caption": "1️⃣ *BMW 1 Series*"})

    def test_a_failed_send_is_recorded_without_the_message_text(self):
        customer = Customer.objects.create(phone=TEST_PHONE)
        enquiry = Enquiry.objects.create(customer=customer, channel="whatsapp", intent="car_enquiry", step="chatting")
        refused = mock.Mock(ok=False, status_code=400, content=b"x",
                            json=lambda: {"error": {"code": 131047, "message": "Re-engagement message"}})
        with mock.patch.object(whatsapp.requests, "post", return_value=refused), \
                self.captureOnCommitCallbacks(execute=True):
            message = engine.say(enquiry, "Private words")
        message.refresh_from_db()
        self.assertEqual(message.delivery, "failed")
        event = Event.objects.get(type="whatsapp.send_failed")
        self.assertIn("131047", event.payload["error"])
        self.assertNotIn("Private words", json.dumps(event.payload))

    def test_simulator_messages_are_never_sent_to_whatsapp(self):
        customer = Customer.objects.create(phone=TEST_PHONE)
        enquiry = Enquiry.objects.create(customer=customer, channel="simulator", intent="car_enquiry", step="chatting")
        with self.captureOnCommitCallbacks(execute=True):
            engine.say(enquiry, "hello")
        self.assertEqual(self.meta.sent, [])

    @override_settings(SIMULATOR_ENABLED=True)
    def test_the_simulator_only_accepts_fake_numbers(self):
        api = APIClient()
        api.force_authenticate(get_user_model().objects.create_user("james@example.com", "a-long-test-password"))
        response = api.post("/api/sim/inbound", {"phone": "+447827000000", "text": "hi"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_with_whatsapp_connected_the_page_shows_real_conversations_only(self):
        api = APIClient()
        api.force_authenticate(get_user_model().objects.create_user("james@example.com", "a-long-test-password"))
        fake = Customer.objects.create(phone="+447700900999")
        Enquiry.objects.create(customer=fake, channel="simulator", intent="car_enquiry", step="chatting")
        real = Customer.objects.create(phone=TEST_PHONE)
        Enquiry.objects.create(customer=real, channel="whatsapp", intent="car_enquiry", step="chatting")
        data = api.get("/api/sim/enquiries?tab=bot").json()
        self.assertEqual([e["phone"] for e in data["enquiries"]], [TEST_PHONE])
        self.assertEqual(data["counts"]["bot"], 1)
        self.assertEqual(data["channel"], {"connected": True, "number": "+447700900100", "real_customers": False,
                                           "simulator": False})
        # no typing as a customer and no clearing a conversation
        self.assertEqual(api.post("/api/sim/inbound", {"phone": "+447700900999", "text": "hi"}, format="json")
                         .status_code, 404)
        self.assertEqual(api.delete(f"/api/sim/phones/{TEST_PHONE}").status_code, 404)
        self.assertTrue(Customer.objects.filter(phone=TEST_PHONE).exists())

    def test_photos_and_voice_notes_reach_the_journey_as_a_note(self):
        found = whatsapp.incoming(call({"id": "wamid.p", "from": "447700900321", "type": "image", "image": {}}))
        self.assertEqual(found, [{"id": "wamid.p", "phone": TEST_PHONE, "text": "[image sent]"}])


KAPSO = dict(WA, WHATSAPP_PROVIDER="kapso", KAPSO_API_KEY="kapso-test-key", KAPSO_WEBHOOK_SECRET="kapso-secret",
             KAPSO_API_URL="https://api.kapso.ai/meta/whatsapp/v24.0")


@override_settings(**KAPSO)
class KapsoTests(TestCase):
    """Kapso forwards Meta's API both ways: only the address, the key and the signature differ."""

    def setUp(self):
        cache.clear()
        self.meta = FakeMeta()
        for target, name, value in ((whatsapp.requests, "post", self.meta.post),
                                    (webhook, "handle", lambda m: tasks.whatsapp_inbound(m["phone"], m["text"], m["id"])),
                                    (engine, "classify", lambda *_: ("car_enquiry", 0.9, "ai")),
                                    (whatsapp, "pump_later", lambda *_: None)):
            patch = mock.patch.object(target, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def deliver(self, payload, secret="kapso-secret", event=""):
        body = json.dumps(payload).encode()
        signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()  # hex, no "sha256=" prefix
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post("/api/whatsapp/webhook", body, content_type="application/json",
                                    HTTP_X_WEBHOOK_SIGNATURE=signature, HTTP_X_IDEMPOTENCY_KEY="delivery-1",
                                    HTTP_X_WEBHOOK_EVENT=event)

    @staticmethod
    def kapso_event(wamid, phone, body, direction="inbound"):
        """Kapso's own v2 event, as its dashboard webhooks send it."""
        return {"message": {"id": wamid, "from": phone.lstrip("+"), "timestamp": "1730092800", "type": "text",
                            "text": {"body": body}, "kapso": {"direction": direction, "status": "received"}},
                "conversation": {"id": "conv_1", "phone_number": phone.lstrip("+"), "phone_number_id": "111"},
                "is_new_conversation": True, "phone_number_id": "111"}

    def test_kapso_events_from_the_dashboard_webhook(self):
        received = self.kapso_event("wamid.v2", TEST_PHONE, "Looking for a BMW 1 Series")
        self.assertEqual(self.deliver(received, event="whatsapp.message.received").status_code, 200)
        self.assertEqual(Enquiry.objects.get().messages.get(direction="in").body, "Looking for a BMW 1 Series")
        self.assertEqual(len(self.meta.sent), 1)

    def test_our_own_sent_messages_and_receipts_are_never_read_as_the_customer(self):
        for event, direction in (("whatsapp.message.sent", "outbound"), ("whatsapp.message.delivered", "outbound"),
                                 ("whatsapp.message.received", "outbound")):
            self.deliver(self.kapso_event(f"wamid.{event}", TEST_PHONE, "Our reply", direction), event=event)
        self.assertFalse(Customer.objects.exists())

    def test_a_batch_of_kapso_events(self):
        batch = {"type": "whatsapp.message.received", "batch": True, "batch_info": {},
                 "data": [self.kapso_event("wamid.b1", TEST_PHONE, "Hi"),
                          self.kapso_event("wamid.b2", TEST_PHONE, "Looking for a BMW 1 Series")]}
        with mock.patch.object(engine, "wait_then_ask_purpose"):
            self.deliver(batch, event="whatsapp.message.received")
        self.assertEqual(EnquiryMessage.objects.filter(direction="in").count(), 2)

    def test_a_forwarded_message_is_answered_through_kapso(self):
        self.assertEqual(self.deliver(call(text("wamid.k1", TEST_PHONE, "Looking for a BMW 1 Series"))).status_code, 200)
        [sent] = self.meta.sent
        self.assertEqual(sent["url"], "https://api.kapso.ai/meta/whatsapp/v24.0/111/messages")
        self.assertEqual(sent["to"], "447700900321")
        self.assertNotIn("Authorization", sent)
        self.assertEqual(Enquiry.objects.get().channel, "whatsapp")

    def test_kapso_key_goes_in_its_own_header(self):
        with mock.patch.object(whatsapp.requests, "post") as post:
            post.return_value = mock.Mock(ok=True, content=b"x", json=lambda: {"messages": [{"id": "wamid.1"}]})
            customer = Customer.objects.create(phone=TEST_PHONE)
            enquiry = Enquiry.objects.create(customer=customer, channel="whatsapp", intent="car_enquiry", step="chatting")
            with self.captureOnCommitCallbacks(execute=True):
                engine.say(enquiry, "hello")
        self.assertEqual(post.call_args.kwargs["headers"], {"X-API-Key": "kapso-test-key"})

    def test_a_call_not_signed_with_our_secret_is_refused(self):
        self.assertEqual(self.deliver(call(text("wamid.k2", TEST_PHONE, "hi")), secret="guess").status_code, 403)
        meta_style = self.client.post("/api/whatsapp/webhook", b"{}", content_type="application/json",
                                      HTTP_X_HUB_SIGNATURE_256="sha256=abc")
        self.assertEqual(meta_style.status_code, 403)
        self.assertFalse(Customer.objects.exists())


@override_settings(**WA)
class PhotoAndDeliveryTests(TestCase):
    def setUp(self):
        self.meta = FakeMeta()
        for target, name, value in ((whatsapp.requests, "post", self.meta.post), (whatsapp, "pump_later", lambda *_: None)):
            patch = mock.patch.object(target, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def test_messages_arrive_in_order_each_after_the_one_before(self):
        from datetime import timedelta

        from django.utils import timezone

        customer = Customer.objects.create(phone=TEST_PHONE)
        enquiry = Enquiry.objects.create(customer=customer, channel="whatsapp", intent="car_enquiry", step="options_sent")
        with self.captureOnCommitCallbacks(execute=True):
            engine.say(enquiry, "intro")
            engine.say(enquiry, "1️⃣ car", media_url="https://hub.example/api/public/cars/abc/photos/1")
            engine.say(enquiry, "closing line")
        self.assertEqual([m.get("text", m.get("image"))["body" if "text" in m else "caption"] for m in self.meta.sent],
                         ["intro"])  # the photo waits until the intro has arrived
        self.report("wamid.out1", "delivered")
        self.assertEqual(self.meta.sent[-1]["type"], "image")
        self.assertEqual(len(self.meta.sent), 2)  # the closing line waits for the photo
        self.report("wamid.out2", "delivered")
        self.assertEqual(self.meta.sent[-1]["text"]["body"], "closing line")
        # no report at all: after the wait the next message goes anyway
        with self.captureOnCommitCallbacks(execute=True):
            engine.say(enquiry, "later")
        EnquiryMessage.objects.filter(body="closing line").update(delivery_at=timezone.now() - timedelta(seconds=16))
        whatsapp.pump(enquiry.id)
        self.assertEqual(self.meta.sent[-1]["text"]["body"], "later")

    def test_the_car_photo_sent_is_the_full_jpeg_never_the_webp_thumbnail(self):
        from apps.listings.models import ListingPhoto

        from .test_journey import car

        listing = car(1)
        ListingPhoto.objects.create(listing=listing, position=1, source_url="https://img.test/1.webp",
                                    image="listings/x/01.webp", thumbnail="listings/x/thumbs/01.webp")
        ListingPhoto.objects.create(listing=listing, position=2, source_url="https://img.test/2.jpg",
                                    image="listings/x/02.jpg", thumbnail="listings/x/thumbs/02.webp")
        url = engine.first_photo_url(listing)
        self.assertRegex(url, r"^https://hub\.example/api/public/cars/[\w-]+/photos/2$")  # no ?size=thumb
        ListingPhoto.objects.filter(position=2).delete()
        self.assertEqual(engine.first_photo_url(listing), "")  # WebP only: the car goes as text

    def report(self, wamid, status, errors=None):
        payload = call()
        value = payload["entry"][0]["changes"][0]["value"]
        value["messages"] = []
        value["statuses"] = [{"id": wamid, "status": status, "recipient_id": "447700900321",
                              **({"errors": errors} if errors else {})}]
        body = json.dumps(payload).encode()
        signature = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
        return self.client.post("/api/whatsapp/webhook", body, content_type="application/json",
                                HTTP_X_HUB_SIGNATURE_256=signature)

    def test_meta_reports_delivered_read_and_failed(self):
        customer = Customer.objects.create(phone=TEST_PHONE)
        enquiry = Enquiry.objects.create(customer=customer, channel="whatsapp", intent="car_enquiry", step="options_sent")
        ok = EnquiryMessage.objects.create(enquiry=enquiry, direction="out", sender="bot", body="hi",
                                           external_id="wamid.ok", delivery="sent")
        photo = EnquiryMessage.objects.create(enquiry=enquiry, direction="out", sender="bot", body="1️⃣ car",
                                              external_id="wamid.photo", delivery="sent")
        self.report("wamid.ok", "read")
        self.report("wamid.ok", "delivered")  # arrives late: never moves a message backwards
        self.report("wamid.photo", "failed", [{"code": 131053, "title": "Media upload error"}])
        ok.refresh_from_db()
        photo.refresh_from_db()
        self.assertEqual((ok.delivery, photo.delivery), ("read", "failed"))
        event = Event.objects.get(type="whatsapp.send_failed")
        self.assertEqual(event.payload["error"], "131053 Media upload error")
        self.assertFalse(Customer.objects.exclude(pk=customer.pk).exists())  # a report is never a customer message
