from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import TimeStampedModel, UUIDModel


class Customer(UUIDModel):
    """Someone who messaged the business number about buying a car. Personal contacts are never stored."""

    phone = models.CharField(max_length=20, unique=True, help_text="E.164, e.g. +447700900123")
    name = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return self.name or self.phone


class Enquiry(TimeStampedModel):
    """One customer journey on one channel: chat (or form) -> quotes -> 5 options -> hand-over.

    AI reads the first message and, while the Hub is chatting, each reply. It only extracts what the customer
    asked for; every message the customer receives is written by code.
    """

    class Step(models.TextChoices):
        CHATTING = "chatting", "Chatting: asking what they want"
        FORM_SENT = "form_sent", "Form link sent"
        FORM_DONE = "form_done", "Details received"
        QUOTING = "quoting", "Getting quotes"
        AWAITING_APPROVAL = "awaiting_approval", "Options ready: waiting for approval"
        OPTIONS_SENT = "options_sent", "Options sent"
        HANDED_OVER = "handed_over", "Customer chose a car"
        NEEDS_PERSON = "needs_person", "Needs a person"
        CLOSED = "closed", "Closed"

    class Intent(models.TextChoices):
        CAR = "car_enquiry", "Car enquiry"
        FINANCE = "finance", "Finance / quote"
        OTHER = "other_business", "Other business"
        UNSURE = "unsure", "Not sure"

    BOT_STEPS = (Step.CHATTING, Step.FORM_SENT, Step.FORM_DONE, Step.QUOTING, Step.AWAITING_APPROVAL, Step.OPTIONS_SENT)

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="enquiries")
    channel = models.CharField(max_length=20, default="simulator", help_text="simulator now; whatsapp later")
    business_number = models.CharField(max_length=20, blank=True)
    intent = models.CharField(max_length=20, choices=Intent.choices)
    intent_confidence = models.FloatField(null=True, blank=True)
    intent_by = models.CharField(max_length=10, blank=True, help_text="ai or rules")
    step = models.CharField(max_length=20, choices=Step.choices)
    needs_person_reason = models.CharField(max_length=200, blank=True)
    answers = models.JSONField(default=dict, db_default={}, blank=True,
                               help_text="What the customer has told the chatbot so far, in the form's fields")
    asked = models.JSONField(default=list, db_default=[], blank=True, help_text="The chatbot's questions already asked")
    form_token = models.CharField(max_length=32, unique=True, null=True, blank=True)
    form_sent_at = models.DateTimeField(null=True, blank=True)
    form_submitted_at = models.DateTimeField(null=True, blank=True)
    requirement = models.ForeignKey("matching.Requirement", null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+")
    quotes_tried = models.PositiveSmallIntegerField(default=0)
    quoting_started_at = models.DateTimeField(null=True, blank=True)
    quoting_finished_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+")
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+")
    chosen_number = models.PositiveSmallIntegerField(null=True, blank=True)
    last_inbound_at = models.DateTimeField(null=True, blank=True)
    nudged = models.BooleanField(default=False, help_text="The one 'still working on it' reply has been sent")

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.customer} · {self.get_step_display()}"


class EnquiryMessage(UUIDModel):
    class Direction(models.TextChoices):
        IN = "in", "From the customer"
        OUT = "out", "To the customer"

    class Sender(models.TextChoices):
        CUSTOMER = "customer", "Customer"
        BOT = "bot", "Hub"
        STAFF = "staff", "Staff"

    enquiry = models.ForeignKey(Enquiry, on_delete=models.CASCADE, related_name="messages")
    direction = models.CharField(max_length=3, choices=Direction.choices)
    sender = models.CharField(max_length=10, choices=Sender.choices)
    sent_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="+")
    body = models.TextField()
    media_url = models.URLField(max_length=500, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["created_at"]


class EnquiryOption(UUIDModel):
    """One of the cars prepared for the customer, with its Codeweavers quote. The cards are kept as they
    were sent, so the record stays right even after the car or quote is gone."""

    enquiry = models.ForeignKey(Enquiry, on_delete=models.CASCADE, related_name="options")
    number = models.PositiveSmallIntegerField()
    listing = models.ForeignKey("listings.Listing", null=True, on_delete=models.SET_NULL, related_name="+")
    quote = models.ForeignKey("quotes.Quote", null=True, on_delete=models.SET_NULL, related_name="+")
    customer = models.JSONField(help_text="Only customer-safe fields: the car card and the quote figures")
    staff = models.JSONField(help_text="Staff only: source, platform price, markup, quote reference, match reason")
    sent = models.BooleanField(default=False)

    class Meta:
        ordering = ["number"]

