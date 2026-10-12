import email
import html
import re
from email import policy

from django.db import transaction
from django.utils import timezone

from apps.core.services import emit_event
from apps.listings.models import Listing
from apps.listings.services.expiry import status_for

from ..models import Alert
from ..platforms import PLATFORMS, platform_for_sender

URL_RE = re.compile(r"https://[^\s\"'<>\\)\]]+")


class UnknownPlatform(ValueError):
    pass


def readable_body(raw):
    """The text and HTML of an alert. Accepts a whole MIME email or just its body."""
    if not re.match(r"(?i)^[\w-]+:\s", raw):
        return raw
    message = email.message_from_string(raw, policy=policy.default)
    parts = []
    for part in message.walk():
        if part.get_content_type() in ("text/plain", "text/html"):
            try:
                parts.append(part.get_content())
            except (LookupError, UnicodeDecodeError):
                continue
    return "\n".join(parts) or raw


def extract_listing_urls(platform, raw):
    """{external_id: canonical_url} for every listing link of this platform found in an alert."""
    definition = PLATFORMS[platform]
    found = {}
    for url in URL_RE.findall(html.unescape(readable_body(raw))):
        match = definition.match(url.rstrip(".,;"))
        if match:
            found.setdefault(*match)
    return found


def ingest_alert(raw, *, sender="", subject="", platform=None, now=None):
    """Store a saved-search alert and upsert its listings (live, details still to capture).

    Only listings that arrive this way are ever put on a sync run's allowlist.
    """
    now = now or timezone.now()
    platform = platform or platform_for_sender(sender)
    if platform not in PLATFORMS:
        raise UnknownPlatform(f"Cannot tell which platform sent this alert (sender: {sender or 'none'}).")
    listings = extract_listing_urls(platform, raw)

    with transaction.atomic():
        alert = Alert.objects.create(platform=platform, received_at=now, sender=sender[:255],
                                     subject=subject[:255], raw=raw, parsed_count=len(listings))
        for external_id, url in listings.items():
            listing, created = Listing.objects.select_for_update().get_or_create(
                platform=platform, external_id=external_id,
                defaults={"url": url, "source": Listing.Source.ALERT, "first_seen_at": now,
                          "last_seen_at": now, "last_alert_at": now},
            )
            if created:
                continue
            listing.last_alert_at = listing.last_seen_at = now
            listing.url, listing.source = url, Listing.Source.ALERT
            if listing.status == Listing.Status.ENDED and listing.ended_reason == "left_alerts":
                listing.status = status_for(listing.ends_at, now)  # back in the alerts
                listing.ended_reason = "end_time_passed" if listing.status == Listing.Status.ENDED else ""
            listing.save(update_fields=["last_alert_at", "last_seen_at", "url", "source", "status",
                                        "ended_reason", "updated_at"])
        emit_event("alert.ingested", {"alert_id": str(alert.id), "platform": platform, "listings": len(listings)})
    return alert
