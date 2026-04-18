"""
PaymentService — gateway-agnostic, idempotent, fully audited.

Rules enforced here:
- Only one SUCCESS per payment (idempotent webhook / manual mark)
- Tenant isolation via base_objects + explicit tenant kwarg
- Every state change writes a PaymentEvent row
- Signals fired AFTER the DB write so the DB is always consistent first
"""
import hashlib
import hmac
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.payments.models import Payment, PaymentEvent, PaymentStatus, PaymentGateway
from apps.payments.signals import payment_success, payment_failed


class PaymentError(Exception):
    pass


class PaymentService:

    # ── Create ────────────────────────────────────────────────────────────────

    @staticmethod
    @transaction.atomic
    def create_payment(
        *,
        tenant,
        amount: Decimal,
        purpose: str,
        reference_type: str = "",
        reference_id=None,
        currency: str = "INR",
        gateway: str = PaymentGateway.OFFLINE,
        payment_method: str = None,
        payment_reference: str = "",
        notes: str = "",
        created_by=None,
    ) -> Payment:
        payment = Payment.base_objects.create(
            tenant=tenant,
            amount=amount,
            currency=currency,
            status=PaymentStatus.CREATED,
            purpose=purpose,
            reference_type=reference_type,
            reference_id=reference_id,
            gateway=gateway,
            payment_method=payment_method,
            payment_reference=payment_reference,
            notes=notes,
            created_by=created_by,
        )
        PaymentEvent.objects.create(
            payment=payment,
            event_type="CREATED",
            payload={"amount": str(amount), "purpose": purpose},
        )
        return payment

    # ── Mark Pending ──────────────────────────────────────────────────────────

    @staticmethod
    @transaction.atomic
    def mark_pending(payment: Payment, gateway_order_id: str = "") -> Payment:
        if payment.status == PaymentStatus.SUCCESS:
            return payment   # already terminal — skip

        payment.status = PaymentStatus.PENDING
        if gateway_order_id:
            payment.gateway_order_id = gateway_order_id
        payment.save(update_fields=["status", "gateway_order_id", "updated_at"])
        PaymentEvent.objects.create(
            payment=payment,
            event_type="PENDING",
            payload={"gateway_order_id": gateway_order_id},
        )
        return payment

    # ── Mark Success ──────────────────────────────────────────────────────────

    @staticmethod
    @transaction.atomic
    def mark_payment_success(
        payment: Payment,
        gateway_payment_id: str = "",
        gateway_signature: str = "",
        payment_method: str = None,
        payment_reference: str = "",
    ) -> Payment:
        """
        Idempotent: if already SUCCESS, logs the duplicate attempt and returns.
        Fires `payment_success` signal after DB commit.
        """
        if payment.status == PaymentStatus.SUCCESS:
            PaymentEvent.objects.create(
                payment=payment,
                event_type="DUPLICATE_SKIP",
                payload={"reason": "already SUCCESS"},
            )
            return payment

        payment.status             = PaymentStatus.SUCCESS
        payment.paid_at            = timezone.now()
        payment.gateway_payment_id = gateway_payment_id
        payment.gateway_signature  = gateway_signature
        if payment_method:
            payment.payment_method = payment_method
        if payment_reference:
            payment.payment_reference = payment_reference
        payment.save(update_fields=[
            "status", "paid_at", "gateway_payment_id", "gateway_signature",
            "payment_method", "payment_reference", "updated_at",
        ])
        PaymentEvent.objects.create(
            payment=payment,
            event_type="SUCCESS",
            payload={
                "gateway_payment_id": gateway_payment_id,
                "paid_at": str(payment.paid_at),
            },
        )
        # Fire signal — receivers handle downstream work (membership activation etc.)
        transaction.on_commit(lambda: payment_success.send(sender=Payment, payment=payment))
        return payment

    # ── Mark Failed ───────────────────────────────────────────────────────────

    @staticmethod
    @transaction.atomic
    def mark_payment_failed(payment: Payment, reason: str = "") -> Payment:
        if payment.status == PaymentStatus.SUCCESS:
            raise PaymentError("Cannot fail an already-successful payment.")

        payment.status = PaymentStatus.FAILED
        payment.save(update_fields=["status", "updated_at"])
        PaymentEvent.objects.create(
            payment=payment,
            event_type="FAILED",
            payload={"reason": reason},
        )
        transaction.on_commit(lambda: payment_failed.send(sender=Payment, payment=payment))
        return payment

    # ── Handle Webhook (Razorpay / Stripe) ────────────────────────────────────

    @staticmethod
    def handle_webhook(
        *,
        gateway: str,
        payload: dict,
        raw_body: bytes,
        signature: str,
    ) -> Payment:
        """
        Verifies gateway signature using the tenant's own webhook_secret,
        then transitions payment to SUCCESS or FAILED idempotently.

        No @transaction.atomic here — each state-transition method (mark_payment_success,
        mark_payment_failed) manages its own atomic block. This ensures that the WEBHOOK
        event log and AMOUNT_MISMATCH events are committed to the DB even when a
        PaymentError is raised to return a 400 response to the caller.
        """
        if gateway == PaymentGateway.RAZORPAY:
            return PaymentService._handle_razorpay_webhook(payload, raw_body, signature)
        raise PaymentError(f"Unsupported gateway for webhook: {gateway}")

    @staticmethod
    def _handle_razorpay_webhook(payload, raw_body, signature):
        import logging as _logging
        _logger = _logging.getLogger("apps.payments")

        event             = payload.get("event", "")
        entity            = payload.get("payload", {}).get("payment", {}).get("entity", {})
        order_id          = entity.get("order_id", "")
        payment_id        = entity.get("id", "")
        amount_paise      = entity.get("amount")   # None if key absent — intentional, not 0
        currency_received = entity.get("currency", "")

        # ── Step 1: order_id must be present ─────────────────────────────────
        # An empty order_id could match offline payments that never received a
        # gateway order (gateway_order_id=""). Reject before any DB read.
        if not order_id:
            raise PaymentError("Webhook rejected: missing order_id.")

        # ── Step 2: locate payment by gateway_order_id (READ only) ───────────
        payment = Payment.base_objects.filter(
            gateway_order_id=order_id, is_deleted=False
        ).first()
        if not payment:
            raise PaymentError(f"No payment found for order_id={order_id}")

        # ── Step 3: defense-in-depth — stored order_id must match exactly ─────
        # The filter above guarantees this; the explicit check is a contract
        # assertion that prevents any future loosening of the filter from silently
        # processing the wrong payment.
        if payment.gateway_order_id != order_id:
            _logger.error(
                "Razorpay webhook rejected: order_id mismatch",
                extra={
                    "reason":   "order_mismatch",
                    "expected": payment.gateway_order_id,
                    "received": order_id,
                    "payment":  str(payment.id),
                },
            )
            PaymentEvent.objects.create(
                payment=payment,
                event_type="ORDER_MISMATCH",
                payload={
                    "reason":   "order_mismatch",
                    "expected": payment.gateway_order_id,
                    "received": order_id,
                },
            )
            PaymentService.mark_payment_failed(payment, reason="order_mismatch")
            raise PaymentError(
                f"Order ID mismatch: expected {payment.gateway_order_id!r}, received {order_id!r}."
            )

        # ── Step 4: load tenant-specific webhook secret (READ only) ──────────
        from apps.payments.services.config_service import get_active_payment_config, PaymentConfigError
        try:
            config         = get_active_payment_config(payment.tenant, "razorpay")
            webhook_secret = config.webhook_secret
        except PaymentConfigError as exc:
            raise PaymentError(str(exc))

        # ── Step 5: verify HMAC-SHA256 signature ─────────────────────────────
        # This is the FIRST DB write gate. Nothing is written to the DB before
        # this point, so an invalid signature has zero side effects.
        expected_sig = hmac.HMAC(
            webhook_secret.encode(), raw_body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected_sig, signature):
            raise PaymentError("Invalid Razorpay webhook signature.")

        # ── Step 6: idempotency — already SUCCESS → acknowledge, no side effects
        # Short-circuit here (after signature verification, before re-running
        # amount/currency checks) so a duplicate confirmed webhook does not
        # re-trigger membership activation or produce a second WEBHOOK event.
        if payment.status == PaymentStatus.SUCCESS:
            PaymentEvent.objects.create(
                payment=payment,
                event_type="DUPLICATE_SKIP",
                payload={"reason": "already SUCCESS", "event": event},
            )
            return payment

        # ── Step 7: log the verified, non-duplicate incoming webhook ──────────
        PaymentEvent.objects.create(
            payment=payment,
            event_type="WEBHOOK",
            payload={"event": event, "razorpay_payment_id": payment_id},
        )

        if event == "payment.captured":
            expected_paise = int(payment.amount * 100)

            # ── Amount guard ──────────────────────────────────────────────────
            # Strict equality — a None or 0 paise value must NOT bypass this
            # check. The previous falsy-check bug (`if amount_paise and ...`)
            # allowed amount=0 to skip validation and mark payment SUCCESS.
            if amount_paise is None or amount_paise != expected_paise:
                _logger.warning(
                    "Razorpay webhook rejected: amount mismatch",
                    extra={
                        "reason":   "amount_mismatch",
                        "expected": expected_paise,
                        "received": amount_paise,
                        "order_id": order_id,
                    },
                )
                PaymentEvent.objects.create(
                    payment=payment,
                    event_type="AMOUNT_MISMATCH",
                    payload={
                        "reason":         "amount_mismatch",
                        "expected_paise": expected_paise,
                        "received_paise": amount_paise,
                        "order_id":       order_id,
                    },
                )
                PaymentService.mark_payment_failed(
                    payment,
                    reason=f"amount_mismatch: expected {expected_paise} paise, received {amount_paise} paise",
                )
                raise PaymentError(
                    f"Amount mismatch: expected {expected_paise} paise, received {amount_paise} paise."
                )

            # ── Currency guard ────────────────────────────────────────────────
            if currency_received and currency_received != payment.currency:
                _logger.warning(
                    "Razorpay webhook rejected: currency mismatch",
                    extra={
                        "reason":   "currency_mismatch",
                        "expected": payment.currency,
                        "received": currency_received,
                        "order_id": order_id,
                    },
                )
                PaymentEvent.objects.create(
                    payment=payment,
                    event_type="AMOUNT_MISMATCH",
                    payload={
                        "reason":            "currency_mismatch",
                        "expected_currency": payment.currency,
                        "received_currency": currency_received,
                        "order_id":          order_id,
                    },
                )
                PaymentService.mark_payment_failed(
                    payment,
                    reason=f"currency_mismatch: expected {payment.currency}, received {currency_received}",
                )
                raise PaymentError(
                    f"Currency mismatch: expected {payment.currency}, received {currency_received}."
                )

            # All validations passed — transition to SUCCESS
            PaymentService.mark_payment_success(
                payment,
                gateway_payment_id=payment_id,
                gateway_signature=payload.get("razorpay_signature", ""),
            )

        elif event == "payment.failed":
            PaymentService.mark_payment_failed(payment, reason=event)

        return payment

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def get_payments_for_reference(reference_type: str, reference_id):
        return Payment.base_objects.filter(
            reference_type=reference_type,
            reference_id=reference_id,
            is_deleted=False,
        ).order_by("-created_at")

    @staticmethod
    def get_active_payment_for_reference(reference_type: str, reference_id):
        """Return the most recent non-failed, non-cancelled payment for a reference."""
        return (
            Payment.base_objects
            .filter(
                reference_type=reference_type,
                reference_id=reference_id,
                is_deleted=False,
            )
            .exclude(status__in=[PaymentStatus.FAILED, PaymentStatus.CANCELLED])
            .order_by("-created_at")
            .first()
        )
