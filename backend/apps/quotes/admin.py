from django.contrib import admin

from .models import Quote


@admin.register(Quote)
class QuoteAdmin(admin.ModelAdmin):
    list_display = ("created_at", "registration", "status", "monthly", "apr", "term_months", "deposit", "lender",
                    "requested_by", "error")
    list_filter = ("status", "lender", "product")
    search_fields = ("registration", "quote_ref")
    date_hierarchy = "created_at"

    @admin.display(description="Monthly")
    def monthly(self, obj):
        return "-" if obj.monthly_pence is None else f"£{obj.monthly_pence / 100:,.2f}"

    @admin.display(description="Deposit")
    def deposit(self, obj):
        return f"£{obj.deposit_pence / 100:,.0f}"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False  # figures come from Codeweavers and are never edited by hand
