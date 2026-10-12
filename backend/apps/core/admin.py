from django.contrib import admin

from .models import Event, Setting


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("occurred_at", "type", "actor")
    list_filter = ("type",)
    date_hierarchy = "occurred_at"
    readonly_fields = ("id", "type", "occurred_at", "actor", "payload")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Setting)
class SettingAdmin(admin.ModelAdmin):
    list_display = ("key", "value", "description", "updated_at")
    search_fields = ("key",)
