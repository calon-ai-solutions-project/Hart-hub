"""Client for the Hart Hub sync API. The runner never touches the database directly."""

import os
from urllib.parse import urlsplit

import requests


class HubError(Exception):
    status = None  # the hub's HTTP status, when it answered


class HubClient:
    def __init__(self, base_url=None, token=None):
        base_url = (base_url or os.getenv("HUB_URL") or "").rstrip("/")
        token = token or os.getenv("HUB_RUNNER_TOKEN")
        if not base_url or not token:
            raise SystemExit("Set HUB_URL and HUB_RUNNER_TOKEN in your .env file.")
        parts = urlsplit(base_url)
        if parts.scheme != "https" and parts.hostname not in ("localhost", "127.0.0.1"):
            raise SystemExit("HUB_URL must be https (the runner token must not travel in clear text).")
        self.base = base_url
        self.http = requests.Session()
        self.http.headers["Authorization"] = f"Bearer {token}"

    def _call(self, method, path, **kwargs):
        try:
            r = self.http.request(method, f"{self.base}{path}", timeout=120, **kwargs)
        except requests.RequestException as e:
            raise HubError(f"Could not reach the hub: {e}") from e
        if r.status_code >= 400:
            error = HubError(f"Hub answered {r.status_code} for {path}: {r.text[:300]}")
            error.status = r.status_code
            raise error
        return r.json() if r.content else None

    def platforms(self):
        """{platform: {"enabled": bool, "slot": "HH:MM"}}"""
        return self._call("GET", "/api/sync/platforms")

    def scrape_settings(self):
        """{"max_mileage": int, "min_year": int} - the filters set in the hub."""
        return self._call("GET", "/api/scrape/settings")

    def next_run(self, platform):
        """(run, reason): today's run ({id, urls, delay_ms, ...}), or None and why there is none."""
        answer = self._call("GET", "/api/sync/next", params={"platform": platform})
        return answer["run"], answer["reason"]

    def save_scraped(self, platform, record):
        return self._call("POST", "/api/scrape/listings", json={"platform": platform, "record": record})

    def upload_scraped_photo(self, platform, external_id, position, path):
        with open(path, "rb") as f:
            return self._call("POST", "/api/scrape/photos",
                              data={"platform": platform, "external_id": external_id, "position": position},
                              files={"file": (path.name, f, "image/jpeg")})

    def start(self, run_id, session_ok):
        return self._call("POST", f"/api/sync/runs/{run_id}/start", json={"session_ok": session_ok})

    def report_url(self, run_id, url, outcome, record=None, http_status=None, detail=""):
        body = {"url": url, "outcome": outcome, "http_status": http_status, "detail": detail[:255]}
        if record is not None:
            body["record"] = record
        return self._call("POST", f"/api/sync/runs/{run_id}/urls", json=body)

    def upload_photo(self, run_id, url, position, path):
        with open(path, "rb") as f:
            return self._call("POST", f"/api/sync/runs/{run_id}/photos",
                              data={"url": url, "position": position}, files={"file": (path.name, f, "image/jpeg")})

    def finish(self, run_id, status, stop_reason=""):
        return self._call("POST", f"/api/sync/runs/{run_id}/report",
                          json={"status": status, "stop_reason": stop_reason[:255]})
