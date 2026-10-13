from datetime import datetime, timedelta, timezone

from django.core import mail
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings

from apps.core.models import Event, Setting
from apps.listings.models import Listing, ListingPhoto
from apps.sourcing.models import SyncLog, SyncRun
from apps.sourcing.services import runs
from apps.sourcing.services.alerts import UnknownPlatform, ingest_alert
from apps.sourcing.services.ingest import IngestError, save_scraped, upsert_listing

from . import fixtures

# 12 Oct 2026 is in British Summer Time: 16:00 UTC is 17:00 in the UK
NOW = datetime(2026, 10, 12, 16, 0, tzinfo=timezone.utc)
URL_4 = "https://pro.motorway.co.uk/vehicles/30000004"
URL_5 = "https://pro.motorway.co.uk/vehicles/30000005"


def alert(now=NOW, body=fixtures.MOTORWAY_ALERT):
    return ingest_alert(body, sender="alerts@motorway.co.uk", now=now)


class AlertIngestTests(TestCase):
    def test_alert_creates_partial_live_listings(self):
        stored = alert()
        self.assertEqual(stored.parsed_count, 2)
        listing = Listing.objects.get(external_id="30000004")
        self.assertEqual((listing.platform, listing.status, listing.details_status, listing.source, listing.url),
                         ("motorway", "live", "partial", "alert", URL_4))
        self.assertTrue(Event.objects.filter(type="alert.ingested").exists())

    def test_the_same_car_in_two_alerts_is_one_listing(self):
        alert()
        alert(NOW + timedelta(hours=1))
        self.assertEqual(Listing.objects.count(), 2)
        self.assertEqual(Listing.objects.get(external_id="30000004").last_alert_at, NOW + timedelta(hours=1))

    def test_unknown_sender_is_refused(self):
        with self.assertRaises(UnknownPlatform):
            ingest_alert(fixtures.MOTORWAY_ALERT, sender="someone@example.com")


class PrepareRunTests(TestCase):
    def test_allowlist_is_exactly_the_alerted_listings(self):
        alert(NOW - timedelta(hours=2))
        run, created = runs.prepare_run("motorway", NOW)
        self.assertTrue(created)
        self.assertEqual(run.status, SyncRun.Status.READY)
        self.assertEqual(str(run.uk_date), "2026-10-12")
        self.assertCountEqual(run.allowlist, [URL_4, URL_5])

    def test_second_run_on_the_same_uk_day_is_rejected(self):
        alert(NOW - timedelta(hours=2))
        first, _ = runs.prepare_run("motorway", NOW)
        again, created = runs.prepare_run("motorway", NOW + timedelta(hours=3))
        self.assertFalse(created)
        self.assertEqual(again.pk, first.pk)
        self.assertEqual(SyncRun.objects.count(), 1)

    def test_uk_day_not_utc_day_decides_once_per_day(self):
        alert(NOW - timedelta(hours=2))
        runs.prepare_run("motorway", NOW)
        # 23:30 UTC on the 12th is already 00:30 on the 13th in the UK
        alert(NOW + timedelta(hours=7))
        _, created = runs.prepare_run("motorway", datetime(2026, 10, 12, 23, 30, tzinfo=timezone.utc))
        self.assertTrue(created)

    def test_platform_that_is_not_enabled_is_skipped(self):
        ingest_alert("https://www.bca.co.uk/lot/XX16TSU", platform="bca", now=NOW - timedelta(hours=1))
        run, _ = runs.prepare_run("bca", NOW)  # SYNC_ENABLED_BCA is off in the test settings
        self.assertEqual((run.status, run.stop_reason, run.allowlist), ("skipped", "platform_not_enabled", []))

    def test_no_alerts_means_nothing_to_open_and_nothing_ended(self):
        alert(NOW - timedelta(days=3))
        run, _ = runs.prepare_run("motorway", NOW)
        self.assertEqual((run.status, run.stop_reason), ("skipped", "no_listings_to_sync"))
        self.assertEqual(Listing.objects.filter(status="live").count(), 2)

    def test_listing_missing_from_todays_alerts_is_ended(self):
        alert(NOW - timedelta(days=1, hours=2))
        runs.prepare_run("motorway", NOW - timedelta(days=1))
        alert(NOW - timedelta(hours=2), body=f'<a href="{URL_5}">still listed</a>')
        run, _ = runs.prepare_run("motorway", NOW)
        self.assertEqual(run.allowlist, [URL_5])
        gone = Listing.objects.get(external_id="30000004")
        self.assertEqual((gone.status, gone.ended_reason), ("ended", "left_alerts"))
        self.assertTrue(Event.objects.filter(type="listing.expired", payload__reason="left_alerts").exists())

    def test_only_alert_listings_are_allowlisted(self):
        alert(NOW - timedelta(hours=2))
        upsert_listing("motorway", {**fixtures.MOTORWAY, "vehicle_id": 99, "sale_end_utc": ""},
                       source=Listing.Source.IMPORT, now=NOW - timedelta(hours=1))
        run, _ = runs.prepare_run("motorway", NOW)
        self.assertCountEqual(run.allowlist, [URL_4, URL_5])

    def test_due_platforms_follow_their_uk_slots(self):
        # 17:00 UK: Motorway's 16:45 slot has passed, Carwow's 17:15 has not
        due = runs.due_platforms(NOW)
        self.assertIn("motorway", due)
        self.assertNotIn("carwow", due)
        Setting.objects.create(key="sync_slot_carwow", value="16:30")
        self.assertIn("carwow", runs.due_platforms(NOW))
        runs.prepare_run("motorway", NOW)
        self.assertNotIn("motorway", runs.due_platforms(NOW))


class RunLifecycleTests(TestCase):
    def setUp(self):
        alert(NOW - timedelta(hours=2))
        self.run, _ = runs.prepare_run("motorway", NOW)

    def start(self):
        return runs.start_run(self.run.pk, session_ok=True, now=NOW)

    def test_logged_out_session_skips_the_run_and_tells_the_team(self):
        run = runs.start_run(self.run.pk, session_ok=False, now=NOW)
        self.assertEqual((run.status, run.stop_reason), ("skipped", "session_logged_out"))
        self.assertIn("not logged in", mail.outbox[0].subject)
        with self.assertRaises(runs.RunStateError):
            self.start()

    def test_a_run_cannot_be_started_twice(self):
        self.start()
        with self.assertRaises(runs.RunStateError):
            self.start()

    def test_switch_turned_off_after_prepare_still_blocks_the_run(self):
        with override_settings(SYNC_ENABLED={"motorway": False}):
            run = self.start()
        self.assertEqual((run.status, run.stop_reason), ("skipped", "platform_not_enabled"))

    def test_url_outside_the_allowlist_is_refused_and_logged(self):
        run = self.start()
        other = "https://pro.motorway.co.uk/vehicles/999"
        with self.assertRaises(runs.NotAllowlisted):
            runs.record_url(run, other, "captured", record=fixtures.MOTORWAY, now=NOW)
        self.assertEqual(SyncLog.objects.get(url=other).outcome, "refused")
        self.assertFalse(Listing.objects.filter(external_id="999").exists())

    def test_capture_completes_the_listing_and_prices_it(self):
        run = self.start()
        listing = runs.record_url(run, URL_4, "captured", record=fixtures.MOTORWAY, http_status=200, now=NOW)
        self.assertEqual(Listing.objects.count(), 2)  # the alert's row was updated, not duplicated
        self.assertEqual((listing.details_status, listing.status, listing.make), ("complete", "ending_soon", "Testmake"))
        self.assertEqual(listing.buy_price_pence, 1389000)
        self.assertEqual(listing.suggested_price_pence, 1389000 + 110000 + 200000)
        self.assertEqual(listing.margin_pence, 200000)
        self.assertEqual(listing.photos.count(), 2)
        self.assertEqual(listing.last_run, run)

    def test_completed_run_logs_every_url(self):
        run = self.start()
        runs.record_url(run, URL_4, "captured", record=fixtures.MOTORWAY, now=NOW)
        run = runs.finish_run(run, "completed", now=NOW)
        self.assertEqual((run.status, run.listings_captured), ("completed", 1))
        self.assertEqual(dict(run.log.values_list("url", "outcome")), {URL_4: "captured", URL_5: "skipped"})
        self.assertTrue(Event.objects.filter(type="sync.run_completed").exists())
        self.assertEqual(mail.outbox, [])

    def test_platform_stop_ends_the_run_and_alerts(self):
        run = self.start()
        runs.record_url(run, URL_4, "stopped", http_status=429, detail="HTTP 429", now=NOW)
        run = runs.finish_run(run, "stopped_by_platform", "HTTP 429", now=NOW)
        self.assertEqual(run.status, "stopped_by_platform")
        self.assertIn("stopped by platform", mail.outbox[0].subject)
        self.assertTrue(Event.objects.filter(type="sync.run_stopped_by_platform").exists())
        with self.assertRaises(runs.RunStateError):  # nothing more is accepted, and no retry today
            runs.record_url(run, URL_5, "captured", record=fixtures.MOTORWAY, now=NOW)
        _, created = runs.prepare_run("motorway", NOW + timedelta(hours=1))
        self.assertFalse(created)

    def test_stale_runs_are_closed(self):
        self.start()
        self.assertEqual(runs.close_stale_runs(NOW + timedelta(hours=7)), 1)
        self.run.refresh_from_db()
        self.assertEqual((self.run.status, self.run.stop_reason), ("failed", "runner_went_silent"))

    def test_uncollected_run_cannot_be_started_the_next_day(self):
        tomorrow = NOW + timedelta(days=1)
        with self.assertRaises(runs.RunStateError):
            runs.start_run(self.run.pk, session_ok=True, now=tomorrow)
        runs.close_stale_runs(tomorrow)
        self.run.refresh_from_db()
        self.assertEqual((self.run.status, self.run.stop_reason), ("skipped", "runner_did_not_collect"))


class ScrapeThenSyncTests(TestCase):
    """The scrape command finds cars; the daily sync then re-checks exactly those cars."""

    def setUp(self):
        self.car, created = save_scraped("motorway", fixtures.MOTORWAY)
        self.assertTrue(created)

    def test_scraped_car_is_stored_complete_and_priced(self):
        self.assertEqual((self.car.source, self.car.details_status, self.car.url), ("search", "complete", URL_4))
        self.assertEqual(self.car.suggested_price_pence, 1389000 + 110000 + 200000)
        again, created = save_scraped("motorway", {**fixtures.MOTORWAY, "display_price": 14000})
        self.assertFalse(created)
        self.assertEqual((Listing.objects.count(), again.buy_price_pence), (1, 1400000))

    def test_record_with_a_link_that_is_not_a_listing_is_refused(self):
        with self.assertRaises(IngestError):
            save_scraped("motorway", {**fixtures.MOTORWAY, "url": "https://evil.test/vehicles/30000004"})

    def test_sync_rechecks_scraped_cars_and_updates_them(self):
        Listing.objects.update(ends_at=NOW + timedelta(hours=30), status="live")
        run, _ = runs.prepare_run("motorway", NOW)
        self.assertEqual(run.allowlist, [URL_4])
        run = runs.start_run(run.pk, session_ok=True, now=NOW)
        new_end = (NOW + timedelta(hours=5)).isoformat()
        runs.record_url(run, URL_4, "captured", now=NOW,
                        record={**fixtures.MOTORWAY, "highest_bid": 15000, "sale_end_utc": new_end})
        self.car.refresh_from_db()
        self.assertEqual((self.car.buy_price_pence, self.car.buy_price_kind, self.car.status),
                         (1500000, "current_bid", "ending_soon"))
        self.assertEqual(self.car.source, "search")

    def gone_at_sync(self):
        Listing.objects.update(ends_at=None, status="live")
        run, _ = runs.prepare_run("motorway", NOW)
        run = runs.start_run(run.pk, session_ok=True, now=NOW)
        runs.record_url(run, URL_4, "failed", http_status=404, detail="HTTP 404", now=NOW)

    def test_sold_car_is_deleted_at_the_sync_with_its_photos(self):
        photo = ListingPhoto.objects.create(listing=self.car, position=99, source_url="https://img.test/1.jpg")
        photo.image.save("sold-car-test.jpg", ContentFile(b"jpeg"), save=True)
        storage, name = photo.image.storage, photo.image.name
        self.assertTrue(storage.exists(name))
        self.gone_at_sync()
        self.assertFalse(Listing.objects.filter(pk=self.car.pk).exists())
        self.assertFalse(ListingPhoto.objects.exists())
        self.assertFalse(storage.exists(name))
        event = Event.objects.get(type="listing.deleted")
        self.assertEqual((event.payload["external_id"], event.payload["reason"]), ("30000004", "listing_gone"))
        self.assertEqual(SyncLog.objects.filter(url=URL_4, http_status=404).count(), 1)  # the log keeps the URL

    def test_sold_car_is_only_ended_when_deleting_is_switched_off(self):
        Setting.objects.create(key="sync_delete_sold_listings", value=False)
        self.gone_at_sync()
        self.car.refresh_from_db()
        self.assertEqual((self.car.status, self.car.ended_reason), ("ended", "listing_gone"))

    def test_runner_is_told_why_there_is_no_run(self):
        Listing.objects.update(ends_at=None, status="live")
        morning = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)  # 10:00 UK, before Motorway's 16:45 slot
        run, reason = runs.run_for_runner("motorway", morning)
        self.assertIsNone(run)
        self.assertIn("16:45", reason)
        self.assertEqual(SyncRun.objects.count(), 0)  # asking early does not use up the day's run
        run, reason = runs.run_for_runner("bca", NOW)
        self.assertIn("switched off", reason)
        run, reason = runs.run_for_runner("motorway", NOW)  # 17:00 UK: prepared on demand
        self.assertEqual((run.status, run.allowlist, reason), ("ready", [URL_4], ""))
        runs.start_run(run.pk, session_ok=True, now=NOW)
        runs.finish_run(run, "completed", now=NOW)
        run, reason = runs.run_for_runner("motorway", NOW + timedelta(hours=1))
        self.assertIsNone(run)
        self.assertIn("one run per UK day", reason)
