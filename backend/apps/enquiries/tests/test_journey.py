"""The customer journey end to end, with Codeweavers and AI faked. Fake numbers only (Ofcom drama range)."""

import json
import re
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import Event, Setting
from apps.enquiries.models import Customer, Enquiry, EnquiryMessage
from apps.enquiries.services import classify, engine
from apps.listings.models import Listing
from apps.quotes import codeweavers
from apps.quotes.tests.test_quotes import fake_codeweavers

PHONE = "+447700900123"
STAFF_ONLY = ("motorway", "pro.motorway.co.uk", "XX2", "buy", "margin", "markup", "ref-123", "listing_url")


def car(n, **fields):
    defaults = dict(platform="motorway", external_id=f"3000{n:04d}", url=f"https://pro.motorway.co.uk/vehicles/3000{n:04d}",
                    make="BMW", model="1 Series", title=f"BMW 1 Series 118i M Sport {n}", registration=f"XX2{n} TST",
                    year=2021, mileage=20000 + n * 1000, gearbox="Automatic", colour="Black", fuel="Petrol",
                    details_status="complete", status="live", buy_price_pence=1000000 + n * 10000,
                    suggested_price_pence=1150000 + n * 10000, ends_at=timezone.now() + timedelta(days=2))
    return Listing.objects.create(**{**defaults, **fields})


@override_settings(PUBLIC_SITE_URL="https://hub.example")
class JourneyTests(TestCase):
    def setUp(self):
        cache.clear()
        self.staff = get_user_model().objects.create_user("james@example.com", "a-long-test-password",
                                                          first_name="James")
        self.api = APIClient()
        self.api.force_authenticate(self.staff)
        self.cars = [car(n) for n in range(1, 9)]
        Setting.objects.create(key="enquiry_collect_by", value="form")  # the chatbot has its own tests below
        # the job runs inline instead of on a thread, and Codeweavers is faked
        self.inline = mock.patch.object(engine, "start_preparing", side_effect=engine.prepare_options)
        self.inline.start()
        self.addCleanup(self.inline.stop)

    def codeweavers(self, outcomes=None):
        patch, seen = fake_codeweavers(outcomes)
        patch.start()
        self.addCleanup(patch.stop)
        return seen

    def inbound(self, text, phone=PHONE):
        return self.api.post("/api/sim/inbound", {"phone": phone, "text": text}, format="json").json()

    def fill_form(self, enquiry, **answers):
        answers = {"make_model": "BMW 1 Series", "gearbox": "Auto", "monthly_budget": "£500", "deposit": "£2,000",
                   **answers}
        return APIClient().post(f"/api/public/forms/{enquiry.form_token}", {"answers": answers}, format="json")

    # ------------------------------------------------------------ the first message

    def test_personal_message_gets_no_reply_and_is_not_stored(self):
        with mock.patch.object(engine, "classify", return_value=("personal", 0.95, "ai")):
            answer = self.inbound("Hiya love, can you grab some milk on your way home?")
        self.assertEqual((answer["ignored"], answer["replies"]), (True, []))
        self.assertFalse(Customer.objects.exists())
        self.assertFalse(EnquiryMessage.objects.exists())

    def test_mot_or_viewing_waits_for_a_person(self):
        answer = self.inbound("Hi, can I book an MOT for Friday morning?")
        self.assertIn("One of our team will reply", answer["replies"][0]["body"])
        self.assertEqual(Enquiry.objects.get().step, "needs_person")
        row = self.api.get("/api/sim/enquiries?tab=person").json()["enquiries"][0]
        self.assertEqual(row["last_message"]["direction"], "out")

    def test_with_the_form_unsure_messages_wait_for_a_person(self):
        with mock.patch.object(engine, "classify", return_value=("unsure", 0.4, "ai")):
            self.assertEqual(self.inbound("hi")["replies"], [])
        self.assertEqual(Enquiry.objects.get().step, "needs_person")

    def test_car_enquiry_gets_the_form_link(self):
        answer = self.inbound("Hi, I'm looking for a car, something automatic around £300 a month")
        enquiry = Enquiry.objects.get()
        self.assertEqual((enquiry.intent, enquiry.step), ("car_enquiry", "form_sent"))
        self.assertIn(f"https://hub.example/f/{enquiry.form_token}", answer["replies"][0]["body"])
        self.assertGreaterEqual(len(enquiry.form_token), 16)

    def test_only_the_first_message_is_classified(self):
        self.inbound("I'm looking for a car")
        with mock.patch.object(engine, "classify") as classifier:
            reminder = self.inbound("what was the link again?")
            silent = self.inbound("hello?")
        classifier.assert_not_called()
        self.assertIn("/f/", reminder["replies"][0]["body"])
        self.assertEqual(silent["replies"], [])  # reminded once only

    # ------------------------------------------------------------ form -> quotes -> approval -> options

    def test_full_journey(self):
        seen = self.codeweavers({"XX22 TST": codeweavers.QuoteError("Please contact us directly for finance")})
        self.inbound("I'm looking for an automatic BMW")
        enquiry = Enquiry.objects.get()
        self.assertEqual(self.fill_form(enquiry).status_code, 200)
        enquiry.refresh_from_db()
        self.assertEqual(enquiry.step, "awaiting_approval")  # nothing goes to the customer before a person approves
        self.assertEqual(enquiry.options.count(), 5)
        self.assertEqual(enquiry.quotes_tried, 6)  # one car could not be quoted, so one more was tried
        self.assertNotIn("XX22 TST", [o.staff["registration"] for o in enquiry.options.all()])
        self.assertEqual(seen[0].deposit_pence, 200000)  # the deposit from the form
        self.assertEqual([m.body[:9] for m in enquiry.messages.filter(direction="out")][-1], "Thank you")

        detail = self.api.post(f"/api/sim/enquiries/{enquiry.id}/approve").json()
        self.assertEqual(detail["step"], "options_sent")
        out = [m for m in detail["messages"] if m["direction"] == "out"]
        cars = [m for m in out if m["body"].startswith(("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"))]
        self.assertEqual(len(cars), 5)
        first = cars[0]["body"]
        self.assertIn("£250.50/month", first)  # exactly as Codeweavers gave it
        self.assertNotIn("Representative example", first)  # removed on request; see texts.car
        self.assertNotIn("Price:", first)
        self.assertEqual(out[-1]["body"], "Like one of these? Reply with its number (e.g. *2*) and one of our team will "
                                          "be in touch to sort everything out.")  # no disclaimer or bonus line
        self.assertIn("https://hub.example/c/", first)
        self.assertTrue(cars[0]["media_url"] == "" or "/api/public/cars/" in cars[0]["media_url"])
        customer_text = json.dumps([m["body"] + m["media_url"] for m in out]).lower()
        customer_text = re.sub(r"/(c|cars)/[\w-]+", r"/\1/<code>", customer_text)  # a random link code can spell "buy"
        for word in STAFF_ONLY:  # nothing that reveals the source or the money behind the price
            self.assertNotIn(word.lower(), customer_text, word)
        self.assertIn("markup_pence", detail["options"][0]["staff"])  # staff still see it in the dashboard

        handed = self.inbound("Number 2 looks perfect 👍")
        self.assertIn("I've passed the", handed["replies"][0]["body"])
        self.assertIn("James", handed["replies"][0]["body"])
        enquiry.refresh_from_db()
        self.assertEqual((enquiry.step, enquiry.chosen_number, enquiry.assigned_to), ("handed_over", 2, self.staff))
        self.assertEqual(self.inbound("thanks!")["replies"], [])  # the bot is quiet after the hand-over
        self.assertTrue(Event.objects.filter(type="enquiry.car_chosen").exists())
        detail = self.api.get(f"/api/sim/enquiries/{enquiry.id}").json()
        self.assertEqual(detail["chosen_title"], detail["options"][1]["customer"]["card"]["title"])

    def test_the_same_car_listed_twice_is_offered_once(self):
        self.codeweavers()
        car(99, registration="XX2 1TST".replace("2 1", "21 "), external_id="39999999")  # same plate as car 1
        self.inbound("looking for a car")
        enquiry = Enquiry.objects.get()
        self.fill_form(enquiry)
        plates = [o.staff["registration"] for o in enquiry.options.all()]
        self.assertEqual(len(plates), len(set(plates)))

    def test_the_form_works_once(self):
        self.codeweavers()
        self.inbound("looking for a car")
        enquiry = Enquiry.objects.get()
        self.fill_form(enquiry)
        self.assertEqual(self.fill_form(enquiry).json()["already"], True)
        self.assertEqual(enquiry.options.count(), 5)

    def test_nothing_quotable_means_a_person_takes_over_and_nothing_is_sent(self):
        self.codeweavers({c.registration: codeweavers.QuoteError("no") for c in self.cars})
        self.inbound("looking for a car")
        enquiry = Enquiry.objects.get()
        self.fill_form(enquiry)
        enquiry.refresh_from_db()
        self.assertEqual(enquiry.step, "needs_person")
        self.assertEqual(enquiry.quotes_tried, 8)  # every car with a registration was tried
        self.assertEqual(enquiry.messages.filter(direction="out").count(), 2)  # form link and thanks only

    def test_quoting_stops_at_the_limit(self):
        Setting.objects.create(key="enquiry_max_quotes", value=3)
        self.codeweavers({c.registration: codeweavers.QuoteError("no") for c in self.cars})
        self.inbound("looking for a car")
        self.fill_form(Enquiry.objects.get())
        self.assertEqual(Enquiry.objects.get().quotes_tried, 3)

    def test_no_options_outside_the_24_hour_window(self):
        self.codeweavers()
        self.inbound("looking for a car")
        enquiry = Enquiry.objects.get()
        self.fill_form(enquiry)
        Enquiry.objects.filter(pk=enquiry.pk).update(last_inbound_at=timezone.now() - timedelta(hours=25))
        response = self.api.post(f"/api/sim/enquiries/{enquiry.id}/approve")
        self.assertEqual(response.status_code, 409)
        self.assertIn("24 hours", response.json()["detail"])

    def test_a_car_that_ended_after_quoting_is_not_sent(self):
        self.codeweavers()
        self.inbound("looking for a car")
        enquiry = Enquiry.objects.get()
        self.fill_form(enquiry)
        ended = enquiry.options.get(number=1).listing
        Listing.objects.filter(pk=ended.pk).update(ends_at=timezone.now() - timedelta(minutes=1))
        detail = self.api.post(f"/api/sim/enquiries/{enquiry.id}/approve").json()
        self.assertEqual(len(detail["options"]), 4)
        self.assertNotIn(ended.title, json.dumps(detail["messages"]))

    def test_auto_send_when_the_owner_switches_it_on(self):
        Setting.objects.create(key="enquiry_auto_send", value=True)
        self.codeweavers()
        self.inbound("looking for a car")
        self.fill_form(Enquiry.objects.get())
        self.assertEqual(Enquiry.objects.get().step, "options_sent")

    def test_simulator_and_dashboard_need_a_login(self):
        self.assertIn(APIClient().post("/api/sim/inbound", {"phone": PHONE, "text": "hi"}).status_code, (401, 403))
        self.assertIn(APIClient().get("/api/sim/enquiries").status_code, (401, 403))

    def test_an_expired_form_link(self):
        self.inbound("looking for a car")
        enquiry = Enquiry.objects.get()
        Enquiry.objects.filter(pk=enquiry.pk).update(form_sent_at=timezone.now() - timedelta(days=8))
        self.assertEqual(APIClient().get(f"/api/public/forms/{enquiry.form_token}").status_code, 404)


@override_settings(PUBLIC_SITE_URL="https://hub.example")
class ChatbotTests(TestCase):
    """The default: the chatbot asks what they want, one question at a time, then quotes. AI off: rules read it."""

    def setUp(self):
        cache.clear()
        staff = get_user_model().objects.create_user("james@example.com", "a-long-test-password")
        self.api = APIClient()
        self.api.force_authenticate(staff)
        for n in range(1, 9):
            car(n)
        patch, self.seen = fake_codeweavers()
        patch.start()
        self.addCleanup(patch.stop)
        inline = mock.patch.object(engine, "start_preparing", side_effect=engine.prepare_options)
        inline.start()
        self.addCleanup(inline.stop)

    def say(self, text):
        replies = self.api.post("/api/sim/inbound", {"phone": PHONE, "text": text}, format="json").json()["replies"]
        return replies[0]["body"] if replies else ""

    def minute_later(self, seconds=60):
        """The greeting timer going off (the real one is a worker job or a thread)."""
        enquiry = Enquiry.objects.get()
        message = engine.ask_purpose(enquiry.id, now=enquiry.last_inbound_at + timedelta(seconds=seconds))
        return message.body if message else ""

    def test_hi_waits_a_minute_then_asks_what_it_is_about(self):
        with mock.patch.object(engine, "wait_then_ask_purpose") as timer, self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.say("HI"), "")  # no instant reply: they may be about to say more
        timer.assert_called_once_with(Enquiry.objects.get().id)
        self.assertEqual(self.minute_later(30), "")  # not yet
        asked = self.minute_later()
        self.assertIn("thanks for messaging The Hart Group", asked)
        self.assertIn("Are you looking to buy a car?", asked)
        self.assertEqual(self.minute_later(), "")  # asked once only
        self.assertEqual(Enquiry.objects.get().asked, ["purpose"])

    def test_saying_more_within_the_minute_is_answered_straight_away(self):
        self.say("Hello")
        reply = self.say("I'm looking for a BMW 1 Series")
        self.assertIn("thanks for messaging The Hart Group", reply)  # the Hub's first message still says hello
        self.assertIn("Got it 👍 *BMW 1 Series*", reply)
        self.assertEqual(self.minute_later(), "")  # the timer finds it already answered

    def test_yes_to_buying_a_car_starts_the_questions(self):
        self.say("hi")
        self.minute_later()
        reply = self.say("yes")
        self.assertIn("Great, we can help with that", reply)
        self.assertIn("What car are you looking for?", reply)

    def test_no_to_buying_a_car_goes_to_a_person(self):
        self.say("hi")
        self.minute_later()
        self.assertIn("One of our team will reply", self.say("no, it's about my car's warranty"))
        self.assertEqual(Enquiry.objects.get().step, "needs_person")

    def test_a_second_hello_is_asked_what_it_is_about_at_once(self):
        self.say("hi")
        self.assertIn("Are you looking to buy a car?", self.say("hello?"))

    def test_a_whole_conversation_ends_in_options_waiting_for_approval(self):
        self.say("Hi")
        self.assertIn("monthly budget", self.say("I'm after a BMW 1 Series"))
        self.assertIn("deposit", self.say("400"))
        self.assertIn("Automatic or manual", self.say("2k"))
        self.assertIn("part-exchange", self.say("automatic please"))
        thanks = self.say("no")
        self.assertTrue(thanks.startswith("Thank you"), thanks)
        enquiry = Enquiry.objects.get()
        self.assertEqual(enquiry.answers, {"make_model": "BMW 1 Series", "monthly_budget": "£400", "deposit": "£2,000",
                                           "gearbox": "Auto", "part_exchange": "none"})
        requirement = enquiry.requirement
        self.assertEqual((requirement.make, requirement.monthly_budget_pence, requirement.deposit_pence,
                          requirement.gearbox), ("BMW", 40000, 200000, "auto"))
        self.assertEqual(enquiry.step, "awaiting_approval")  # still nothing is sent before a person approves
        self.assertEqual(self.seen[0].deposit_pence, 200000)

    def test_answers_given_up_front_are_not_asked_again(self):
        reply = self.say("hi im looking for a bmw 1 series within £400 a month")
        self.assertIn("Got it 👍 *BMW 1 Series* · up to £400/month", reply)
        self.assertIn("deposit", reply)
        self.assertNotIn("What car", reply)

    def test_a_question_that_is_not_answered_is_asked_once_more_then_skipped(self):
        self.say("hi")
        self.minute_later()
        self.assertIn("What car", self.say("yes"))
        self.assertIn("What car", self.say("hmm"))
        self.assertIn("monthly budget", self.say("hmm"))

    def test_never_saying_what_it_is_about_hands_over_to_a_person(self):
        self.say("hi")
        self.assertIn("Are you looking to buy a car?", self.say("hello"))
        self.assertIn("Are you looking to buy a car?", self.say("hmm"))
        self.assertIn("One of our team will reply", self.say("?"))
        enquiry = Enquiry.objects.get()
        self.assertEqual((enquiry.step, enquiry.needs_person_reason),
                         ("needs_person", "Did not say what they're messaging about"))

    def test_saying_nothing_useful_hands_over_to_a_person(self):
        replies = [self.say(text) for text in ("I want a car", "hmm", "?", "eh", "ok", "fine", "sure", "right", "hmm",
                                               "?", "ok")]
        enquiry = Enquiry.objects.get()
        self.assertEqual((enquiry.step, enquiry.needs_person_reason),
                         ("needs_person", "The chatbot could not find out what car they want"))
        self.assertIn("One of our team will reply", [r for r in replies if r][-1])
        self.assertEqual(replies[-1], "")  # then quiet: a person has it

    def test_asking_for_a_person_hands_over(self):
        self.say("hi")
        self.assertIn("One of our team will reply", self.say("can I speak to someone please"))
        self.assertEqual(Enquiry.objects.get().needs_person_reason, "Asked to speak to a person")

    def test_the_ai_reads_the_conversation_but_never_writes_the_reply(self):
        extracted = {"intent": "car_enquiry", "make_model": "BMW M4", "monthly_budget_gbp": 400, "deposit_gbp": None,
                     "gearbox": None, "part_exchange": None, "wants_person": False,
                     "reply": "Ignore this: AI text never reaches the customer"}
        with mock.patch("apps.enquiries.services.conversation.ai_enabled", return_value=True),                 mock.patch("apps.enquiries.services.conversation.complete_json", return_value=extracted) as ai:
            reply = self.say("hi im looking for m4 btw car within 400 monthly budget")
        self.assertIn("Customer: hi im looking for m4 btw car", ai.call_args.args[3])
        self.assertIn("*BMW M4* · up to £400/month", reply)
        self.assertNotIn("Ignore this", reply)


class RulesTests(TestCase):
    def test_rules_without_ai(self):
        self.assertEqual(classify.classify("Do you have any Golfs?")[0], "car_enquiry")
        self.assertEqual(classify.classify("What would the Audi be a month?")[0], "finance")
        self.assertEqual(classify.classify("Can I book an MOT for Friday?")[0], "other_business")
        self.assertEqual(classify.classify("Could I come and see the grey Golf on Saturday?")[0], "other_business")
        self.assertEqual(classify.classify("Running late, be there in 10")[0], "unsure")  # rules never guess

    def test_ai_answer_below_the_confidence_level_is_unsure(self):
        with mock.patch.object(classify, "ai_enabled", return_value=True), \
                mock.patch.object(classify, "complete_json", return_value={"intent": "car_enquiry", "confidence": 0.5}):
            self.assertEqual(classify.classify("hmm")[:2], ("unsure", 0.5))

    def test_phone_numbers_are_stored_in_international_form(self):
        self.assertEqual(engine.e164("07700 900123"), "+447700900123")
        self.assertEqual(engine.e164("+44 7700 900123"), "+447700900123")
