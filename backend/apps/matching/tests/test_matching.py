from datetime import datetime, timedelta, timezone
from unittest import mock

from django.test import SimpleTestCase, TestCase

from apps.ai.client import AiUnavailable
from apps.listings.models import Listing
from apps.listings.services import keys
from apps.matching.models import Requirement
from apps.matching.services import parse, rerank, search
from apps.matching.services.budget import price_ceiling_pence
from apps.matching.services.cards import CUSTOMER_FIELDS, available_until, customer_card, staff_card

NOW = datetime(2026, 10, 12, 16, 0, tzinfo=timezone.utc)  # 17:00 UK
STAFF_ONLY = ("buy_price", "prep_cost", "margin", "listing_url", "url", "platform", "match_reason", "match_score",
              "registration", "raw", "cap_")


def car(external_id, make="BMW", model="1 Series", price=1200000, **fields):
    defaults = dict(platform="motorway", url=f"https://pro.motorway.co.uk/vehicles/{external_id}",
                    details_status="complete", status="live", gearbox="Automatic", colour="Black", year=2020,
                    mileage=30000, fuel="Petrol", suggested_price_pence=price, buy_price_pence=price - 310000,
                    prep_cost_pence=110000, ends_at=NOW + timedelta(hours=30), title=f"{make} {model}")
    return Listing.objects.create(external_id=str(external_id), make=make, model=model, **{**defaults, **fields})


class KeyTests(SimpleTestCase):
    def test_platform_wording_collapses_to_one_key(self):
        self.assertEqual({keys.make_key(m) for m in ("Mercedes", "MERCEDES-BENZ", "Mercedes-Benz", "merc")},
                         {"mercedesbenz"})
        self.assertEqual(keys.make_key("VW"), "volkswagen")
        self.assertEqual([keys.gearbox_kind(g) for g in ("Automatic", "Manual Transmission", "Auto/Manual Mode",
                                                         "Semi-automatic", "DSG", "")],
                         ["auto", "manual", "auto", "auto", "auto", ""])
        self.assertEqual([keys.colour_key(c) for c in ("GREY", "Metallic Gray", "Black", "Sunset")],
                         ["grey", "grey", "black", ""])

    def test_model_match_never_crosses_models(self):
        self.assertTrue(keys.model_matches("A Class", "A-Class"))
        self.assertTrue(keys.model_matches("CLA", "CLA 220 AMG LN PRM+"))
        self.assertTrue(keys.model_matches("golf gti", "Golf", "GTI Performance"))
        self.assertTrue(keys.model_matches("cclass", "C-Class"))
        self.assertFalse(keys.model_matches("CLA", "SLK 200"))  # a CLA never matches an SLK
        self.assertFalse(keys.model_matches("A1", "A180"))
        self.assertFalse(keys.model_matches("1 Series", "3 Series"))
        self.assertTrue(keys.model_matches("one series", "1 Series"))


class ParseTests(TestCase):
    def test_form(self):
        fields = parse.from_form({"make_model": "bmw 1 series", "colour": "Black or grey", "gearbox": "Auto",
                                  "deposit": "£2,000", "monthly_budget": "300pm", "needed_by": "End of the month"})
        self.assertEqual(fields, {"make": "BMW", "model": "1 Series", "colours": ["black", "grey"],
                                  "colour_only": False, "gearbox": "auto", "deposit_pence": 200000, "monthly_budget_pence": 30000,
                                  "needed_by": "End of the month"})

    def test_blank_and_none_answers_are_left_out(self):
        fields = parse.from_form({"make_model": "Mercedes A Class", "colour": "any", "gearbox": "Either",
                                  "deposit": "none", "monthly_budget": "", "needed_by": "n/a"})
        self.assertEqual(fields, {"make": "Mercedes-Benz", "model": "A Class"})

    def test_money(self):
        self.assertEqual([parse.to_pence(v) for v in ("£2,000", "2k", "1.5k", "300 pm", "0", "none", "", None, 250)],
                         [200000, 200000, 150000, 30000, None, None, None, None, 25000])

    def test_free_text(self):
        fields = parse.from_text("Black BMW 1 series, automatic, £3k deposit, 300 a month")
        self.assertEqual(fields, {"make": "BMW", "model": "1 Series", "colours": ["black"], "colour_only": False,
                                  "gearbox": "auto", "deposit_pence": 300000, "monthly_budget_pence": 30000})
        self.assertEqual(parse.from_text("vw golf under £15k manual"),
                         {"make": "Volkswagen", "model": "Golf", "gearbox": "manual", "max_price_pence": 1500000})
        self.assertEqual(parse.from_text("only black"), {"colours": ["black"], "colour_only": True})
        self.assertEqual(parse.from_text("bmw one series auto")["model"], "1 Series")
        self.assertEqual(parse.from_text("any colour"), {"colours": [], "colour_only": False})
        self.assertEqual(parse.from_text("any make, automatic, under £20k"),
                         {"make": "", "model": "", "gearbox": "auto", "max_price_pence": 2000000})
        self.assertEqual(parse.from_text("hello"), {})

    def test_insisting_on_a_colour_makes_it_a_hard_rule(self):
        for said in ("Gray Only", "only grey", "must be grey", "just grey please", "grey", "in grey please"):
            with self.subTest(said=said):
                self.assertEqual(parse.from_text(said), {"colours": ["grey"], "colour_only": True})
        # a colour mentioned in passing stays a preference
        self.assertFalse(parse.from_text("grey BMW 1 series automatic")["colour_only"])
        self.assertFalse(parse.from_text("ideally grey, automatic")["colour_only"])
        self.assertNotIn("colour_only", parse.from_text("automatic only"))

    def test_sort_words(self):
        self.assertEqual(parse.from_text("cheapest first"), {"sort": "price"})
        self.assertEqual(parse.from_text("show me the newest"), {"sort": "year"})
        self.assertEqual(parse.from_text("Lowest mileage"), {"sort": "mileage"})
        self.assertEqual(parse.from_text("best match first"), {"sort": ""})

    def test_pasted_form_with_answers(self):
        fields = parse.from_text("• Make & Model: Audi A3\n• Preferred Colour: white\n• Auto or Manual: manual\n"
                                 "• Deposit (if any): 1000\n• Max Monthly Budget: £250\n• When do you need it by? asap")
        self.assertEqual(fields["make"], "Audi")
        self.assertEqual((fields["model"], fields["colours"], fields["gearbox"]), ("A3", ["white"], "manual"))
        self.assertEqual((fields["deposit_pence"], fields["monthly_budget_pence"]), (100000, 25000))

    def test_model_alone_finds_its_make_from_stock(self):
        car(1, make="NISSAN", model="QASHQAI")
        self.assertEqual(parse.from_text("qashqai automatic"), {"make": "Nissan", "model": "Qashqai", "gearbox": "auto"})

    def test_follow_up_only_changes_what_it_mentions(self):
        requirement = Requirement(make="BMW", model="1 Series", gearbox="auto", monthly_budget_pence=30000)
        parse.apply_fields(requirement, parse.from_text("only black"))
        self.assertEqual((requirement.make, requirement.model, requirement.gearbox, requirement.colours,
                          requirement.monthly_budget_pence), ("BMW", "1 Series", "auto", ["black"], 30000))
        self.assertTrue(requirement.colour_only)
        parse.apply_fields(requirement, parse.from_text("ideally red, manual"))  # a new colour is a preference again
        self.assertEqual((requirement.colours, requirement.colour_only, requirement.gearbox), (["red"], False, "manual"))
        parse.apply_fields(requirement, parse.from_text("any colour"))
        self.assertEqual((requirement.colours, requirement.colour_only), ([], False))


class BudgetTests(TestCase):
    def test_monthly_budget_becomes_a_price_ceiling(self):
        # £300 x 48 months at 12.9% APR is about £11,200 borrowed, plus the deposit
        ceiling = price_ceiling_pence(Requirement(monthly_budget_pence=30000, deposit_pence=200000))
        self.assertTrue(1300000 < ceiling < 1340000, ceiling)

    def test_cash_budget_is_used_as_given_and_no_budget_means_no_ceiling(self):
        self.assertEqual(price_ceiling_pence(Requirement(max_price_pence=1500000, monthly_budget_pence=30000)), 1500000)
        self.assertIsNone(price_ceiling_pence(Requirement(deposit_pence=200000)))


class SearchTests(TestCase):
    def find(self, **wanted):
        return search.find(Requirement(**wanted), NOW)

    def ids(self, **wanted):
        return [c.listing.external_id for c in self.find(**wanted)[0]]

    def test_only_available_cars_are_ever_offered(self):
        car("ok")
        car("ended", status="ended")
        car("past", ends_at=NOW - timedelta(minutes=1))
        car("partial", details_status="partial")
        car("unpriced", suggested_price_pence=None)
        car("buy-now", ends_at=None)
        self.assertCountEqual(self.ids(make="BMW"), ["ok", "buy-now"])

    def test_make_model_and_gearbox_are_hard_filters(self):
        car("right")
        car("manual", gearbox="Manual Transmission")
        car("merc", make="MERCEDES-BENZ", model="A-Class")
        self.assertEqual(self.ids(make="BMW", model="1 Series", gearbox="auto"), ["right"])
        self.assertEqual(self.ids(make="Mercedes", model="A Class"), ["merc"])
        self.assertEqual(self.ids(make="BMW", gearbox="manual"), ["manual"])

    def test_budget_filters_and_colour_only_ranks(self):
        car("grey-cheap", colour="GREY", price=1000000)
        car("black", colour="Black", price=1100000)
        car("dear", price=2000000)
        candidates, notes = self.find(make="BMW", colours=["black"], max_price_pence=1200000)
        self.assertEqual([c.listing.external_id for c in candidates], ["black", "grey-cheap"])
        self.assertEqual([c.flags for c in candidates], [[], ["different_colour"]])
        self.assertEqual(notes, [])

    def test_only_a_colour_hides_every_other_colour(self):
        car("grey", colour="GREY")
        car("white", colour="White")
        car("silver", colour="SILVER")
        preferred, _ = self.find(make="BMW", colours=["grey"])
        self.assertEqual(len(preferred), 3)  # a preference only ranks: the others are shown, flagged
        only, notes = self.find(make="BMW", colours=["grey"], colour_only=True)
        self.assertEqual([c.listing.external_id for c in only], ["grey"])
        self.assertEqual(only[0].flags, [])
        self.assertEqual(notes, ["Showing grey only. 2 more in other colours are hidden."])
        none, notes = self.find(make="BMW", colours=["red"], colour_only=True)
        self.assertEqual(none, [])
        self.assertIn("no red ones, but 3 in other colours", notes[0])

    def test_sort_order_chosen_by_the_salesperson(self):
        car("a", price=1500000, year=2022, mileage=40000)
        car("b", price=900000, year=2018, mileage=60000)
        car("c", price=1200000, year=2020, mileage=15000)
        self.assertEqual(self.ids(make="BMW", sort="price"), ["b", "c", "a"])
        self.assertEqual(self.ids(make="BMW", sort="year"), ["a", "c", "b"])
        self.assertEqual(self.ids(make="BMW", sort="mileage"), ["c", "a", "b"])

    def test_newer_and_lower_mileage_rank_higher(self):
        car("old", year=2016, mileage=78000)
        car("new", year=2023, mileage=9000)
        self.assertEqual(self.ids(make="BMW"), ["new", "old"])

    def test_widens_to_slightly_over_budget_then_to_other_models(self):
        car("over", price=1300000)  # 8% over
        car("way-over", price=2000000)
        car("other", model="3 Series", price=1100000)
        candidates, notes = self.find(make="BMW", model="1 Series", max_price_pence=1200000)
        self.assertEqual([(c.listing.external_id, c.flags) for c in candidates],
                         [("over", ["over_budget"]), ("other", ["different_model"])])
        self.assertIn("a little over", notes[0])

    def test_explains_why_nothing_was_found(self):
        self.assertIn("no live, priced cars", self.find(make="BMW")[1][0])
        car("bmw", price=2000000)
        self.assertIn("no live Audi", self.find(make="Audi")[1][0])
        self.assertIn("no live manual BMW", self.find(make="BMW", gearbox="manual")[1][0])
        self.assertIn("cheapest car that otherwise fits is £20,000", self.find(make="BMW", max_price_pence=500000)[1][0])


class RerankTests(TestCase):
    def setUp(self):
        for n in range(1, 8):
            car(n, year=2015 + n)
        self.requirement = Requirement(make="BMW", colours=["black"], max_price_pence=1500000)
        self.candidates, _ = search.find(self.requirement, NOW)

    def test_without_ai_the_top_five_get_rule_reasons(self):
        options, used_ai = rerank.choose(self.requirement, self.candidates)
        self.assertFalse(used_ai)
        self.assertEqual([c.listing.external_id for c, _ in options], ["7", "6", "5", "4", "3"])
        self.assertEqual(options[0][1], "Black as asked, automatic, 2022, 30,000 miles, within budget")

    def ai(self, answer):
        return mock.patch.multiple(rerank, ai_enabled=lambda: True, complete_json=mock.Mock(side_effect=answer))

    def test_ai_reorders_inside_the_shortlist(self):
        picks = {"picks": [{"n": 3, "reason": "Newest black automatic hatchback"}, {"n": 1, "reason": "Low mileage"}]}
        with self.ai([picks]):
            options, used_ai = rerank.choose(self.requirement, self.candidates)
        self.assertTrue(used_ai)
        self.assertEqual([c.listing.external_id for c, _ in options], ["5", "7", "6", "4", "3"])  # filled up to five
        self.assertEqual(options[0][1], "Newest black automatic hatchback")

    def test_ai_cannot_add_cars_or_talk_about_money(self):
        picks = {"picks": [{"n": 99, "reason": "Not on the list"}, {"n": 2, "reason": "Only £199 a month!"},
                           {"n": 2, "reason": "Repeated"}, {"n": "1", "reason": "Wrong type"}]}
        with self.ai([picks]):
            options, _ = rerank.choose(self.requirement, self.candidates)
        self.assertEqual(options[0][0].listing.external_id, "6")
        self.assertNotIn("£199", options[0][1])
        self.assertIn("within budget", options[0][1])  # our reason replaced the AI's
        self.assertEqual(len({c.listing.external_id for c, _ in options}), 5)

    def test_a_chosen_sort_order_is_not_reshuffled_by_ai(self):
        self.requirement.sort = "year"
        with self.ai(AssertionError("the AI must not be asked")):
            options, used_ai = rerank.choose(self.requirement, self.candidates)
        self.assertFalse(used_ai)

    def test_ai_failure_falls_back_to_rules(self):
        with self.ai(AiUnavailable("down")):
            options, used_ai = rerank.choose(self.requirement, self.candidates)
        self.assertFalse(used_ai)
        self.assertEqual(len(options), 5)


class CardTests(TestCase):
    def test_customer_card_has_no_staff_fields(self):
        listing = car("1", registration="XX20 TST", spec="Heated seats", cover_thumbnail="listings/x/thumbs/01.webp")
        card = customer_card(listing, NOW)
        self.assertEqual(set(card), set(CUSTOMER_FIELDS))
        for key in card:
            self.assertFalse(any(word in key for word in STAFF_ONLY), key)
        text = str(card)
        for secret in ("XX20", "pro.motorway.co.uk", str(listing.buy_price_pence), "Motorway"):
            self.assertNotIn(secret, text)
        self.assertEqual(card["price_pence"], 1200000)
        self.assertEqual(card["ends_at"], (NOW + timedelta(hours=30)).isoformat())  # the end date is for customers too
        self.assertIsNone(customer_card(car("buy-now", ends_at=None), NOW)["ends_at"])
        self.assertEqual(staff_card(listing, "reason", ["over_budget"], 12.5)["margin_band"], "green")

    def test_available_until_wording(self):
        def ends(**kwargs):
            return available_until(Listing(ends_at=kwargs.get("at")), NOW)
        self.assertEqual(ends(at=None), "Buy now: this car can sell at any time.")
        self.assertEqual(ends(at=datetime(2026, 10, 12, 21, 59, tzinfo=timezone.utc)),
                         "This deal ends today at 10.59pm. After that it's gone.")
        self.assertEqual(ends(at=datetime(2026, 10, 13, 14, 30, tzinfo=timezone.utc)),
                         "This deal ends tomorrow at 3.30pm. After that it's gone.")
        self.assertEqual(ends(at=datetime(2026, 10, 16, 8, 0, tzinfo=timezone.utc)),
                         "This deal ends on Friday 16 October at 9.00am.")
