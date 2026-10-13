from django.contrib import admin

from .models import Match, Requirement


class MatchInline(admin.TabularInline):
    model = Match
    extra = 0
    fields = ("rank", "listing", "score", "reason", "flags")
    readonly_fields = fields
    can_delete = False


@admin.register(Requirement)
class RequirementAdmin(admin.ModelAdmin):
    list_display = ("created_at", "make", "model", "gearbox", "colours", "deposit_pence", "monthly_budget_pence",
                    "created_by")
    list_filter = ("channel", "gearbox")
    inlines = [MatchInline]
