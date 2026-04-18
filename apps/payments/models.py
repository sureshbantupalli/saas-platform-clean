import uuid
from django.conf import settings
from django.db import models
from apps.core.models import TenantAwareModel, BaseModel
from apps.payments.utils.encryption import EncryptedCharField


# ── Status / choice constants ─────────────────────────────────────────────────

class PaymentStatus(models.TextChoices):
    CREATED   = "CREATED",   "Created"
    PENDING   = "PENDING",   "Pending"
    SUCCESS   = "SUCCESS",   "Success"
    FAILED    = "FAILED",    "Failed"
    CANCELLED = "CANCELLED", "Cancelled"
    REFUNDED  = "REFUNDED",  "Refunded"


class PaymentPurpose(models.TextChoices):
    MEMBERSHIP = "membership", "Membership"
    BOOKING    = "booking",    "Booking"
    OTHER      = "other",      "Other"


class PaymentGateway(models.TextChoices):
    OFFLINE  = "offline",  "Offline / Manual"
    RAZORPAY = "razorpay", "Razorpay"
    STRIPE   = "stripe",   "Stripe"


class PaymentMethod(models.TextChoices):
    CASH          = "cash",          "Cash"
    UPI           = "upi",           "UPI"
    BANK_TRANSFER = "bank_transfer", "Bank Transfer"
    CARD          = "card",          "Card"
    ONLINE        = "online",        "Online"


# ── Payment ───────────────────────────────────────────────────────────────────

class Payment(TenantAwareModel):
    """
    Gateway-agnostic payment record.
    Linked to any entity via (reference_type, reference_id) — never via FK.
    """
    amount   = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default="INR")

    status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.CREATED,
        db_index=True,
    )

    purpose        = models.CharField(max_length=20, choices=PaymentPurpose.choices, default=PaymentPurpose.MEMBERSHIP)
    reference_type = models.CharField(max_length=50, blank=True, help_text="e.g. 'membership', 'booking'")
    reference_id   = models.UUIDField(null=True, blank=True, db_index=True)

    # Gateway fields (unused for offline payments)
    gateway            = models.CharField(max_length=20, choices=PaymentGateway.choices, default=PaymentGateway.OFFLINE)
    gateway_order_id   = models.CharField(max_length=200, blank=True)
    gateway_payment_id = models.CharField(max_length=200, blank=True)
    gateway_signature  = models.CharField(max_length=500, blank=True)

    # Manual / offline payment details
    payment_method    = models.CharField(max_length=20, choices=PaymentMethod.choices, null=True, blank=True)
    payment_reference = models.CharField(max_length=200, blank=True, help_text="UPI txn ID, cheque no., etc.")
    notes             = models.TextField(blank=True)

    paid_at    = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="created_payments",
    )

    class Meta:
        db_table = "payments"
        ordering = ["-created_at"]
        indexes  = [models.Index(fields=["reference_type", "reference_id"])]

    def __str__(self):
        return f"Payment {self.id} — {self.amount} {self.currency} [{self.status}]"


# ── PaymentEvent ──────────────────────────────────────────────────────────────

class PaymentEvent(BaseModel):
    """Append-only audit log for every state transition."""

    payment    = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name="events")
    event_type = models.CharField(max_length=50)
    payload    = models.JSONField(default=dict)

    class Meta:
        db_table = "payment_events"
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.event_type} @ {self.created_at:%Y-%m-%d %H:%M}"


# ── TenantPaymentConfig ───────────────────────────────────────────────────────

class TenantPaymentConfig(BaseModel):
    """
    Per-tenant payment gateway configuration.
    Secrets (key_secret, webhook_secret) are encrypted at rest via EncryptedCharField.
    Never expose key_secret or webhook_secret in API responses.
    """
    tenant = models.ForeignKey(
        "core.Tenant",
        on_delete=models.CASCADE,
        related_name="payment_configs",
    )
    provider   = models.CharField(max_length=30, default="razorpay")
    key_id     = models.CharField(max_length=200, blank=True)
    key_secret     = EncryptedCharField(blank=True)
    webhook_secret = EncryptedCharField(blank=True)
    is_active  = models.BooleanField(default=False)

    class Meta:
        db_table       = "tenant_payment_configs"
        unique_together = [["tenant", "provider"]]

    def __str__(self):
        status = "active" if self.is_active else "inactive"
        return f"{self.tenant} — {self.provider} [{status}]"
