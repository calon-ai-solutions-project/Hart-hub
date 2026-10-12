import hashlib
import secrets

from django.db import models
from django.utils import timezone

from apps.core.models import UUIDModel
from apps.listings.models import Platform


class Alert(UUIDModel):
    """A saved-search alert email from a platform. `raw` is private: never shown outside the admin."""

    platform = models.CharField(max_length=20, choices=Platform.choices)
    received_at = models.DateTimeField(default=timezone.now, db_index=True)
    sender = models.CharField(max_length=255, blank=True)
    subject = models.CharField(max_length=255, blank=True)
    raw = models.TextField()
    parsed_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-received_at"]

    def __str__(self):
        return f"{self.platform} alert {self.received_at:%Y-%m-%d %H:%M} ({self.parsed_count} listings)"


class SyncRun(UUIDModel):
    """One sync per platform per UK day (contract Schedule 1)."""

    class Status(models.TextChoices):
        READY = "ready", "Ready"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        STOPPED_BY_PLATFORM = "stopped_by_platform", "Stopped by platform"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"

    FINISHED = (Status.COMPLETED, Status.STOPPED_BY_PLATFORM, Status.FAILED, Status.SKIPPED)

    platform = models.CharField(max_length=20, choices=Platform.choices)
    uk_date = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.READY)
    stop_reason = models.CharField(max_length=255, blank=True)
    allowlist = models.JSONField(default=list, help_text="The only URLs this run may open")
    created_at = models.DateTimeField(default=timezone.now)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    listings_captured = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["platform", "uk_date"], name="sync_run_once_per_platform_per_day"),
        ]
        ordering = ["-uk_date", "platform"]

    def __str__(self):
        return f"{self.platform} {self.uk_date} ({self.status})"


class SyncLog(UUIDModel):
    """Every URL a run opened (or refused, or never reached)."""

    class Outcome(models.TextChoices):
        CAPTURED = "captured", "Captured"
        SKIPPED = "skipped", "Skipped"
        STOPPED = "stopped", "Stopped by platform"
        FAILED = "failed", "Failed"
        REFUSED = "refused", "Refused (not on the allowlist)"

    run = models.ForeignKey(SyncRun, on_delete=models.CASCADE, related_name="log")
    url = models.URLField(max_length=500)
    outcome = models.CharField(max_length=10, choices=Outcome.choices)
    http_status = models.PositiveSmallIntegerField(null=True, blank=True)
    detail = models.CharField(max_length=255, blank=True)
    at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["at"]

    def __str__(self):
        return f"{self.outcome} {self.url}"


class RunnerToken(UUIDModel):
    """A machine credential for the sync runner. Only its hash is stored."""

    PREFIX = "hhr_"

    name = models.CharField(max_length=100)
    key_hash = models.CharField(max_length=64, unique=True, editable=False)
    created_at = models.DateTimeField(default=timezone.now)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.name

    @staticmethod
    def hash_key(key):
        return hashlib.sha256(key.encode()).hexdigest()

    @classmethod
    def issue(cls, name):
        """Create a token and return (token, key). The key is shown once and cannot be recovered."""
        key = cls.PREFIX + secrets.token_urlsafe(32)
        return cls.objects.create(name=name, key_hash=cls.hash_key(key)), key
