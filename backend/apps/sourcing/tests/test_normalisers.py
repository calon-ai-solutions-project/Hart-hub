from datetime import datetime, timezone

from django.test import SimpleTestCase

from apps.sourcing.normalisers import normalise

from . import fixtures


class NormaliserTests(SimpleTestCase):
    def test_carwow(self):
        car = normalise("carwow", fixtures.CARWOW)
        self.assertEqual((car["external_id"], car["make"], car["model"]), ("10000001", "Land Rover", "Discovery Sport"))
        self.assertEqual(car["year"], 2020)
        self.assertEqual(car["location"], "Leeds")
        self.assertEqual(car["sale_type"], "auction")
        self.assertEqual(car["ends_at"], datetime(2026, 10, 13, 14, 30, tzinfo=timezone.utc))
        self.assertEqual(car["retail_valuation_pence"], 2450000)
        # Carwow shows no bid, so the buy price is CAP clean, flagged as an estimate
        self.assertEqual((car["buy_price_pence"], car["buy_price_kind"]), (2010000, "cap_clean"))
        self.assertEqual(len(car["photos"]), 2)

    def test_carwow_without_an_end_time_is_buy_now(self):
        car = normalise("carwow", {**fixtures.CARWOW, "auction_ends": ""})
        self.assertEqual((car["sale_type"], car["ends_at"]), ("buy_now", None))

    def test_manheim(self):
        car = normalise("manheim", fixtures.MANHEIM)
        self.assertEqual((car["make"], car["model"], car["trim"]), ("TESTMAKE", "TM", "250d AMG Line 5dr Auto"))
        self.assertEqual((car["gearbox"], car["fuel"], car["body"]), ("Automatic", "Diesel", "Estate"))
        self.assertEqual(car["sale_type"], "live_sale")
        self.assertEqual((car["buy_price_pence"], car["buy_price_kind"]), (950000, "current_bid"))
        self.assertEqual(car["lot_number"], "3184")

    def test_manheim_buy_now_and_no_bid(self):
        car = normalise("manheim", {**fixtures.MANHEIM, "is_buy_now": True, "buy_now_price": 11000})
        self.assertEqual((car["sale_type"], car["buy_price_pence"], car["buy_price_kind"]),
                         ("buy_now", 1100000, "buy_now"))
        car = normalise("manheim", {**fixtures.MANHEIM, "current_bid": 0})
        self.assertEqual((car["buy_price_pence"], car["buy_price_kind"]), (1280000, "cap_clean"))

    def test_bca(self):
        car = normalise("bca", fixtures.BCA)
        self.assertEqual((car["external_id"], car["registration"]), ("XX16TSU", "XX16 TSU"))
        self.assertEqual(car["sale_type"], "bid_now")
        self.assertEqual((car["cap_clean_pence"], car["cap_below_pence"]), (410000, 285000))
        self.assertEqual(car["buy_price_kind"], "cap_clean")
        car = normalise("bca", {**fixtures.BCA, "price_guideprice": "£ 3,900"})
        self.assertEqual((car["buy_price_pence"], car["buy_price_kind"]), (390000, "guide"))

    def test_bca_falls_back_to_the_detail_page_labels(self):
        record = {k: v for k, v in fixtures.BCA.items() if k not in ("year", "plate", "fuel", "transmission", "grade")}
        record.update(dateregistered="11/03/2016", fuel_type="Petrol", gearbox="Manual", vehicle_grade="3")
        car = normalise("bca", record)
        self.assertEqual((car["year"], car["fuel"], car["gearbox"], car["grade"]), (2016, "Petrol", "Manual", "3"))

    def test_motorway(self):
        car = normalise("motorway", fixtures.MOTORWAY)
        self.assertEqual((car["external_id"], car["body"], car["sale_type"]), ("30000004", "Panel van", "auction"))
        self.assertEqual((car["buy_price_pence"], car["buy_price_kind"]), (1389000, "reserve"))
        self.assertEqual(car["photos"][0], (1, "exterior_front_driver", "https://img.example.test/w1"))
        self.assertEqual(car["photos"][1][1], "")
        car = normalise("motorway", {**fixtures.MOTORWAY, "highest_bid": 12500})
        self.assertEqual((car["buy_price_pence"], car["buy_price_kind"]), (1250000, "current_bid"))

    def test_junk_values_do_not_break_a_record(self):
        car = normalise("manheim", {"vehicle_id": 5, "mileage": "n/a", "year": "unknown", "sale_end_utc": "soon",
                                    "photo_urls": "javascript:alert(1) | https://img.example.test/ok"})
        self.assertEqual((car["mileage"], car["year"], car["ends_at"], car["buy_price_pence"]), (None,) * 4)
        self.assertEqual(car["photos"], [(1, "", "https://img.example.test/ok")])
