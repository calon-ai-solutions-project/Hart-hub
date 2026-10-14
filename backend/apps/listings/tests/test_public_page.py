import json
from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from apps.core.models import Setting
from apps.listings.models import CarLink, Listing, ListingPhoto
from apps.listings.services.public import car_page_url, link_for

STAFF_ONLY = ("motorway", "pro.motorway.co.uk", "30000004", "XX20TST", "XX20 TST", "1000000", "buy_price", "margin",
              "registration", "listing_url", "platform")


def car(**fields):
    defaults = dict(platform="motorway", external_id="30000004", url="https://pro.motorway.co.uk/vehicles/30000004",
                    registration="XX20 TST", make="BMW", model="1 Series", title="BMW 1 Series 118i M Sport",
                    year=2020, mileage=30000, gearbox="Automatic", colour="black", fuel="Petrol", status="live",
                    details_status="complete", buy_price_pence=1000000, suggested_price_pence=1150000,
                    ends_at=timezone.now() + timedelta(days=2))
    return Listing.objects.create(**{**defaults, **fields})


class PublicCarPageTests(TestCase):
    def setUp(self):
        cache.clear()  # rate limits
        self.car = car()
        ListingPhoto.objects.create(listing=self.car, position=1, source_url="https://img.test/1.jpg",
                                    image="listings/motorway/30000004/01.jpg",
                                    thumbnail="listings/motorway/30000004/thumbs/01.webp")

    def open(self, token):
        return self.client.get(f"/api/public/cars/{token}")

    def test_one_unguessable_link_per_car(self):
        first, again = link_for(self.car), link_for(self.car)
        self.assertEqual(first.pk, again.pk)
        self.assertGreaterEqual(len(first.token), 10)
        self.assertNotIn("30000004", first.token)
        self.assertTrue(car_page_url(self.car).endswith(f"/c/{first.token}"))

    def test_page_shows_customer_fields_only_and_needs_no_login(self):
        response = self.open(link_for(self.car).token)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["available"])
        self.assertEqual(data["car"]["title"], "BMW 1 Series 118i M Sport")
        self.assertNotIn("price_pence", data["car"])  # no price on the public page
        self.assertEqual(len(data["photos"]), 1)
        text = json.dumps(data).lower()
        for word in STAFF_ONLY:  # nothing anywhere on the page gives away the source, including photo addresses
            self.assertNotIn(word.lower(), text, word)
        self.assertEqual(response["X-Robots-Tag"], "noindex")
        self.assertEqual(CarLink.objects.get().opened_count, 1)

    def test_an_ended_car_shows_nothing_but_that(self):
        token = link_for(self.car).token
        Listing.objects.filter(pk=self.car.pk).update(ends_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(self.open(token).json()["available"], False)
        self.assertNotIn("car", self.open(token).json())

    def test_photos_come_from_the_page_address(self):
        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage

        default_storage.save("listings/motorway/30000004/thumbs/01.webp", ContentFile(b"webp-bytes"))
        self.addCleanup(default_storage.delete, "listings/motorway/30000004/thumbs/01.webp")
        token = link_for(self.car).token
        thumb = self.open(token).json()["photos"][0]["thumb"]
        self.assertEqual(thumb, f"/api/public/cars/{token}/photos/1?size=thumb")
        response = self.client.get(thumb)
        self.assertEqual((response.status_code, response["Content-Type"], response.content),
                         (200, "image/webp", b"webp-bytes"))
        self.assertEqual(self.client.get(f"/api/public/cars/{token}/photos/9").status_code, 404)

    def test_unknown_link(self):
        self.assertEqual(self.open("not-a-real-code").status_code, 404)

    def test_whatsapp_button_number_comes_from_settings(self):
        Setting.objects.create(key="public_whatsapp_number", value="+44 7700 900100")
        self.assertEqual(self.open(link_for(self.car).token).json()["whatsapp"], "447700900100")
