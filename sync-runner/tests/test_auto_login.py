"""Run from the sync-runner folder:  python -m unittest discover tests"""

import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scrapers"))

import run_scrape  # noqa: E402
import run_sync  # noqa: E402
from guard import PlatformStop, SessionLoggedOut  # noqa: E402

ARGS = types.SimpleNamespace(max_mileage=80000, min_year=2016, limit=0, no_images=True, no_login=False)
URLS = ["https://pro.motorway.co.uk/vehicles/1", "https://pro.motorway.co.uk/vehicles/2",
        "https://pro.motorway.co.uk/vehicles/3"]


def quiet(message):
    pass


class ScrapeLoginTests(unittest.TestCase):
    def run_scrape(self, exit_codes, login_ok=True, args=ARGS):
        codes = iter(exit_codes)
        with mock.patch.object(run_scrape, "run_script", side_effect=lambda *a: next(codes)) as script, \
                mock.patch.object(run_scrape, "log_in", return_value=login_ok) as login, \
                mock.patch.object(Path, "exists", return_value=True):
            return run_scrape.scrape("motorway", args, quiet), script.call_count, login.call_count

    def test_expired_session_logs_in_and_carries_on(self):
        self.assertEqual(self.run_scrape([2, 0]), (0, 2, 1))

    def test_login_is_tried_at_most_twice(self):
        self.assertEqual(self.run_scrape([2, 2, 2, 2]), (2, 3, 2))

    def test_failed_login_stops_there(self):
        self.assertEqual(self.run_scrape([2], login_ok=False), (2, 1, 1))

    def test_a_platform_stop_never_triggers_a_login_or_retry(self):
        self.assertEqual(self.run_scrape([3]), (3, 1, 0))

    def test_no_login_switch(self):
        args = types.SimpleNamespace(**{**vars(ARGS), "no_login": True})
        self.assertEqual(self.run_scrape([2], args=args), (2, 1, 0))


class FakeHub:
    def __init__(self):
        self.reported, self.finished = [], None

    def next_run(self, platform):
        return {"id": "run-1", "urls": URLS, "delay_ms": 0}, ""

    def start(self, run_id, session_ok):
        return {"status": "running" if session_ok else "skipped", "stop_reason": "session_logged_out"}

    def report_url(self, run_id, url, outcome, **kwargs):
        self.reported.append((url, outcome))
        return {"missing_photos": []}

    def finish(self, run_id, status, reason):
        self.finished = (status, reason)
        return {"status": status, "listings_captured": sum(o == "captured" for _, o in self.reported)}


def collector(fail_on_call, error):
    """A collector that raises `error` on the given calls: at the second URL first time, then at once."""
    calls = []

    def collect(urls, guard, images):
        calls.append(list(urls))
        for n, url in enumerate(urls):
            if len(calls) in fail_on_call and n == (1 if len(calls) == 1 else 0):
                raised = error("logged out" if error is SessionLoggedOut else "HTTP 429")
                raised.url = url
                raise raised
            yield {"url": url, "outcome": "captured", "record": {}, "folder": None, "http_status": 200, "detail": ""}
    return collect, calls


class SyncLoginTests(unittest.TestCase):
    def sync(self, collect, login_ok=True, auto_login=True):
        import collectors
        hub = FakeHub()
        with mock.patch.dict(collectors.COLLECTORS, {"motorway": collect}), \
                mock.patch.object(run_sync, "log_in", return_value=login_ok) as login, \
                mock.patch.object(Path, "exists", return_value=True):
            run_sync.sync_platform(hub, "motorway", False, quiet, auto_login)
        return hub, login.call_count

    def test_logs_in_mid_run_and_finishes_the_rest_without_repeats(self):
        collect, calls = collector({1}, SessionLoggedOut)
        hub, logins = self.sync(collect)
        self.assertEqual(logins, 1)
        self.assertEqual(calls, [URLS, URLS[1:]])  # second pass only has what was not done
        self.assertEqual(hub.reported, [(u, "captured") for u in URLS])
        self.assertEqual(hub.finished, ("completed", ""))

    def test_gives_up_after_two_logins(self):
        collect, calls = collector({1, 2, 3}, SessionLoggedOut)
        hub, logins = self.sync(collect)
        self.assertEqual((logins, len(calls)), (2, 3))
        self.assertEqual(hub.finished, ("failed", "session_logged_out"))

    def test_without_auto_login_the_run_fails_as_before(self):
        collect, _ = collector({1}, SessionLoggedOut)
        hub, logins = self.sync(collect, auto_login=False)
        self.assertEqual((logins, hub.finished), (0, ("failed", "session_logged_out")))

    def test_platform_stop_is_never_followed_by_a_login(self):
        collect, calls = collector({1}, PlatformStop)
        hub, logins = self.sync(collect)
        self.assertEqual((logins, len(calls)), (0, 1))
        self.assertEqual(hub.finished, ("stopped_by_platform", "HTTP 429"))
        self.assertIn((URLS[1], "stopped"), hub.reported)


if __name__ == "__main__":
    unittest.main()
