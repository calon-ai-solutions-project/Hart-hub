"""The conversational chatbot: AI writes the replies, code checks every one. AI is faked. Fake numbers only."""

import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.ai.client import AiUnavailable
from apps.core.models import Event
from apps.enquiries.models import Enquiry
from apps.enquiries.services import conversation, engine
from apps.quotes.tests.test_quotes import fake_codeweavers

from .test_journey import PHONE, STAFF_ONLY, car


def ai(reply="", intent="car_enquiry", ready=False, wants_person=False, **fields):
    return {"intent": intent, "make_model": None, "monthly_budget_gbp": None, "deposit_gbp": None, "gearbox": None,
            "part_exchange": None, "colour": None, "needed_by": None, "wants_person": wants_person, "ready": ready,
            "reply": reply, **fields}


@override_settings(PUBLIC_SITE_URL="https://hub.example")
class ConversationalTests(TestCase):
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
        for target, value in ((engine, "ai_enabled"), (engine, "start_preparing")):
            p = mock.patch.object(target, value, **({"return_value": True} if value == "ai_enabled"
                                                   else {"side_effect": engine.prepare_options}))
            p.start()
            self.addCleanup(p.stop)
        self.answers = []  # what the fake AI returns, one per call
        p = mock.patch.object(conversation, "complete_json", side_effect=lambda *a, **k: self.answers.pop(0))
        self.calls = p.start()
        self.addCleanup(p.stop)

    def say(self, text, *answers):
        self.answers.extend(answers)
        with mock.patch.object(engine, "classify", return_value=("car_enquiry", 0.9, "ai")):
            replies = self.api.post("/api/sim/inbound", {"phone": PHONE, "text": text}, format="json").json()["replies"]
        return replies[0]["body"] if replies else ""

    def test_the_ai_writes_the_reply_and_code_keeps_the_answers(self):
        reply = self.say("hi im looking for m4 btw car within 400 monthly budget",
                         ai("Nice choice! A BMW M4 with a budget of £400 a month. How much could you put down as a "
                            "deposit?", make_model="BMW M4", monthly_budget_gbp=400))
        self.assertEqual(reply, "Nice choice! A BMW M4 with a budget of £400 a month. How much could you put down "
                                "as a deposit?")
        enquiry = Enquiry.objects.get()
        self.assertEqual((enquiry.step, enquiry.answers), ("chatting", {"make_model": "BMW M4", "monthly_budget": "£400"}))
        sent = json.loads(self.calls.call_args.args[3].split("\n\nCONVERSATION:")[0])
        self.assertEqual(sent["STILL NEEDED"], ["make_model", "monthly_budget", "deposit", "gearbox", "part_exchange"])
        self.assertEqual(self.calls.call_args.kwargs["temperature"], 0.4)

    def test_a_finance_figure_the_customer_did_not_give_is_never_sent(self):
        for invented in ("That would be about £289/month on PCP.", "Rates start from 6.9% APR!",
                         "You'll definitely be approved 👍", "We have it in stock now!",
                         "Have a look at https://example.com", "Call us on 01234 567890"):
            Enquiry.objects.all().delete()
            reply = self.say("looking for a golf", ai(invented, make_model="Volkswagen Golf"))
            self.assertNotEqual(reply, invented)
            self.assertIn("monthly budget", reply)  # the scripted question instead
        self.assertEqual(Event.objects.filter(type="enquiry.ai_reply_blocked").count(), 6)

    def test_the_customers_own_budget_may_be_said_back(self):
        self.say("hi", ai("Hi! Are you looking for a car?", intent="greeting"))
        reply = self.say("a golf, max 250 a month", ai("Great, a Golf up to £250 a month. Any deposit?",
                                                       make_model="Volkswagen Golf", monthly_budget_gbp=250))
        self.assertEqual(reply, "Great, a Golf up to £250 a month. Any deposit?")

    def test_when_ready_the_hub_thanks_them_and_quotes(self):
        self.say("BMW 1 Series please", ai("What monthly budget?", make_model="BMW 1 Series"))
        thanks = self.say("£500 a month, 2k deposit, that's all",
                          ai("ok", ready=True, monthly_budget_gbp=500, deposit_gbp=2000))
        self.assertTrue(thanks.startswith("Thank you, we've got your details"), thanks)
        enquiry = Enquiry.objects.get()
        self.assertEqual(enquiry.step, "awaiting_approval")  # still waits for a person to approve
        self.assertEqual(self.seen[0].deposit_pence, 200000)

    def test_ready_without_a_car_or_a_budget_keeps_chatting(self):
        reply = self.say("hello", ai("Hi! Are you after a car?", intent="greeting", ready=True))
        self.assertEqual(reply, "Hi! Are you after a car?")
        self.assertEqual(Enquiry.objects.get().step, "chatting")

    def test_asking_for_a_person(self):
        self.say("hi", ai("Hello! Looking for a car?", intent="greeting"))
        reply = self.say("can someone call me", ai("Sure", wants_person=True))
        self.assertIn("One of our team will reply", reply)
        self.assertEqual(Enquiry.objects.get().step, "needs_person")

    def test_when_the_ai_fails_the_scripted_questions_carry_on(self):
        self.answers.append(AiUnavailable("down"))
        self.calls.side_effect = lambda *a, **k: (_ for _ in ()).throw(AiUnavailable("down"))
        reply = self.say("I'm after a BMW 1 Series")
        self.assertIn("monthly budget", reply)

    def test_after_the_options_it_answers_from_the_sent_cards_only(self):
        self.say("BMW 1 Series", ai("Budget?", make_model="BMW 1 Series"))
        self.say("500 a month, no deposit", ai("ok", ready=True, monthly_budget_gbp=500, deposit_gbp=0))
        enquiry = Enquiry.objects.get()
        self.api.post(f"/api/sim/enquiries/{enquiry.id}/approve")
        reply = self.say("which one has the lowest miles?",
                         ai("Option 1 has the lowest mileage at 21,000 miles. Reply 1 to go ahead with it!"))
        self.assertEqual(reply, "Option 1 has the lowest mileage at 21,000 miles. Reply 1 to go ahead with it!")
        context = self.calls.call_args.args[3].split("\n\nCONVERSATION:")[0].lower()
        self.assertIn('"stage": "options"', context)
        cars = json.dumps(json.loads(context)["cars"])
        for word in STAFF_ONLY + ("price", "monthly", "quote", "deposit"):
            self.assertNotIn(word.lower(), cars, word)
        self.assertEqual(Enquiry.objects.get().step, "options_sent")
        self.assertIn("Great choice", self.say("2"))  # choosing is still done by code, no AI call
        self.assertEqual(Enquiry.objects.get().step, "handed_over")

    def test_no_car_found_the_ai_helps_them_change_and_a_change_searches_again(self):
        from apps.quotes import codeweavers as cw

        self.say("BMW 1 Series", ai("Budget?", make_model="BMW 1 Series"))
        patch, _ = fake_codeweavers({f"XX2{n} TST": cw.QuoteError("no") for n in range(1, 9)})
        with patch:
            self.say("£400 a month, no deposit, that's it", ai("ok", ready=True, monthly_budget_gbp=400, deposit_gbp=0))
        enquiry = Enquiry.objects.get()
        self.assertEqual((enquiry.step, enquiry.asked[-1]), ("chatting", "retry"))
        # just chatting: the AI answers, nothing is searched yet, and it knows why
        reply = self.say("hmm what do you suggest?", ai("Would a different model or a higher budget work for you?"))
        self.assertEqual(reply, "Would a different model or a higher budget work for you?")
        self.assertIn('"NOTE": "No cars could be found', self.calls.call_args.args[3])
        self.assertEqual(Enquiry.objects.get().step, "chatting")
        thanks = self.say("ok a golf then", ai("ok", make_model="Volkswagen Golf"))
        self.assertTrue(thanks.startswith("Thank you"), thanks)
        self.assertEqual(Enquiry.objects.get().requirement.make, "Volkswagen")

    def test_owner_can_switch_back_to_scripted(self):
        from apps.core.models import Setting

        Setting.objects.create(key="enquiry_ai_replies", value=False)
        reply = self.say("I'm after a BMW 1 Series")
        self.calls.assert_not_called()
        self.assertIn("monthly budget", reply)


class GuardTests(TestCase):
    def test_guard(self):
        said = ["looking for a golf around 250 a month", "deposit 1k"]
        self.assertEqual(conversation.guard("Up to £250 a month with £1,000 down, got it!", said),
                         "Up to £250 a month with £1,000 down, got it!")
        for bad in ("That's about £199 a month", "£1,500 deposit would help", "300 per month is realistic",
                    "0% finance available", "Your credit score won't matter", "It's on our forecourt",
                    "It can be delivered tomorrow", "Send your bank details", "", "x" * 701):
            self.assertIsNone(conversation.guard(bad, said), bad)
