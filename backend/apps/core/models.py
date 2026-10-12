import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class UUIDModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class TimeStampedModel(UUIDModel):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Event(UUIDModel):
    """Append-only history. Timelines, dashboards and audits read from here."""

    type = models.CharField(max_length=100, db_index=True)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                              related_name="+")
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-occurred_at"]

    def __str__(self):
        return f"{self.type} @ {self.occurred_at:%Y-%m-%d %H:%M}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("Events are append-only and cannot be changed.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Events are append-only and cannot be deleted.")


class Setting(TimeStampedModel):
    """A configurable default (prep cost, sync slots and so on). Missing rows fall back to DEFAULTS."""

    key = models.CharField(max_length=100, unique=True)
    value = models.JSONField()
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["key"]

    def __str__(self):
        return self.key
