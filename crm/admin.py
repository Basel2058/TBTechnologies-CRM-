from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from . import models

admin.site.site_header = "TBT CRM — الإدارة المتقدمة"
admin.site.site_title = "TBT CRM"


@admin.register(models.User)
class TBTUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("الدور", {"fields": ("role",)}),)
    list_display = ("username", "first_name", "last_name", "role", "is_active")


@admin.register(models.Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("display_name", "phone", "city", "stage", "assigned_to", "next_call_at")
    list_filter = ("stage", "assigned_to", "product", "sector")
    search_fields = ("business_name", "contact_name", "phone", "phone_normalized", "city")


@admin.register(models.Call)
class CallAdmin(admin.ModelAdmin):
    list_display = ("customer", "agent", "outcome", "product", "created_at")
    list_filter = ("outcome", "agent", "product")


@admin.register(models.Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ("customer", "scheduled_at", "meeting_type", "status", "presenter")
    list_filter = ("status", "meeting_type")


@admin.register(models.Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("customer", "product", "monthly_price", "status", "start_date")
    list_filter = ("status", "product")


for model in (models.Sector, models.Product, models.Plan, models.Objection, models.Reason,
              models.MessageTemplate, models.Activity):
    admin.site.register(model)
