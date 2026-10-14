from django.contrib import admin

from .models import Customer, Enquiry, EnquiryMessage, EnquiryOption


class MessageInline(admin.TabularInline):
    model = EnquiryMessage
    extra = 0
    fields = ("created_at", "direction", "sender", "body", "media_url")
    readonly_fields = fields


class OptionInline(admin.TabularInline):
    model = EnquiryOption
    extra = 0
    fields = ("number", "listing", "quote", "sent")
    readonly_fields = fields


@admin.register(Enquiry)
class EnquiryAdmin(admin.ModelAdmin):
    list_display = ("customer", "channel", "intent", "step", "quotes_tried", "assigned_to", "updated_at")
    list_filter = ("step", "intent", "channel")
    search_fields = ("customer__phone",)
    readonly_fields = ("form_token",)
    inlines = [OptionInline, MessageInline]


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("phone", "name", "created_at")
    search_fields = ("phone", "name")
