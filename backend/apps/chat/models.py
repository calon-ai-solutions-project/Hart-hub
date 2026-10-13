from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import TimeStampedModel, UUIDModel


class Conversation(TimeStampedModel):
    """One salesperson's chat with the stock chatbot about one customer's request."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chat_conversations")
    title = models.CharField(max_length=120, blank=True)
    requirement = models.ForeignKey("matching.Requirement", null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+")

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title or f"Chat {self.created_at:%d %b %H:%M}"


class Message(UUIDModel):
    class Role(models.TextChoices):
        BOT = "bot", "Bot"
        USER = "user", "User"

    class Kind(models.TextChoices):
        TEXT = "text", "Text"
        FORM = "form", "Enquiry form"
        OPTIONS = "options", "Option cards"
        QUOTES = "quotes", "Finance quotes"

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=4, choices=Role.choices)
    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.TEXT)
    body = models.TextField(blank=True)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["created_at"]
