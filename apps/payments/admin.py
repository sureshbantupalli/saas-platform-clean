from django.contrib import admin
from .models import Payment, PaymentEvent


class PaymentEventInline(admin.TabularInline):
    model       = PaymentEvent
    extra       = 0
    readonly_fields = ("event_type", "payload", "created_at")
    can_delete  = False


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display  = ("id", "tenant", "amount", "currency", "status", "purpose", "payment_method", "paid_at", "created_at")
    list_filter   = ("status", "purpose", "gateway", "payment_method")
    search_fields = ("id", "gateway_order_id", "gateway_payment_id", "payment_reference")
    readonly_fields = ("id", "created_at", "updated_at", "paid_at")
    inlines       = [PaymentEventInline]
