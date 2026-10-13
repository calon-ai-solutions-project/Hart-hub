from django.contrib import admin

from .models import AiUsage


@admin.register(AiUsage)
class AiUsageAdmin(admin.ModelAdmin):
    list_display = ("created_at", "feature", "model", "prompt_version", "input_tokens", "output_tokens",
                    "cost_usd", "ok")
    list_filter = ("feature", "ok", "model")
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
