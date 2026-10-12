from django.contrib import admin, messages
from django.utils import timezone

from .models import Alert, RunnerToken, SyncLog, SyncRun


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ("received_at", "platform", "sender", "subject", "parsed_count")
    list_filter = ("platform",)
    date_hierarchy = "received_at"
    readonly_fields = ("id", "platform", "received_at", "sender", "subject", "raw", "parsed_count")

    def has_add_permission(self, request):
        return False


class SyncLogInline(admin.TabularInline):
    model = SyncLog
    extra = 0
    fields = ("at", "outcome", "http_status", "url", "detail")
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(SyncRun)
class SyncRunAdmin(admin.ModelAdmin):
    list_display = ("uk_date", "platform", "status", "stop_reason", "allowlisted", "listings_captured",
                    "started_at", "finished_at")
    list_filter = ("platform", "status")
    date_hierarchy = "uk_date"
    inlines = [SyncLogInline]
    readonly_fields = ("id", "platform", "uk_date", "status", "stop_reason", "allowlist", "created_at",
                       "started_at", "finished_at", "listings_captured")

    @admin.display(description="Allowlisted")
    def allowlisted(self, obj):
        return len(obj.allowlist)

    def has_add_permission(self, request):
        return False  # runs are created by the scheduler only: once per platform per UK day

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(RunnerToken)
class RunnerTokenAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at", "last_used_at", "revoked_at")
    readonly_fields = ("id", "created_at", "last_used_at", "revoked_at")
    actions = ["revoke"]

    def save_model(self, request, obj, form, change):
        if change:
            return super().save_model(request, obj, form, change)
        token, key = RunnerToken.issue(obj.name)
        obj.pk = token.pk
        messages.warning(request, f"Runner token (shown once, store it in the runner's .env): {key}")

    @admin.action(description="Revoke selected tokens")
    def revoke(self, request, queryset):
        queryset.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())
