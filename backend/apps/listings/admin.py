from django.contrib import admin

from .models import Listing, ListingPhoto


def pounds(pence):
    return "-" if pence is None else f"£{pence / 100:,.0f}"


class ListingPhotoInline(admin.TabularInline):
    model = ListingPhoto
    extra = 0
    fields = ("position", "label", "source_url", "image", "thumbnail")
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = ("registration", "platform", "make", "model", "year", "mileage", "status", "details_status",
                    "ends_at", "buy_price", "suggested_price", "margin", "photo_count")
    list_filter = ("platform", "status", "details_status", "source", "sale_type", "buy_price_kind")
    search_fields = ("registration", "vin", "make", "model", "external_id", "title")
    date_hierarchy = "ends_at"
    inlines = [ListingPhotoInline]
    readonly_fields = ("id", "platform", "external_id", "raw", "first_seen_at", "last_seen_at", "last_alert_at",
                       "last_captured_at", "last_run", "photo_count", "cover_thumbnail", "margin",
                       "created_at", "updated_at")

    @admin.display(description="Buy price", ordering="buy_price_pence")
    def buy_price(self, obj):
        return pounds(obj.buy_price_pence)

    @admin.display(description="Selling price", ordering="suggested_price_pence")
    def suggested_price(self, obj):
        return pounds(obj.suggested_price_pence)

    @admin.display(description="Margin")
    def margin(self, obj):
        margin = obj.margin_pence
        if margin is None:
            return "-"
        band = "green" if margin >= 200000 else "amber" if margin >= 100000 else "red"
        return f"{pounds(margin)} ({band})"

    def save_model(self, request, obj, form, change):
        # a person changing the selling price in the manual update queue keeps it
        if change and "suggested_price_pence" in form.changed_data:
            obj.price_overridden = True
        super().save_model(request, obj, form, change)
