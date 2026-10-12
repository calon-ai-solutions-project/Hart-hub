"""
The daily platform sync, run under the Hart Hub rules (contract Schedule 1).

For each platform it asks the hub for today's run. The hub only hands one out when
  - the platform's SYNC_ENABLED switch is on,
  - its daily slot (UK time) has passed, and
  - it has not already run today.
The run carries an allowlist: the listing URLs from Hart's saved-search alerts. This script opens
those URLs and nothing else, one at a time, and sends each car and its photos to the hub.

It stops the whole run at once on any CAPTCHA, verification, unusual-activity notice, access denied,
403 or 429, and reports it; those are never retried.

If a saved session has expired it runs that platform's login script (scrapers/<site>_login.py: a
Chrome window opens, logs in and closes), then carries on with the listings not done yet. A login is
tried at most twice per platform; --no-login switches this off.

Usage:
    python run_sync.py                 # every platform that has a run ready
    python run_sync.py --only motorway
    python run_sync.py --no-images     # data only
    python run_sync.py --no-login      # never log in automatically

Needs HUB_URL and HUB_RUNNER_TOKEN in .env. Schedule it (Windows Task Scheduler) a few minutes after
each platform's slot; running it when nothing is due does nothing.
"""

import argparse
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "scrapers"))  # the scraper modules live in scrapers/

from dotenv import load_dotenv  # noqa: E402

load_dotenv(HERE / ".env")

from guard import NotAllowlisted, PlatformStop, SessionLoggedOut, SyncGuard  # noqa: E402
from hub import HubClient, HubError  # noqa: E402
from paths import LOGS  # noqa: E402

PLATFORMS = ("motorway", "carwow", "bca", "manheim")
MAX_LOGINS = 2  # automatic logins per platform per command


class Log:
    def __init__(self, name="sync"):
        LOGS.mkdir(exist_ok=True)
        self.path = LOGS / f"{name}-{datetime.now():%Y-%m-%d}.log"

    def __call__(self, message):
        line = f"{datetime.now():%H:%M:%S} {message}"
        print(line)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def photo_files(folder):
    """{position: file} for the photos a collector saved (01_front.jpg, 02.jpg, ...)."""
    files = {}
    if folder and folder.is_dir():
        for path in folder.iterdir():
            numbered = re.match(r"(\d+)(?:_.*)?\.jpe?g$", path.name, re.I)
            if numbered:
                files[int(numbered.group(1))] = path
    return files


def run_script(path, args, log):
    """Run one of the scrapers/ scripts, streaming what it prints into the log. Returns its exit code."""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8:replace"}
    proc = subprocess.Popen([sys.executable, "-u", str(path), *args], cwd=HERE, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    for line in proc.stdout:
        log(f"  | {line.rstrip()}")
    return proc.wait()


def log_in(platform, log):
    """Run the platform's login script (visible Chrome window). True when a session was saved.

    If the site shows a CAPTCHA the script waits for a person to complete it in the window.
    """
    log(f"{platform}: session expired - logging in again (a browser window will open and close)...")
    ok = run_script(HERE / "scrapers" / f"{platform}_login.py", [], log) == 0
    log(f"{platform}: " + ("logged in" if ok else "login failed - check the window message above"))
    return ok


def sync_platform(hub, platform, images, log, auto_login=True):
    from collectors import SESSION_FILES

    run, reason = hub.next_run(platform)
    if not run:
        log(f"{platform}: nothing to sync - {reason}")
        return
    run_id, urls = run["id"], run["urls"]

    logins = 0
    session_ok = SESSION_FILES[platform].exists()
    if not session_ok and auto_login:
        logins += 1
        session_ok = log_in(platform, log)
    started = hub.start(run_id, session_ok)
    if started["status"] != "running":
        log(f"{platform}: run skipped ({started.get('stop_reason')}) - "
            f"log in with scrapers/{platform}_login.py; it can run again tomorrow")
        return
    log(f"{platform}: run started, {len(urls)} allowlisted listings")

    guard = SyncGuard(urls, run["delay_ms"])
    status, reason = "completed", ""
    done = set()  # URLs already handled, so a login in the middle does not repeat them
    while True:
        try:
            _collect(hub, platform, run_id, urls, done, guard, images, log)
        except SessionLoggedOut as e:
            if auto_login and logins < MAX_LOGINS:
                logins += 1
                if log_in(platform, log):
                    continue  # carry on with the listings not done yet
            status, reason = "failed", "session_logged_out"
            url = getattr(e, "url", None)
            if url:
                hub.report_url(run_id, url, "failed", detail=str(e))
            log(f"{platform}: the session is logged out - log in with scrapers/{platform}_login.py")
        except PlatformStop as e:
            status, reason = "stopped_by_platform", str(e)
            url = getattr(e, "url", None)
            if url:
                hub.report_url(run_id, url, "stopped", detail=reason)
            log(f"{platform}: STOPPED BY PLATFORM at {url} - {reason}. Nothing was retried.")
        except NotAllowlisted as e:
            status, reason = "failed", f"refused a URL that is not allowlisted: {e}"
            log(f"{platform}: {reason}")
        except HubError:
            raise
        except Exception as e:
            status, reason = "failed", f"{type(e).__name__}: {e}"
            log(f"{platform}: failed - {reason}")
        break

    finished = hub.finish(run_id, status, reason)
    log(f"{platform}: {finished['status']}, {finished['listings_captured']} of {len(urls)} listings captured")


def _collect(hub, platform, run_id, urls, done, guard, images, log):
    """Collect every URL not done yet and send each result to the hub."""
    from collectors import COLLECTORS

    for result in COLLECTORS[platform]([u for u in urls if u not in done], guard, images):
        done.add(result["url"])
        try:
            saved = hub.report_url(run_id, result["url"], result["outcome"], record=result["record"],
                                   http_status=result["http_status"], detail=result["detail"])
        except HubError as e:
            if e.status != 422:  # 422 = the hub could not use this one record; carry on with the rest
                raise
            log(f"  rejected {result['url']} ({e})")
            continue
        if result["outcome"] != "captured":
            log(f"  failed  {result['url']} ({result['detail']})")
            continue
        files = photo_files(result["folder"])
        wanted = [p for p in saved.get("missing_photos", []) if p in files]
        with ThreadPoolExecutor(max_workers=6) as pool:  # several at once: the hub may be far away
            list(pool.map(lambda p: hub.upload_photo(run_id, result["url"], p, files[p]), wanted))
        log(f"  [{len(done)}/{len(urls)}] captured {result['url']}")


def main():
    ap = argparse.ArgumentParser(description="Run today's platform sync under the Hart Hub rules")
    ap.add_argument("--only", choices=PLATFORMS, help="run just one platform")
    ap.add_argument("--no-images", action="store_true")
    ap.add_argument("--no-login", action="store_true", help="do not log in automatically when a session expired")
    args = ap.parse_args()

    sys.stdout.reconfigure(errors="replace")
    log = Log()
    hub = HubClient()
    for platform in [p for p in PLATFORMS if not args.only or p == args.only]:
        try:
            sync_platform(hub, platform, not args.no_images, log, not args.no_login)
        except HubError as e:
            log(f"{platform}: {e}")


if __name__ == "__main__":
    main()
