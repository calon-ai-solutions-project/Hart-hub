from django.test import SimpleTestCase

from apps.sourcing.platforms import PLATFORMS, platform_for_sender
from apps.sourcing.services.alerts import extract_listing_urls

from .fixtures import MOTORWAY_ALERT


class PlatformUrlTests(SimpleTestCase):
    def test_listing_urls_give_the_platform_id_and_a_clean_url(self):
        cases = {
            "motorway": ("https://pro.motorway.co.uk/vehicles/123/?utm=x",
                         ("123", "https://pro.motorway.co.uk/vehicles/123")),
            "carwow": ("https://dealers.carwow.co.uk/dealers/listings/456",
                       ("456", "https://dealers.carwow.co.uk/dealers/listings/456")),
            "bca": ("https://www.bca.co.uk/lot/xx16%20tsu", ("XX16TSU", "https://www.bca.co.uk/lot/XX16TSU")),
            "manheim": ("https://www.manheim.co.uk/vehicle-detail/MAKE/MODEL?id=789&ref=mail",
                        ("789", "https://www.manheim.co.uk/vehicle-detail/MAKE/MODEL?id=789")),
        }
        for platform, (url, expected) in cases.items():
            with self.subTest(platform=platform):
                self.assertEqual(PLATFORMS[platform].match(url), expected)

    def test_anything_that_is_not_a_listing_page_is_rejected(self):
        rejected = [
            "http://pro.motorway.co.uk/vehicles/123",  # not https
            "https://pro.motorway.co.uk.evil.test/vehicles/123",  # lookalike host
            "https://pro.motorway.co.uk@evil.test/vehicles/123",  # host hidden behind userinfo
            "https://pro.motorway.co.uk/vehicles",  # the search, not a listing
            "https://pro.motorway.co.uk/vehicles/123/bid",
            "https://www.manheim.co.uk/vehicle-detail/MAKE/MODEL",  # no id
            "https://www.manheim.co.uk/search?id=5",
            "not a url",
        ]
        for url in rejected:
            with self.subTest(url=url):
                self.assertTrue(all(p.match(url) is None for p in PLATFORMS.values()))

    def test_alert_sender_identifies_the_platform(self):
        self.assertEqual(platform_for_sender("BCA <alerts@email.bca.co.uk>"), "bca")
        self.assertEqual(platform_for_sender("no-reply@motorway.co.uk"), "motorway")
        self.assertIsNone(platform_for_sender("someone@notmotorway.co.uk"))
        self.assertIsNone(platform_for_sender(""))

    def test_alert_links_are_deduplicated_and_filtered(self):
        self.assertEqual(extract_listing_urls("motorway", MOTORWAY_ALERT), {
            "30000004": "https://pro.motorway.co.uk/vehicles/30000004",
            "30000005": "https://pro.motorway.co.uk/vehicles/30000005",
        })

    def test_links_survive_a_quoted_printable_email(self):
        raw = ("From: alerts@carwow.co.uk\r\nSubject: New stock\r\nMIME-Version: 1.0\r\n"
               "Content-Type: text/html; charset=utf-8\r\nContent-Transfer-Encoding: quoted-printable\r\n\r\n"
               "<a href=3D\"https://dealers.carwow.co.uk/dealers/listi=\r\nngs/10000001\">car</a>\r\n")
        self.assertEqual(list(extract_listing_urls("carwow", raw)), ["10000001"])
