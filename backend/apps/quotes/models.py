from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import UUIDModel


def quote_pdf_path(quote, filename):
    return f"quotes/{quote.created_at:%Y/%m}/{quote.id}.pdf"


class Quote(UUIDModel):
    """A Codeweavers finance quote for one car. Every figure comes from Codeweavers; none is calculated here.

    Quotes only: the Hub never starts a finance application.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Waiting"
        RUNNING = "running", "Getting quote"
        DONE = "done", "Quoted"
        FAILED = "failed", "Finance quote to follow"

    listing = models.ForeignKey("listings.Listing", on_delete=models.CASCADE, related_name="quotes")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    conversation = models.ForeignKey("chat.Conversation", null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name="quotes")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    error = models.CharField(max_length=255, blank=True)

    # what was sent to Codeweavers
    registration = models.CharField(max_length=16)
    mileage = models.PositiveIntegerField(help_text="The car's mileage plus the extra-mileage setting")
    cash_price_pence = models.IntegerField()
    deposit_pence = models.IntegerField(default=0)
    term_months = models.PositiveSmallIntegerField()
    annual_mileage = models.PositiveIntegerField(default=8000, help_text="Annual Mileage asked for")
    annual_mileage_applied = models.BooleanField(
        default=False, help_text="Whether the product has an Annual Mileage field (PCP does, Hire Purchase does not)")
    product = models.CharField(max_length=120, help_text="The product asked for")
    product_quoted = models.CharField(max_length=120, blank=True, help_text="The product Codeweavers actually quoted")
    note = models.CharField(max_length=255, blank=True, help_text="Staff only: why a different kind of product was quoted")
    credit_tier = models.CharField(max_length=40)

    # what came back
    monthly_pence = models.IntegerField(null=True, blank=True)
    final_payment_pence = models.IntegerField(null=True, blank=True)
    balloon_pence = models.IntegerField(null=True, blank=True, help_text="PCP: the optional final payment")
    apr = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    amount_of_credit_pence = models.IntegerField(null=True, blank=True)
    charges_pence = models.IntegerField(null=True, blank=True)
    total_payable_pence = models.IntegerField(null=True, blank=True)
    fees_text = models.CharField(max_length=255, blank=True)
    lender = models.CharField(max_length=120, blank=True)
    product_family = models.CharField(max_length=60, blank=True)
    quote_ref = models.CharField(max_length=64, blank=True, help_text="Staff only: never shown to a customer")
    raw = models.JSONField(default=dict, blank=True)
    pdf = models.FileField(upload_to=quote_pdf_path, max_length=255, blank=True,
                           help_text="Codeweavers' own quote document")

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    INPUTS = ("listing_id", "registration", "mileage", "cash_price_pence", "deposit_pence", "term_months",
              "annual_mileage", "product", "credit_tier")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.registration} {self.get_status_display()}"

    @property
    def finished(self):
        return self.status in (self.Status.DONE, self.Status.FAILED)
