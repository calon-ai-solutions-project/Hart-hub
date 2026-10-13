from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.ai.models import AiUsage
from apps.chat.models import Message
from apps.core.models import Event
from apps.listings.models import Listing
from apps.matching.models import Match, Requirement
from apps.matching.services import parse


def car(external_id, make="BMW", model="1 Series", price=1200000, **fields):
    defaults = dict(platform="motorway", url=f"https://pro.motorway.co.uk/vehicles/{external_id}",
                    details_status="complete", status="live", gearbox="Automatic", colour="Black", year=2020,
                    mileage=30000, suggested_price_pence=price, buy_price_pence=price - 310000,
                    prep_cost_pence=110000, ends_at=timezone.now() + timedelta(hours=30), title=f"{make} {model}")
    return Listing.objects.create(external_id=str(external_id), make=make, model=model, **{**defaults, **fields})


class ChatApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("sales@example.com", "a-long-password", is_staff=True)
        self.api = APIClient()
        self.api.force_authenticate(self.user)
        for n in range(1, 8):
            car(n, year=2015 + n, colour="Black" if n % 2 else "Grey")
        car("merc", make="Mercedes-Benz", model="A-Class")

    def start(self):
        return self.api.post("/api/chat/conversations").json()

    def say(self, conversation, **body):
        response = self.api.post(f"/api/chat/conversations/{conversation['id']}/messages", body, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()["messages"]

    def test_needs_a_login(self):
        anonymous = APIClient()
        self.assertIn(anonymous.post("/api/chat/conversations").status_code, (401, 403))

    def test_chat_starts_with_the_enquiry_form(self):
        conversation = self.start()
        greeting = conversation["messages"][0]
        self.assertEqual((greeting["role"], greeting["kind"]), ("bot", "form"))
        self.assertEqual(greeting["body"], "Hi, what are you looking for? Let me know and I’ll send you some options ASAP!")
        self.assertEqual([f["label"] for f in greeting["payload"]["fields"]],
                         ["Make & Model", "Preferred Colour", "Auto or Manual", "Deposit (if any)",
                          "Max Monthly Budget", "When do you need it by?"])
        self.assertTrue(greeting["payload"]["bonus"].startswith("Bonus: With any car purchased through us"))

    def test_form_returns_the_five_best_cars(self):
        conversation = self.start()
        asked, answer = self.say(conversation, form={"make_model": "BMW 1 Series", "colour": "Black",
                                                     "gearbox": "Auto", "deposit": "£2,000",
                                                     "monthly_budget": "£300", "needed_by": "ASAP"})
        self.assertIn("Make & Model: BMW 1 Series", asked["body"])
        self.assertEqual((answer["role"], answer["kind"]), ("bot", "options"))
        self.assertEqual(answer["body"], "Here are the best 5 of 7 cars for BMW 1 Series, black, automatic.")
        self.assertEqual([f["label"] for f in answer["payload"]["filters"]],
                         ["BMW 1 Series", "Prefers black", "Automatic", "£300 a month + £2,000 deposit"])
        self.assertEqual(answer["payload"]["suggestions"][:1], ["Only black"])
        cards = answer["payload"]["cards"]
        self.assertEqual(len(cards), 5)
        # black cars first (newest first), then the best grey ones, flagged
        self.assertEqual([c["customer"]["year"] for c in cards], [2022, 2020, 2018, 2016, 2021])
        self.assertEqual(cards[4]["staff"]["flags"], ["different_colour"])
        self.assertIn("not a quote", answer["payload"]["notes"][-1])
        self.assertEqual(answer["payload"]["ai"], {"parsed": False, "ranked": False})
        self.assertNotIn("buy_price_pence", cards[0]["customer"])
        self.assertEqual(cards[0]["staff"]["margin_pence"], 200000)

        requirement = Requirement.objects.get()
        self.assertEqual((requirement.make, requirement.gearbox, requirement.deposit_pence, requirement.created_by),
                         ("BMW", "auto", 200000, self.user))
        self.assertEqual(Match.objects.filter(requirement=requirement).count(), 5)
        self.assertEqual(set(Event.objects.values_list("type", flat=True)), {"requirement.saved", "matches.found"})

    def test_follow_up_refines_the_same_request(self):
        conversation = self.start()
        self.say(conversation, text="BMW 1 series automatic")
        _, answer = self.say(conversation, text="Gray Only")
        self.assertEqual(answer["body"], "I found 3 cars for BMW 1 Series, grey only, automatic.")
        self.assertEqual([c["customer"]["colour"] for c in answer["payload"]["cards"]], ["Grey"] * 3)  # nothing else
        self.assertEqual([c["staff"]["flags"] for c in answer["payload"]["cards"]], [[]] * 3)
        self.assertIn("Showing grey only. 4 more in other colours are hidden.", answer["payload"]["notes"])
        self.assertIn("Any colour", answer["payload"]["suggestions"])
        self.assertEqual(self.api.get(f"/api/chat/conversations/{conversation['id']}").json()["title"],
                         "BMW 1 Series, grey only, automatic")

        _, answer = self.say(conversation, text="Any colour")
        self.assertEqual(len(answer["payload"]["cards"]), 5)
        _, answer = self.say(conversation, text="Cheapest first")
        self.assertEqual([f["label"] for f in answer["payload"]["filters"]][-1], "Cheapest first")
        _, answer = self.say(conversation, text="actually a Mercedes A class")
        self.assertEqual(len(answer["payload"]["cards"]), 1)
        self.assertEqual(answer["payload"]["cards"][0]["customer"]["title"], "Mercedes-Benz A-Class")

    def test_filter_chips_can_be_removed_one_by_one(self):
        conversation = self.start()
        _, answer = self.say(conversation, text="grey BMW 1 series automatic")
        self.assertEqual([f["key"] for f in answer["payload"]["filters"]], ["make_model", "colours", "gearbox"])
        asked, answer = self.say(conversation, remove="colours")
        self.assertEqual(asked["body"], "Any colour")
        self.assertEqual([f["key"] for f in answer["payload"]["filters"]], ["make_model", "gearbox"])
        self.say(conversation, remove="gearbox")
        asked, answer = self.say(conversation, remove="make_model")
        self.assertEqual((answer["kind"], answer["body"]), ("text", "All filters cleared. What would you like to look for?"))
        self.assertEqual(answer["payload"]["filters"], [])
        response = self.api.post(f"/api/chat/conversations/{conversation['id']}/messages", {"remove": "nonsense"},
                                 format="json")
        self.assertEqual(response.status_code, 400)

    def test_asks_for_more_when_there_is_nothing_to_search_on(self):
        conversation = self.start()
        _, answer = self.say(conversation, text="hello there")
        self.assertEqual(answer["kind"], "text")
        self.assertIn("make and model, or a budget", answer["body"])
        self.assertEqual(Requirement.objects.count(), 0)

    def test_no_match_says_why(self):
        conversation = self.start()
        _, answer = self.say(conversation, text="Audi A3 manual")
        self.assertEqual(answer["payload"]["cards"], [])
        self.assertIn("no live Audi", answer["payload"]["notes"][0])

    def test_a_salesperson_only_sees_their_own_chats(self):
        conversation = self.start()
        other = APIClient()
        other.force_authenticate(User.objects.create_user("other@example.com", "a-long-password"))
        self.assertEqual(other.get(f"/api/chat/conversations/{conversation['id']}").status_code, 404)
        self.assertEqual(other.get("/api/chat/conversations").json(), [])
        self.assertEqual(len(self.api.get("/api/chat/conversations").json()), 1)

    def test_a_chat_can_be_deleted_by_its_owner_only(self):
        conversation = self.start()
        self.say(conversation, text="BMW 1 series automatic")
        url = f"/api/chat/conversations/{conversation['id']}"
        other = APIClient()
        other.force_authenticate(User.objects.create_user("other@example.com", "a-long-password"))
        self.assertEqual(other.delete(url).status_code, 404)
        self.assertEqual(len(self.api.get("/api/chat/conversations").json()), 1)

        self.assertEqual(self.api.delete(url).status_code, 204)
        self.assertEqual(self.api.get("/api/chat/conversations").json(), [])
        self.assertEqual(self.api.get(url).status_code, 404)
        self.assertEqual(Message.objects.count(), 0)  # its messages go with it
        self.assertEqual(Requirement.objects.count(), 1)  # what was asked for stays on record
        self.assertTrue(Event.objects.filter(type="chat.deleted").exists())
        self.assertEqual(self.api.delete(url).status_code, 404)

    def test_empty_message_is_rejected(self):
        conversation = self.start()
        response = self.api.post(f"/api/chat/conversations/{conversation['id']}/messages", {"text": "  "}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_with_ai_free_text_is_parsed_and_the_shortlist_reranked(self):
        answers = [
            {"make": "BMW", "model": "1 Series", "colours": ["black"], "gearbox": "auto", "deposit_gbp": None,
             "monthly_budget_gbp": 300, "max_price_gbp": None, "needed_by": None},
            {"picks": [{"n": 2, "reason": "Black automatic with the right spec"}]},
        ]
        fake = mock.Mock(side_effect=answers)
        with mock.patch("apps.matching.services.parse.ai_enabled", lambda: True), \
                mock.patch("apps.matching.services.parse.complete_json", fake), \
                mock.patch("apps.matching.services.rerank.ai_enabled", lambda: True), \
                mock.patch("apps.matching.services.rerank.complete_json", fake):
            _, answer = self.say(self.start(), text="they want a black one series, auto, about 300 a month")
        self.assertEqual(answer["payload"]["ai"], {"parsed": True, "ranked": True})
        self.assertEqual(answer["payload"]["cards"][0]["staff"]["match_reason"], "Black automatic with the right spec")
        self.assertEqual(len(answer["payload"]["cards"]), 5)
        self.assertEqual(Requirement.objects.get().monthly_budget_pence, 30000)


class AiClientTests(TestCase):
    def test_every_call_is_metered_and_failures_fall_back(self):
        from apps.ai import client

        self.assertFalse(client.ai_enabled())  # no key in tests
        with self.assertRaises(client.AiUnavailable):
            client.complete_json("rerank", "v1", "system", "user")
        self.assertEqual(AiUsage.objects.count(), 0)

        reply = mock.Mock(status_code=200, json=lambda: {
            "choices": [{"message": {"content": "```json\n{\"picks\": []}\n```"}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 8, "cost": 0.00042}})
        with self.settings(OPENROUTER_API_KEY="k", OPENROUTER_MODEL="some/model"), \
                mock.patch.object(client.requests, "post", return_value=reply) as post:
            self.assertEqual(client.complete_json("rerank", "rerank-v1", "system", "user"), {"picks": []})
            self.assertEqual(post.call_args.kwargs["headers"], {"Authorization": "Bearer k"})
        usage = AiUsage.objects.get()
        self.assertEqual((usage.feature, usage.model, usage.prompt_version, usage.input_tokens, usage.ok),
                         ("rerank", "some/model", "rerank-v1", 120, True))

        with self.settings(OPENROUTER_API_KEY="k", OPENROUTER_MODEL="some/model"), \
                mock.patch.object(client.requests, "post", side_effect=client.requests.ConnectionError("down")):
            with self.assertRaises(client.AiUnavailable):
                client.complete_json("rerank", "rerank-v1", "system", "user")
        self.assertEqual(AiUsage.objects.filter(ok=False).count(), 1)
        self.assertEqual(parse.parse_message("only black"), ({"colours": ["black"], "colour_only": True}, False))

    def test_short_refinements_never_cost_an_ai_call(self):
        called = mock.Mock(side_effect=AssertionError("the AI must not be asked"))
        with mock.patch("apps.matching.services.parse.ai_enabled", lambda: True), \
                mock.patch("apps.matching.services.parse.complete_json", called):
            self.assertEqual(parse.parse_message("Gray Only"), ({"colours": ["grey"], "colour_only": True}, False))
            self.assertEqual(parse.parse_message("Cheapest first"), ({"sort": "price"}, False))

    def test_only_survives_an_ai_parse_that_misses_it(self):
        reply = {"make": "Peugeot", "model": None, "colours": ["grey"], "gearbox": None}
        with mock.patch("apps.matching.services.parse.ai_enabled", lambda: True), \
                mock.patch("apps.matching.services.parse.complete_json", mock.Mock(return_value=reply)):
            fields, used_ai = parse.parse_message("they said it has to be a Peugeot and only in grey please")
        self.assertTrue(used_ai)
        self.assertEqual((fields["colours"], fields["colour_only"]), (["grey"], True))
