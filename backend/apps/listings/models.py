from django.db import models
from django.db.models import Q
from django.utils import timezone
from pgvector.django import VectorField

from apps.core.models import TimeStampedModel, UUIDModel

from .services import keys


class Platform(models.TextChoices):
    MOTORWAY = "motorway", "Motorway"
    CARWOW = "carwow", "Carwow"
    BCA = "bca", "BCA"
    MANHEIM = "manheim", "Manheim"


def photo_path(photo, filename):
    listing = photo.listing
    return f"listings/{listing.platform}/{listing.external_id}/{photo.position:02d}.jpg"


def thumbnail_path(photo, filename):
    listing = photo.listing
    return f"listings/{listing.platform}/{listing.external_id}/thumbs/{photo.position:02d}.webp"


class Listing(TimeStampedModel):
    """One car from a sourcing platform. Money is integer pence; times are UTC."""

    class Status(models.TextChoices):
        LIVE = "live", "Live"
        ENDING_SOON = "ending_soon", "Ending soon"
        ENDED = "ended", "Ended"
        SOLD = "sold", "Sold"

    class DetailsStatus(models.TextChoices):
        PARTIAL = "partial", "Partial (from alert, not captured yet)"
        COMPLETE = "complete", "Complete"

    class Source(models.TextChoices):
        ALERT = "alert", "Saved-search alert"
        SEARCH = "search", "Platform search (scrape command)"
        MANUAL = "manual", "Added by hand"
        IMPORT = "import", "Imported export file"

    class SaleType(models.TextChoices):
        AUCTION = "auction", "Auction"
        BUY_NOW = "buy_now", "Buy Now"
        BID_NOW = "bid_now", "Bid Now (timed)"
        LIVE_SALE = "live_sale", "Live sale"
        UNKNOWN = "unknown", "Unknown"

    class BuyPriceKind(models.TextChoices):
        BUY_NOW = "buy_now", "Buy now price"
        CURRENT_BID = "current_bid", "Current bid"
        RESERVE = "reserve", "Reserve / seller will accept"
        GUIDE = "guide", "Guide price"
        CAP_CLEAN = "cap_clean", "CAP clean (estimate, no platform price)"

    LIVE_STATUSES = (Status.LIVE, Status.ENDING_SOON)

    platform = models.CharField(max_length=20, choices=Platform.choices)
    external_id = models.CharField(max_length=64, help_text="The platform's own id for this listing")
    url = models.URLField(max_length=500)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.ALERT)
    details_status = models.CharField(max_length=10, choices=DetailsStatus.choices, default=DetailsStatus.PARTIAL)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.LIVE)
    ended_reason = models.CharField(max_length=40, blank=True)

    registration = models.CharField(max_length=16, blank=True)
    vin = models.CharField(max_length=32, blank=True)
    make = models.CharField(max_length=60, blank=True)
    model = models.CharField(max_length=80, blank=True)
    trim = models.CharField(max_length=160, blank=True)
    title = models.CharField(max_length=255, blank=True)
    year = models.PositiveSmallIntegerField(null=True, blank=True)
    mileage = models.PositiveIntegerField(null=True, blank=True)
    fuel = models.CharField(max_length=40, blank=True)
    gearbox = models.CharField(max_length=40, blank=True)
    colour = models.CharField(max_length=60, blank=True)
    body = models.CharField(max_length=60, blank=True)
    grade = models.CharField(max_length=40, blank=True)
    spec = models.TextField(blank=True)
    location = models.CharField(max_length=160, blank=True)

    # Normalised for matching; filled on every save from the text above.
    make_key = models.CharField(max_length=60, blank=True, db_index=True, editable=False)
    gearbox_kind = models.CharField(max_length=10, blank=True, editable=False)
    colour_key = models.CharField(max_length=20, blank=True, editable=False)

    sale_type = models.CharField(max_length=10, choices=SaleType.choices, default=SaleType.UNKNOWN)
    sale_channel = models.CharField(max_length=120, blank=True, help_text="As the platform words it")
    lot_number = models.CharField(max_length=40, blank=True)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)

    # Staff only: never put these in a customer payload.
    buy_price_pence = models.IntegerField(null=True, blank=True)
    buy_price_kind = models.CharField(max_length=12, choices=BuyPriceKind.choices, blank=True)
    prep_cost_pence = models.IntegerField(null=True, blank=True, help_text="Blank = the prep cost setting")
    suggested_price_pence = models.IntegerField(null=True, blank=True)
    price_overridden = models.BooleanField(default=False, help_text="A person set the selling price; keep it")
    cap_clean_pence = models.IntegerField(null=True, blank=True)
    cap_average_pence = models.IntegerField(null=True, blank=True)
    cap_below_pence = models.IntegerField(null=True, blank=True)
    cap_retail_pence = models.IntegerField(null=True, blank=True)
    retail_valuation_pence = models.IntegerField(null=True, blank=True)

    photo_count = models.PositiveSmallIntegerField(default=0)
    cover_thumbnail = models.CharField(max_length=255, blank=True, help_text="Storage key of the first thumbnail")
    raw = models.JSONField(default=dict, blank=True, help_text="Every field the runner collected")

    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)
    last_alert_at = models.DateTimeField(null=True, blank=True)
    last_captured_at = models.DateTimeField(null=True, blank=True)
    last_run = models.ForeignKey("sourcing.SyncRun", null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name="listings")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["platform", "external_id"], name="listing_platform_external_id"),
        ]
        indexes = [
            models.Index(fields=["status", "ends_at"], name="listing_status_ends"),
            models.Index(fields=["platform", "status"], name="listing_platform_status"),
            models.Index(fields=["registration"], name="listing_registration"),
            # the hot path: matching and the portal only ever read cars that are still available
            models.Index(fields=["make", "model", "suggested_price_pence"], name="listing_live_match",
                         condition=Q(status__in=["live", "ending_soon"])),
        ]
        ordering = ["ends_at"]

    def __str__(self):
        return f"{self.get_platform_display()} {self.registration or self.external_id} {self.title}".strip()

    def save(self, *args, **kwargs):
        self.make_key = keys.make_key(self.make)
        self.gearbox_kind = keys.gearbox_kind(self.gearbox)
        self.colour_key = keys.colour_key(self.colour)
        if kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = {*kwargs["update_fields"], "make_key", "gearbox_kind", "colour_key"}
        super().save(*args, **kwargs)

    @property
    def margin_pence(self):
        """Selling price minus buy price minus prep cost. Staff only."""
        if self.suggested_price_pence is None or self.buy_price_pence is None or self.prep_cost_pence is None:
            return None
        return self.suggested_price_pence - self.buy_price_pence - self.prep_cost_pence


class ListingEmbedding(models.Model):
    """The vector for a car's description (pgvector). Used only to rank cars that already passed
    the hard filters."""

    listing = models.OneToOneField(Listing, primary_key=True, on_delete=models.CASCADE, related_name="embedding_row")
    embedding = VectorField(dimensions=1536)
    text_hash = models.CharField(max_length=64, help_text="Of the text and model that were embedded")
    stale = models.BooleanField(default=False, db_index=True, help_text="The car's description has changed")
    embedded_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"embedding for {self.listing_id}"


class ListingPhoto(UUIDModel):
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="photos")
    position = models.PositiveSmallIntegerField()
    label = models.CharField(max_length=120, blank=True)
    hidden = models.BooleanField(default=False, db_default=False,
                                 help_text="Hidden from customers by staff. Damage photos are hidden anyway.")
    source_url = models.URLField(max_length=1000)
    image = models.FileField(upload_to=photo_path, max_length=255, blank=True)
    thumbnail = models.FileField(upload_to=thumbnail_path, max_length=255, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["listing", "position"], name="listing_photo_position"),
        ]
        ordering = ["position"]

    def __str__(self):
        return f"{self.listing_id} #{self.position}"


class CarLink(UUIDModel):
    """The public "more photos" page for one car: an unguessable short code instead of anything that
    identifies the car or where it came from. The page shows customer fields only."""

    listing = models.OneToOneField(Listing, on_delete=models.CASCADE, related_name="public_link")
    token = models.CharField(max_length=24, unique=True)
    created_at = models.DateTimeField(default=timezone.now)
    opened_count = models.PositiveIntegerField(default=0)
    last_opened_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"/c/{self.token}"
