"""Run from the sync-runner folder:  python -m unittest discover tests"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scrapers"))

from guard import NotAllowlisted, PlatformStop, SyncGuard, challenge_in  # noqa: E402

URL = "https://pro.motorway.co.uk/vehicles/1"


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.guard = SyncGuard([URL], delay_ms=0)

    def test_only_allowlisted_urls_may_be_opened(self):
        self.guard.check_url(URL)
        for other in ("https://pro.motorway.co.uk/vehicles/2", "https://pro.motorway.co.uk/vehicles", URL + "/"):
            with self.assertRaises(NotAllowlisted):
                self.guard.check_url(other)

    def test_403_and_429_stop_the_run(self):
        for status in (403, 429):
            with self.assertRaises(PlatformStop):
                self.guard.check_response(status)
        self.guard.check_response(200, "<html><body>A normal listing page</body></html>")
        self.guard.check_response(404)  # one missing listing is not a platform stop

    def test_challenge_pages_stop_the_run(self):
        pages = [
            ("<html><body><h1>Verify you are human</h1></body></html>", ""),
            ("<html><body>We have detected unusual activity from your network</body></html>", ""),
            ("<html><body>Access Denied</body></html>", ""),
            ("<html><body>Please complete the CAPTCHA below</body></html>", ""),
            ("<html><body></body></html>", "Just a moment..."),
        ]
        for html, title in pages:
            with self.assertRaises(PlatformStop):
                self.guard.check_response(200, html, title)

    def test_scripts_and_markup_do_not_trigger_a_false_stop(self):
        html = ('<html><head><script src="https://www.google.com/recaptcha/api.js"></script>'
                '<style>.captcha{display:none}</style></head>'
                '<body><div class="security-check-banner">2021 Test Car, 30,000 miles</div></body></html>')
        self.assertIsNone(challenge_in(html))

    def test_api_json_is_judged_by_status_only(self):
        self.guard.check_response(200, '{"equipment": "Alarm, security check sticker"}', is_page=False)
        with self.assertRaises(PlatformStop):
            self.guard.check_response(429, "{}", is_page=False)


if __name__ == "__main__":
    unittest.main()
