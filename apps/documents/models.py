from django.conf import settings
from django.db import models, transaction

from apps.core.models import TenantAwareModel


class DocumentType(models.TextChoices):
    INVOICE    = "invoice",    "Invoice"
    QUOTATION  = "quotation",  "Quotation"
    RECEIPT    = "receipt",    "Receipt"


class DocumentStatus(models.TextChoices):
    DRAFT     = "draft",     "Draft"
    ISSUED    = "issued",    "Issued"
    PAID      = "paid",      "Paid"
    EXPIRED   = "expired",   "Expired"
    CANCELLED = "cancelled", "Cancelled"


# ── Sequence generator ────────────────────────────────────────────────────────

_TYPE_PREFIX = {
    DocumentType.INVOICE:   "INV",
    DocumentType.QUOTATION: "QUO",
    DocumentType.RECEIPT:   "RCT",
}


class DocumentSequence(models.Model):
    """
    Atomic counter per (tenant, document_type, year).
    Always accessed via SELECT FOR UPDATE to avoid gaps under concurrent writes.
    """
    tenant        = models.ForeignKey("core.Tenant", on_delete=models.CASCADE)
    document_type = models.CharField(max_length=20, choices=DocumentType.choices)
    year          = models.IntegerField()
    last_number   = models.IntegerField(default=0)

    class Meta:
        unique_together = [("tenant", "document_type", "year")]

    @classmethod
    def next_number(cls, tenant, document_type: str) -> str:
        """Return e.g. 'INV-2026-0042'. Atomic under concurrent writes."""
        from django.utils import timezone
        year = timezone.now().year
        with transaction.atomic():
            seq, _ = cls.objects.select_for_update().get_or_create(
                tenant=tenant,
                document_type=document_type,
                year=year,
                defaults={"last_number": 0},
            )
            seq.last_number += 1
            seq.save(update_fields=["last_number"])
        prefix = _TYPE_PREFIX.get(document_type, "DOC")
        return f"{prefix}-{year}-{seq.last_number:04d}"


# ── Core document ─────────────────────────────────────────────────────────────

class Document(TenantAwareModel):
    """
    Unified invoice / quotation / receipt.
    Vertical-agnostic: works for yoga classes, therapy sessions, or any future service.

    Conversion rules (enforced in service layer, not here):
      quotation → invoice: new Document(type=invoice) copying line items
      invoice paid  → receipt: new Document(type=receipt) + PaymentDocumentLink
    """
    person   = models.ForeignKey(
        "members.Member",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="documents",
    )
    vertical = models.ForeignKey(
        "verticals.BusinessVertical",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="documents",
    )

    document_type   = models.CharField(max_length=20, choices=DocumentType.choices)
    reference_type  = models.CharField(max_length=50, blank=True)
    reference_id    = models.UUIDField(null=True, blank=True)
    document_number = models.CharField(max_length=30)   # set by service before save

    issued_date = models.DateField()
    valid_until = models.DateField(null=True, blank=True)  # quotations only

    status = models.CharField(
        max_length=20,
        choices=DocumentStatus.choices,
        default=DocumentStatus.DRAFT,
    )

    subtotal        = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    gst_applicable  = models.BooleanField(default=False)
    gst_rate        = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    gst_amount      = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    notes        = models.TextField(blank=True)

    class Meta:
        unique_together = [("tenant", "document_type", "document_number")]
        ordering = ["-issued_date", "-created_at"]
        indexes = [
            models.Index(fields=["tenant", "document_type", "status"]),
            models.Index(fields=["tenant", "person"]),
        ]

    def __str__(self):
        return f"{self.document_number} [{self.status}]"


class DocumentLineItem(models.Model):
    """
    One line on a document. Optionally linked to a Service for catalog consistency.
    """
    document    = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="line_items")
    service     = models.ForeignKey(
        "catalog.Service",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="line_items",
    )
    item_name   = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    quantity    = models.DecimalField(max_digits=8,  decimal_places=2, default=1)
    unit_price  = models.DecimalField(max_digits=10, decimal_places=2)
    total       = models.DecimalField(max_digits=10, decimal_places=2)  # qty × unit_price

    def save(self, *args, **kwargs):
        self.total = self.quantity * self.unit_price
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.item_name} × {self.quantity} = {self.total}"


# ── Payment linkage ───────────────────────────────────────────────────────────

class PaymentDocumentLink(models.Model):
    """
    Explicit junction table for payment ↔ document linkage.
    Supports partial payments, split payments, and future refund tracking.
    """
    payment        = models.ForeignKey(
        "payments.Payment",
        on_delete=models.CASCADE,
        related_name="document_links",
    )
    document       = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="payment_links",
    )
    amount_applied = models.DecimalField(max_digits=10, decimal_places=2)
    created_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("payment", "document")]

    def __str__(self):
        return f"{self.payment_id} → {self.document_id} (₹{self.amount_applied})"
