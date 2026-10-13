from django.db import models
from django.utils import timezone

from apps.core.models import UUIDModel


class AiUsage(UUIDModel):
    """One row per AI call: what it was for, which model and prompt, and what it cost."""

    feature = models.CharField(max_length=60, db_index=True)
    model = models.CharField(max_length=120)
    prompt_version = models.CharField(max_length=40)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    ok = models.BooleanField(default=True)
    error = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "AI usage"

    def __str__(self):
        return f"{self.feature} {self.model} {self.created_at:%Y-%m-%d %H:%M}"
