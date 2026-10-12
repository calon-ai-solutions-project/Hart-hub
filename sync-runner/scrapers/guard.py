"""The sync guard: the platform sync rules (contract Schedule 1), enforced on the runner.

- a URL is opened only if it is on the run's allowlist (Hart's saved-search alert listings)
- pages are opened one at a time, with a fixed pause between them
- any CAPTCHA, verification, unusual-activity notice, access denied, 403 or 429 stops the whole run;
  nothing is retried, waited out or worked around
"""

import re
import time

STOP_STATUSES = (403, 429)
STOP_PHRASES = (
    "captcha",
    "verify you are human",
    "verifying you are human",
    "are you a robot",
    "unusual activity",
    "access denied",
    "security check",
    "just a moment",
    "checking your browser",
)


class PlatformStop(Exception):
    """The platform challenged or blocked us: the run ends here."""


class SessionLoggedOut(Exception):
    """The saved session is no longer logged in: a person must log in before the next slot."""


class NotAllowlisted(Exception):
    pass


def visible_text(html):
    """Lower-case text a person would see: scripts, styles and tags removed."""
    html = re.sub(r"(?is)<(script|style|noscript|template)\b.*?</\1>", " ", html or "")
    return re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", " ", html)).lower()


def challenge_in(html, title=""):
    """The stop phrase found in a page, or None."""
    text = f"{title} {visible_text(html)}".lower()
    return next((phrase for phrase in STOP_PHRASES if phrase in text), None)


class SyncGuard:
    def __init__(self, urls, delay_ms=4000):
        self.allowlist = frozenset(urls)
        self.delay = max(delay_ms, 0) / 1000
        self.opened = 0

    def check_url(self, url):
        if url not in self.allowlist:
            raise NotAllowlisted(url)

    def pause(self):
        """Call before opening each listing: waits between pages (not before the first)."""
        if self.opened:
            time.sleep(self.delay)
        self.opened += 1

    def check_response(self, status, body="", title="", is_page=True):
        """Raise PlatformStop if a response is a block or a challenge.

        `is_page` False is for JSON the page's own API returned: only its status is judged, because
        a vehicle description may legitimately contain words like "security".
        """
        if status in STOP_STATUSES:
            raise PlatformStop(f"HTTP {status}")
        if is_page:
            phrase = challenge_in(body, title)
            if phrase:
                raise PlatformStop(f"page shows '{phrase}'")
