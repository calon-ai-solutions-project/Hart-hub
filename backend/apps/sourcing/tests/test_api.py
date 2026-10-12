import io
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from apps.core.models import Setting
from apps.core.services import DEFAULTS
from apps.listings.models import Listing
from apps.sourcing.models import Alert, RunnerToken, SyncRun
from apps.sourcing.services import runs
from apps.sourcing.services.alerts import ingest_alert

from . import fixtures

URL_4 = "https://pro.motorway.co.uk/vehicles/30000004"


def jpeg():
    out = io.BytesIO()
    Image.new("RGB", (800, 600), "navy").save(out, "JPEG")
    return SimpleUploadedFile("01.jpg", out.getvalue(), content_type="image/jpeg")


class AlertInboundApiTests(TestCase):
    def test_needs_the_shared_secret(self):
        payload = {"from": "alerts@motorway.co.uk", "html": fixtures.MOTORWAY_ALERT}
        self.assertEqual(self.client.post("/api/alerts/inbound", payload).status_code, 403)
        response = self.client.post("/api/alerts/inbound", payload, headers={"X-Alert-Token": "wrong"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Alert.objects.count(), 0)

    def test_stores_the_alert_and_its_listings(self):
        response = self.client.post(
            "/api/alerts/inbound", {"from": "Motorway <alerts@motorway.co.uk>", "subject": "New stock",
                                    "html": fixtures.MOTORWAY_ALERT},
            content_type="application/json", headers={"X-Alert-Token": "test-inbound-token"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["listings"], 2)
        self.assertEqual(Listing.objects.count(), 2)

    def test_unknown_sender_is_ignored_without_an_error(self):
        response = self.client.post("/api/alerts/inbound?token=test-inbound-token",
                                    {"sender": "x@example.com", "text": "hello"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("ignored", response.json())


class SyncApiTests(TestCase):
    def setUp(self):
        ingest_alert(fixtures.MOTORWAY_ALERT, sender="alerts@motorway.co.uk",
                     now=timezone.now() - timedelta(minutes=5))
        self.run, _ = runs.prepare_run("motorway")
        _, self.key = RunnerToken.issue("test-runner")
        self.api = APIClient()
        self.api.credentials(HTTP_AUTHORIZATION=f"Bearer {self.key}")
        self.base = f"/api/sync/runs/{self.run.id}"

    def test_every_endpoint_needs_a_runner_token(self):
        anonymous = APIClient()
        self.assertEqual(anonymous.get("/api/sync/next").status_code, 401)
        self.assertEqual(anonymous.post("/api/scrape/listings", {}, format="json").status_code, 401)
        self.assertEqual(anonymous.post(f"{self.base}/start", {"session_ok": True}, format="json").status_code, 401)
        anonymous.credentials(HTTP_AUTHORIZATION="Bearer hhr_not-a-real-token")
        self.assertEqual(anonymous.get("/api/sync/next").status_code, 401)

    def test_revoked_token_stops_working(self):
        RunnerToken.objects.update(revoked_at=timezone.now())
        self.assertEqual(self.api.get("/api/sync/next").status_code, 401)

    def test_only_the_hash_of_a_token_is_stored(self):
        token = RunnerToken.objects.get()
        self.assertNotIn(self.key, [str(v) for v in token.__dict__.values()])
        self.assertEqual(token.key_hash, RunnerToken.hash_key(self.key))

    def test_full_run(self):
        ready = self.api.get("/api/sync/next?platform=motorway").json()
        self.assertEqual(ready["run"]["id"], str(self.run.id))
        self.assertIn(URL_4, ready["run"]["urls"])
        off = self.api.get("/api/sync/next?platform=bca").json()  # switched off in the test settings
        self.assertIsNone(off["run"])
        self.assertIn("switched off", off["reason"])

        started = self.api.post(f"{self.base}/start", {"session_ok": True}, format="json")
        self.assertEqual(started.json()["status"], "running")
        self.assertEqual(self.api.post(f"{self.base}/start", {"session_ok": True}, format="json").status_code, 409)
        again = self.api.get("/api/sync/next?platform=motorway").json()
        self.assertIsNone(again["run"])
        self.assertIn("one run per UK day", again["reason"])

        refused = self.api.post(f"{self.base}/urls", {
            "url": "https://pro.motorway.co.uk/vehicles/999", "outcome": "captured", "record": fixtures.MOTORWAY,
        }, format="json")
        self.assertEqual(refused.status_code, 400)

        captured = self.api.post(f"{self.base}/urls", {
            "url": URL_4, "outcome": "captured", "http_status": 200, "record": fixtures.MOTORWAY}, format="json")
        self.assertEqual(captured.status_code, 200)
        self.assertEqual(captured.json()["missing_photos"], [1, 2])

        uploaded = self.api.post(f"{self.base}/photos", {"url": URL_4, "position": 1, "file": jpeg()},
                                 format="multipart")
        self.assertEqual(uploaded.status_code, 201)
        listing = Listing.objects.get(external_id="30000004")
        photo = listing.photos.get(position=1)
        self.assertEqual(photo.image.name, "listings/motorway/30000004/01.jpg")
        self.assertEqual(photo.thumbnail.name, "listings/motorway/30000004/thumbs/01.webp")
        self.assertEqual(listing.cover_thumbnail, photo.thumbnail.name)
        with photo.thumbnail.open() as f:
            self.assertLessEqual(max(Image.open(f).size), 480)

        finished = self.api.post(f"{self.base}/report", {"status": "completed"}, format="json")
        self.assertEqual(finished.json(), {"id": str(self.run.id), "status": "completed", "listings_captured": 1})
        self.assertEqual(self.api.post(f"{self.base}/report", {"status": "completed"}, format="json").status_code, 409)
        self.assertEqual(SyncRun.objects.get().log.count(), 3)  # refused + captured + one never reached

    def test_upload_that_is_not_an_image_is_rejected(self):
        self.api.post(f"{self.base}/start", {"session_ok": True}, format="json")
        self.api.post(f"{self.base}/urls", {"url": URL_4, "outcome": "captured", "record": fixtures.MOTORWAY},
                      format="json")
        fake = SimpleUploadedFile("01.jpg", b"<?php echo 1; ?>", content_type="image/jpeg")
        response = self.api.post(f"{self.base}/photos", {"url": URL_4, "position": 1, "file": fake},
                                 format="multipart")
        self.assertEqual(response.status_code, 422)
        self.assertFalse(Listing.objects.get(external_id="30000004").photos.get(position=1).image)

    def test_captured_without_a_record_is_invalid(self):
        self.api.post(f"{self.base}/start", {"session_ok": True}, format="json")
        response = self.api.post(f"{self.base}/urls", {"url": URL_4, "outcome": "captured"}, format="json")
        self.assertEqual(response.status_code, 400)


class ScrapeApiTests(TestCase):
    def setUp(self):
        _, key = RunnerToken.issue("test-runner")
        self.api = APIClient()
        self.api.credentials(HTTP_AUTHORIZATION=f"Bearer {key}")

    def test_scraped_car_and_its_photo_are_stored(self):
        saved = self.api.post("/api/scrape/listings", {"platform": "motorway", "record": fixtures.MOTORWAY},
                              format="json")
        self.assertEqual(saved.status_code, 200)
        self.assertEqual((saved.json()["created"], saved.json()["external_id"], saved.json()["missing_photos"]),
                         (True, "30000004", [1, 2]))
        photo = self.api.post("/api/scrape/photos", {"platform": "motorway", "external_id": "30000004",
                                                      "position": 1, "file": jpeg()}, format="multipart")
        self.assertEqual(photo.status_code, 201)
        listing = Listing.objects.get()
        self.assertEqual(listing.source, "search")
        self.assertTrue(listing.cover_thumbnail)
        again = self.api.post("/api/scrape/listings", {"platform": "motorway", "record": fixtures.MOTORWAY},
                              format="json")
        self.assertEqual((again.json()["created"], again.json()["missing_photos"]), (False, [2]))

    def test_bad_record_is_rejected(self):
        response = self.api.post("/api/scrape/listings", {"platform": "motorway", "record": {"url": "nope"}},
                                 format="json")
        self.assertEqual(response.status_code, 422)

    def test_platforms_shows_switches_and_slots(self):
        data = self.api.get("/api/sync/platforms").json()
        self.assertEqual(data["motorway"], {"enabled": True, "slot": "16:45"})
        self.assertFalse(data["bca"]["enabled"])

    def test_scrape_filters_come_from_settings_rows(self):
        self.assertEqual(self.api.get("/api/scrape/settings").json(), {"max_mileage": 80000, "min_year": 2016})
        call_command("seed_settings", stdout=io.StringIO())
        Setting.objects.filter(key="scrape_max_mileage").update(value=60000)
        call_command("seed_settings", stdout=io.StringIO())  # never overwrites a value someone changed
        self.assertEqual(self.api.get("/api/scrape/settings").json(), {"max_mileage": 60000, "min_year": 2016})
        self.assertEqual(Setting.objects.count(), len(DEFAULTS))
