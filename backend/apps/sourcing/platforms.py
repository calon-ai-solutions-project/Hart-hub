"""What each sourcing platform's listing links look like.

A URL is only ever accepted when it is https, on the platform's exact host and shaped like a
listing page. Everything the runner may open is built from these definitions.
"""

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlsplit


@dataclass(frozen=True)
class PlatformDef:
    key: str
    host: str
    path_re: re.Pattern
    alert_sender_domains: tuple

    def external_id(self, parts, match):
        return match.group(1)

    def canonical_url(self, parts, external_id):
        return f"https://{self.host}{parts.path.rstrip('/')}"

    def match(self, url):
        """A listing URL -> (external_id, canonical_url); anything else -> None."""
        try:
            parts = urlsplit(url.strip())
        except ValueError:
            return None
        if parts.scheme != "https" or parts.netloc.lower() != self.host:
            return None
        found = self.path_re.match(parts.path)
        if not found:
            return None
        external_id = self.external_id(parts, found)
        if not external_id:
            return None
        return external_id, self.canonical_url(parts, external_id)


class _Manheim(PlatformDef):
    def external_id(self, parts, match):
        ids = parse_qs(parts.query).get("id", [])
        return ids[0] if ids and ids[0].isdigit() else None

    def canonical_url(self, parts, external_id):
        return f"https://{self.host}{parts.path}?id={external_id}"


class _Bca(PlatformDef):
    def external_id(self, parts, match):
        return re.sub(r"[^A-Z0-9]", "", unquote(match.group(1)).upper()) or None

    def canonical_url(self, parts, external_id):
        return f"https://{self.host}/lot/{external_id}"


PLATFORMS = {
    "motorway": PlatformDef("motorway", "pro.motorway.co.uk", re.compile(r"^/vehicles/(\d+)/?$"),
                            ("motorway.co.uk",)),
    "carwow": PlatformDef("carwow", "dealers.carwow.co.uk", re.compile(r"^/dealers/listings/(\d+)/?$"),
                          ("carwow.co.uk",)),
    "bca": _Bca("bca", "www.bca.co.uk", re.compile(r"^/lot/([A-Za-z0-9%+ ]{2,24})/?$"), ("bca.co.uk", "bca.com")),
    "manheim": _Manheim("manheim", "www.manheim.co.uk", re.compile(r"^/vehicle-detail/[^?#]+$"),
                        ("manheim.co.uk",)),
}


def platform_for_sender(sender):
    """'BCA Alerts <alerts@email.bca.co.uk>' -> 'bca'; unknown sender -> None."""
    found = re.search(r"@([A-Za-z0-9.-]+)", sender or "")
    if not found:
        return None
    domain = found.group(1).lower()
    for key, platform in PLATFORMS.items():
        if any(domain == d or domain.endswith("." + d) for d in platform.alert_sender_domains):
            return key
    return None
