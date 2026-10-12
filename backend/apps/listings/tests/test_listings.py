from datetime import datetime, timedelta, timezone

from django.test import TestCase

from apps.core.models import Event, Setting
from apps.listings.models import Listing
from apps.listings.services.expiry import expire_listings
from apps.listings.services.pricing import price_listing

NOW = datetime(2026, 10, 12, 16, 0, tzinfo=timezone.utc)


def listing(external_id, **fields):
    return Listing.objects.create(platform="motorway", external_id=external_id,
                                  url=f"https://pro.motorway.co.uk/vehicles/{external_id}", **fields)


class PricingTests(TestCase):
    def test_suggested_price_is_buy_plus_prep_plus_target_margin(self):
        car = price_listing(Listing(buy_price_pence=1500000))
        self.assertEqual((car.prep_cost_pence, car.suggested_price_pence, car.margin_pence),
                         (110000, 1810000, 200000))

    def test_defaults_come_from_settings_rows(self):
        Setting.objects.create(key="prep_cost_pence", value=90000)
        Setting.objects.create(key="target_margin_pence", value=150000)
        car = price_listing(Listing(buy_price_pence=1000000))
        self.assertEqual((car.prep_cost_pence, car.suggested_price_pence), (90000, 1240000))

    def test_per_car_prep_cost_and_a_price_set_by_a_person_are_kept(self):
        car = price_listing(Listing(buy_price_pence=1000000, prep_cost_pence=50000))
        self.assertEqual(car.suggested_price_pence, 1250000)
        car = price_listing(Listing(buy_price_pence=1000000, suggested_price_pence=1999900, price_overridden=True))
        self.assertEqual(car.suggested_price_pence, 1999900)

    def test_no_buy_price_means_no_suggested_price(self):
        car = price_listing(Listing())
        self.assertIsNone(car.suggested_price_pence)
        self.assertIsNone(car.margin_pence)


class ExpiryTests(TestCase):
    def test_expiry_job(self):
        past = listing("1", ends_at=NOW - timedelta(minutes=1))
        soon = listing("2", ends_at=NOW + timedelta(hours=23))
        later = listing("3", ends_at=NOW + timedelta(hours=30))
        buy_now = listing("4", ends_at=None)
        sold = listing("5", ends_at=NOW - timedelta(days=1), status=Listing.Status.SOLD)

        self.assertEqual(expire_listings(NOW), {"ended": 1, "ending_soon": 1})
        statuses = {car.external_id: car.status for car in Listing.objects.all()}
        self.assertEqual(statuses, {"1": "ended", "2": "ending_soon", "3": "live", "4": "live", "5": "sold"})
        past.refresh_from_db()
        self.assertEqual(past.ended_reason, "end_time_passed")
        self.assertEqual(Event.objects.filter(type="listing.expired").count(), 1)
        self.assertEqual(Event.objects.get().payload["listing_id"], str(past.id))

        # running it again changes nothing
        self.assertEqual(expire_listings(NOW), {"ended": 0, "ending_soon": 0})
        # and an ending-soon car ends when its time comes
        self.assertEqual(expire_listings(NOW + timedelta(hours=24))["ended"], 1)
        del soon, later, buy_now, sold

    def test_events_are_append_only(self):
        event = Event.objects.create(type="listing.expired")
        event.type = "changed"
        with self.assertRaises(TypeError):
            event.save()
        with self.assertRaises(TypeError):
            event.delete()
