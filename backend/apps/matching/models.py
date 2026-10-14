from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel, UUIDModel


class Requirement(TimeStampedModel):
    """What a customer wants, as captured by the enquiry form. Money is integer pence."""

    class Gearbox(models.TextChoices):
        ANY = "", "Any"
        AUTO = "auto", "Automatic"
        MANUAL = "manual", "Manual"

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    channel = models.CharField(max_length=20, default="chatbot")
    make = models.CharField(max_length=60, blank=True)
    model = models.CharField(max_length=80, blank=True)
    colours = models.JSONField(default=list, blank=True)
    colour_only = models.BooleanField(default=False, help_text="'Only grey': other colours are not shown at all")
    gearbox = models.CharField(max_length=10, choices=Gearbox.choices, blank=True)
    deposit_pence = models.IntegerField(null=True, blank=True)
    monthly_budget_pence = models.IntegerField(null=True, blank=True)
    max_price_pence = models.IntegerField(null=True, blank=True, help_text="A cash budget, if one was given")
    needed_by = models.CharField(max_length=120, blank=True)
    part_exchange = models.CharField(max_length=120, blank=True, default="", db_default="",
                                     help_text="The car the customer wants to trade in, as they described it")
    sort = models.CharField(max_length=10, blank=True, choices=[
        ("", "Best match"), ("price", "Cheapest first"), ("year", "Newest first"), ("mileage", "Lowest mileage")])
    notes = models.TextField(blank=True, help_text="What was typed, for matching loose wording (trim, spec)")

    FIELDS = ("make", "model", "colours", "colour_only", "gearbox", "deposit_pence", "monthly_budget_pence",
              "max_price_pence", "needed_by", "part_exchange", "sort")

    def __str__(self):
        return f"{self.make} {self.model}".strip() or "Any car"

    @property
    def search_text(self):
        """The request as one line of words, for vector search."""
        gearbox = {"auto": "automatic", "manual": "manual"}.get(self.gearbox, "")
        return " ".join(part for part in (self.make, self.model, " ".join(self.colours), gearbox, self.notes) if part)

    @property
    def has_budget(self):
        return bool(self.monthly_budget_pence or self.max_price_pence)

    @property
    def searchable(self):
        """Enough to search on: a car, a budget, or any other filter that narrows the stock."""
        return bool(self.make or self.model or self.has_budget or self.gearbox or self.colours)


class Match(UUIDModel):
    """A listing offered for a requirement. Score and reason are staff only."""

    requirement = models.ForeignKey(Requirement, on_delete=models.CASCADE, related_name="matches")
    listing = models.ForeignKey("listings.Listing", on_delete=models.CASCADE, related_name="+")
    rank = models.PositiveSmallIntegerField()
    score = models.FloatField()
    reason = models.CharField(max_length=255, blank=True)
    flags = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["rank"]
