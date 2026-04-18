from rest_framework import serializers
from .models import Payment, PaymentEvent


class PaymentEventSerializer(serializers.ModelSerializer):
    class Meta:
        model  = PaymentEvent
        fields = ["id", "event_type", "payload", "created_at"]


class PaymentSerializer(serializers.ModelSerializer):
    events = PaymentEventSerializer(many=True, read_only=True)

    class Meta:
        model  = Payment
        fields = [
            "id", "amount", "currency", "status", "purpose",
            "reference_type", "reference_id",
            "gateway", "gateway_order_id", "gateway_payment_id",
            "payment_method", "payment_reference", "notes",
            "paid_at", "created_at", "updated_at",
            "events",
        ]
        read_only_fields = [
            "id", "status", "gateway_order_id", "gateway_payment_id",
            "paid_at", "created_at", "updated_at", "events",
        ]


class CreatePaymentSerializer(serializers.Serializer):
    amount            = serializers.DecimalField(max_digits=10, decimal_places=2)
    currency          = serializers.CharField(max_length=3, default="INR")
    purpose           = serializers.ChoiceField(choices=["membership", "booking", "other"])
    reference_type    = serializers.CharField(required=False, default="")
    reference_id      = serializers.UUIDField(required=False, allow_null=True, default=None)
    gateway           = serializers.ChoiceField(choices=["offline", "razorpay", "stripe"], default="offline")
    payment_method    = serializers.ChoiceField(
        choices=["cash", "upi", "bank_transfer", "card", "online"],
        required=False, allow_null=True, default=None,
    )
    payment_reference = serializers.CharField(required=False, default="")
    notes             = serializers.CharField(required=False, default="")


class MarkSuccessSerializer(serializers.Serializer):
    payment_method    = serializers.ChoiceField(
        choices=["cash", "upi", "bank_transfer", "card", "online"],
        required=False, allow_null=True, default=None,
    )
    payment_reference = serializers.CharField(required=False, default="")
    notes             = serializers.CharField(required=False, default="")


class WebhookSerializer(serializers.Serializer):
    gateway   = serializers.ChoiceField(choices=["razorpay", "stripe"])
    signature = serializers.CharField()
