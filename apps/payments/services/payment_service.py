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
        payment_id        = entity.get("id", "")   # Razorpay gateway payment id (pay_Xxx)
        amount_paise      = entity.get("amount")   # None if key absent — NOT defaulted to 0
        currency_received = entity.get("currency", "")

        # ══════════════════════════════════════════════════════════════════════
        # PRE-LOOKUP GUARDS — no DB reads or writes.
        # Logging here records only what the caller sent; no financial action.
        # ══════════════════════════════════════════════════════════════════════

        # ── Step 1: gateway_payment_id (entity.id) required ──────────────────
        # Without it we cannot store the result or detect conflicts later.
        if not payment_id:
            _logger.warning(
                "Razorpay webhook rejected: missing payment_id",
                extra={"reason": "missing_payment_id", "gateway": "razorpay", "order_id": order_id},
            )
            raise PaymentError("Webhook rejected: missing payment_id.")

        # ══════════════════════════════════════════════════════════════════════
        # READ-ONLY DB LOOKUPS — still no writes
        # ══════════════════════════════════════════════════════════════════════

        # ── Step 2: locate payment by gateway_order_id ────────────────────────
        payment = Payment.base_objects.filter(
            gateway_order_id=order_id, is_deleted=False
        ).first()
        if not payment:
            _logger.warning(
                "Razorpay webhook rejected: payment not found",
                extra={"reason": "payment_not_found", "gateway": "razorpay", "order_id": order_id},
            )
            raise PaymentError(f"No payment found for order_id={order_id}")

        # ── Step 3: order_id required for Razorpay gateway payments ──────────
        # Offline payments legitimately have an empty gateway_order_id; Razorpay
        # payments must always carry one. Validated post-lookup so we can inspect
        # the payment's gateway field rather than rejecting blindly.
        if payment.gateway == PaymentGateway.RAZORPAY and not order_id:
            _logger.warning(
                "Razorpay webhook rejected: missing order_id for razorpay payment",
                extra={
                    "reason":     "missing_order_id",
                    "gateway":    "razorpay",
                    "payment_id": str(payment.id),
                    "tenant_id":  str(payment.tenant_id),
                    "event":      event,
                },
            )
            raise PaymentError("Webhook rejected: razorpay payment requires order_id.")

        # ── Step 4: load tenant webhook secret (READ only) ───────────────────
        from apps.payments.services.config_service import get_active_payment_config, PaymentConfigError
        try:
            config         = get_active_payment_config(payment.tenant, "razorpay")
            webhook_secret = config.webhook_secret
        except PaymentConfigError as exc:
            raise PaymentError(str(exc))

        # ══════════════════════════════════════════════════════════════════════
        # SIGNATURE GATE — the sole entry point to DB writes.
        # Every path above raises without touching the DB.
        # ══════════════════════════════════════════════════════════════════════

        # ── Step 5: verify HMAC-SHA256 signature ─────────────────────────────
        expected_sig = hmac.HMAC(
            webhook_secret.encode(), raw_body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected_sig, signature):
            _logger.warning(
                "Razorpay webhook rejected: invalid signature",
                extra={
                    "reason":     "invalid_signature",
                    "payment_id": str(payment.id),
                    "gateway":    "razorpay",
                    "order_id":   order_id,
                    "tenant_id":  str(payment.tenant_id),
                    "event":      event,
                },
            )
            raise PaymentError("Invalid Razorpay webhook signature.")

        # ══════════════════════════════════════════════════════════════════════
        # DB WRITES BELOW — signature verified; payment identity confirmed
        # ══════════════════════════════════════════════════════════════════════

        # ── Step 6: idempotency — short-circuit for already-SUCCESS payments ──
        # Must happen AFTER signature verification so an unauthenticated caller
        # cannot probe payment status via forged webhooks.
        if payment.status == PaymentStatus.SUCCESS:
            # Detect conflicting gateway_payment_id on a completed payment
            # (same order_id, different Razorpay pay_Xxx → possible replay
            # with a fraudulent transaction). Log but still return 200 so
            # Razorpay stops retrying.
            if payment.gateway_payment_id and payment.gateway_payment_id != payment_id:
                _logger.error(
                    "Razorpay webhook: gateway_payment_id conflict on already-SUCCESS payment",
                    extra={
                        "reason":     "duplicate_or_conflict",
                        "payment_id": str(payment.id),
                        "expected":   payment.gateway_payment_id,
                        "received":   payment_id,
                        "gateway":    "razorpay",
                        "order_id":   order_id,
                        "tenant_id":  str(payment.tenant_id),
                        "event":      event,
                    },
                )
            PaymentEvent.objects.create(
                payment=payment,
                event_type="DUPLICATE_SKIP",
                payload={"reason": "already SUCCESS", "event": event},
            )
            return payment

        # ── Step 7: defense-in-depth order_id validation (gateway payments only)
        # Scoped to gateway payments — offline payments legitimately have an
        # empty gateway_order_id and should never reach this handler. The
        # filter in Step 3 already guarantees equality; this explicit check
        # is a contract assertion that survives future query refactors.
        if payment.gateway == PaymentGateway.RAZORPAY and payment.gateway_order_id != order_id:
            _logger.error(
                "Razorpay webhook rejected: order_id mismatch",
                extra={
                    "reason":     "order_mismatch",
                    "payment_id": str(payment.id),
                    "expected":   payment.gateway_order_id,
                    "received":   order_id,
                    "gateway":    "razorpay",
                    "order_id":   order_id,
                    "tenant_id":  str(payment.tenant_id),
                    "event":      event,
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

        # ── Step 8: log the verified, non-duplicate incoming webhook ──────────
        PaymentEvent.objects.create(
            payment=payment,
            event_type="WEBHOOK",
            payload={"event": event, "razorpay_payment_id": payment_id},
        )

        if event == "payment.captured":
            expected_paise = int(payment.amount * 100)

            # ── gateway_payment_id conflict (PENDING payment) ─────────────────
            # For PENDING payments gateway_payment_id is normally "".
            # If already set to a different value, a previous partial processing
            # wrote it — this is a conflict that must be rejected.
            if payment.gateway_payment_id and payment.gateway_payment_id != payment_id:
                _logger.error(
                    "Razorpay webhook rejected: gateway_payment_id conflict on PENDING payment",
                    extra={
                        "reason":               "payment_id_conflict",
                        "payment_id":           str(payment.id),
                        "existing_payment_id":  payment.gateway_payment_id,
                        "incoming_payment_id":  payment_id,
                        "gateway":              "razorpay",
                        "order_id":             order_id,
                        "tenant_id":            str(payment.tenant_id),
                        "event":                event,
                    },
                )
                PaymentEvent.objects.create(
                    payment=payment,
                    event_type="PAYMENT_ID_CONFLICT",
                    payload={
                        "reason":   "duplicate_or_conflict",
                        "stored":   payment.gateway_payment_id,
                        "received": payment_id,
                        "order_id": order_id,
                    },
                )
                raise PaymentError(
                    f"Payment ID conflict: stored {payment.gateway_payment_id!r}, "
                    f"received {payment_id!r}."
                )

            # ── Amount guard ──────────────────────────────────────────────────
            # Strict equality: None or 0 must not bypass this check.
            if amount_paise is None or amount_paise != expected_paise:
                _logger.warning(
                    "Razorpay webhook rejected: amount mismatch",
                    extra={
                        "reason":     "amount_mismatch",
                        "payment_id": str(payment.id),
                        "expected":   expected_paise,
                        "received":   amount_paise,
                        "gateway":    "razorpay",
                        "order_id":   order_id,
                        "tenant_id":  str(payment.tenant_id),
                        "event":      event,
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
                        "reason":     "currency_mismatch",
                        "payment_id": str(payment.id),
                        "expected":   payment.currency,
                        "received":   currency_received,
                        "gateway":    "razorpay",
                        "order_id":   order_id,
                        "tenant_id":  str(payment.tenant_id),
                        "event":      event,
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
