from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.payments.gateways.razorpay_adapter import RazorpayAdapter, RazorpayError
from apps.payments.models import Payment, PaymentGateway
from apps.payments.services.config_service import get_active_payment_config, PaymentConfigError
from apps.payments.serializers import (
    CreatePaymentSerializer,
    MarkSuccessSerializer,
    PaymentSerializer,
    WebhookSerializer,
)
from apps.payments.services.payment_service import PaymentService, PaymentError


def _get_membership(reference_type, reference_id, tenant):
    """Return Membership or None — isolated lazy import avoids circular dependency."""
    if reference_type != "membership" or not reference_id:
        return None
    try:
        from apps.memberships.models import Membership
        return Membership.base_objects.get(pk=reference_id, tenant=tenant)
    except Exception:
        return None


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_payment(request):
    """
    POST /api/payments/create/

    Offline payments → returns standard PaymentSerializer response.
    gateway=razorpay → creates Razorpay order and returns checkout data:
        {
            "payment_id": "<uuid>",
            "order_id":   "order_Xxx",
            "amount":     150000,        # paise
            "currency":   "INR",
            "key":        "rzp_test_...",
        }
    """
    ser = CreatePaymentSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    d = ser.validated_data

    tenant = request.user.tenant

    # Overpayment guard for membership payments
    membership = _get_membership(d["reference_type"], d["reference_id"], tenant)
    if membership:
        if membership.status == "cancelled":
            return Response(
                {"detail": "Cannot record payment for a cancelled membership."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if d["amount"] > membership.balance_amount:
            return Response(
                {
                    "detail": (
                        f"Amount ₹{d['amount']} exceeds outstanding balance "
                        f"of ₹{membership.balance_amount}."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

    payment = PaymentService.create_payment(
        tenant=tenant,
        amount=d["amount"],
        currency=d["currency"],
        purpose=d["purpose"],
        reference_type=d["reference_type"],
        reference_id=d["reference_id"],
        gateway=d["gateway"],
        payment_method=d["payment_method"],
        payment_reference=d["payment_reference"],
        notes=d["notes"],
        created_by=request.user,
    )

    # Razorpay: load tenant config, create gateway order, return checkout data
    if d["gateway"] == PaymentGateway.RAZORPAY:
        try:
            config     = get_active_payment_config(tenant, "razorpay")
            order_data = RazorpayAdapter(config).create_order(payment)
        except PaymentConfigError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except RazorpayError as exc:
            # Leave payment CREATED so admin can retry or convert to offline
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        PaymentService.mark_pending(payment, gateway_order_id=order_data["order_id"])

        return Response(
            {
                "payment_id": str(payment.id),
                "order_id":   order_data["order_id"],
                "amount":     order_data["amount"],
                "currency":   order_data["currency"],
                "key":        order_data["key"],
            },
            status=status.HTTP_201_CREATED,
        )

    return Response(PaymentSerializer(payment).data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def payment_detail(request, pk):
    """GET /api/payments/{id}/ — retrieve a payment with its event log."""
    try:
        payment = Payment.base_objects.get(pk=pk, tenant=request.user.tenant, is_deleted=False)
    except Payment.DoesNotExist:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    return Response(PaymentSerializer(payment).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def mark_success(request, pk):
    """POST /api/payments/{id}/mark-success/"""
    try:
        payment = Payment.base_objects.get(pk=pk, tenant=request.user.tenant, is_deleted=False)
    except Payment.DoesNotExist:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

    ser = MarkSuccessSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    d = ser.validated_data

    payment = PaymentService.mark_payment_success(
        payment,
        payment_method=d.get("payment_method"),
        payment_reference=d.get("payment_reference", ""),
    )
    return Response(PaymentSerializer(payment).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def mark_failed(request, pk):
    """POST /api/payments/{id}/mark-failed/"""
    try:
        payment = Payment.base_objects.get(pk=pk, tenant=request.user.tenant, is_deleted=False)
    except Payment.DoesNotExist:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    try:
        payment = PaymentService.mark_payment_failed(payment, reason=request.data.get("reason", ""))
    except PaymentError as e:
        return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(PaymentSerializer(payment).data)


@api_view(["POST"])
def webhook(request):
    """
    POST /api/payments/webhook/?gateway=razorpay
    Raw body + gateway-specific signature header.
    No authentication — verified by signature.
    """
    import json as _json

    # Read raw body FIRST — request.data accesses the same stream and empties it
    try:
        raw_body = request.body
        payload  = _json.loads(raw_body)
    except (ValueError, Exception):
        return Response({"detail": "Invalid JSON body."}, status=status.HTTP_400_BAD_REQUEST)

    gateway   = request.query_params.get("gateway", "")
    signature = (
        request.headers.get("X-Razorpay-Signature", "")
        or request.headers.get("Stripe-Signature", "")
    )

    try:
        payment = PaymentService.handle_webhook(
            gateway=gateway,
            payload=payload,
            raw_body=raw_body,
            signature=signature,
        )
    except PaymentError as e:
        return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    return Response({"status": "ok", "payment_id": str(payment.pk)})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def generate_checkout_link(request):
    """
    POST /api/payments/generate-checkout-link/

    Body: { "payment_id": "<uuid>" }

    Creates a Razorpay order for an existing CREATED/PENDING payment and
    returns the checkout page URL that staff can share with the member.
    """
    payment_id = (request.data or {}).get("payment_id")
    if not payment_id:
        return Response({"detail": "payment_id is required."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        payment = Payment.base_objects.get(
            pk=payment_id,
            tenant=request.user.tenant,
            is_deleted=False,
        )
    except Payment.DoesNotExist:
        return Response({"detail": "Payment not found."}, status=status.HTTP_404_NOT_FOUND)

    if payment.status not in ("CREATED", "PENDING"):
        return Response(
            {"detail": f"Cannot generate checkout link for a {payment.get_status_display()} payment."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Create / reuse gateway order
    if not payment.gateway_order_id:
        try:
            config     = get_active_payment_config(request.user.tenant, "razorpay")
            order_data = RazorpayAdapter(config).create_order(payment)
            PaymentService.mark_pending(payment, gateway_order_id=order_data["order_id"])
        except PaymentConfigError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except RazorpayError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

    from django.urls import reverse
    from django.conf import settings as django_settings
    site_url     = getattr(django_settings, "SITE_URL", "").rstrip("/")
    checkout_url = f"{site_url}{reverse('payments:payment_checkout', kwargs={'pk': payment.pk})}"

    return Response({
        "payment_id":    str(payment.pk),
        "checkout_url":  checkout_url,
        "order_id":      payment.gateway_order_id,
        "amount":        str(payment.amount),
        "currency":      payment.currency,
    })
