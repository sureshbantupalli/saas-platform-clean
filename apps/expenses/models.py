from django.conf import settings
from django.db import models

from apps.core.models import TenantAwareModel


class ExpenseCategory(TenantAwareModel):
    """Tenant-defined expense categories. No hardcoding — tenant creates their own."""
    name = models.CharField(max_length=100)

    class Meta:
        unique_together = [("tenant", "name")]
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.tenant.name})"


class Expense(TenantAwareModel):
    """
    Records money going out of the business.
    vendor_name / vendor_person captures who was paid — required for GST audit trails.
    """
    category = models.ForeignKey(
        ExpenseCategory,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="expenses",
    )
    vertical = models.ForeignKey(
        "verticals.BusinessVertical",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="expenses",
    )

    amount  = models.DecimalField(max_digits=10, decimal_places=2)
    date    = models.DateField()
    notes   = models.TextField(blank=True)

    # Vendor dimension — one of these should be set for auditability
    vendor_name   = models.CharField(max_length=200, blank=True)
    vendor_person = models.ForeignKey(
        "members.Member",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="vendor_expenses",
    )

    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="recorded_expenses",
    )

    # GST fields — manual; user fills these in
    gst_applicable = models.BooleanField(default=False)
    gst_rate       = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    gst_amount     = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    receipt_ref = models.CharField(max_length=100, blank=True, help_text="Vendor invoice / receipt number")

    class Meta:
        ordering = ["-date"]
        indexes = [
            models.Index(fields=["tenant", "date"]),
            models.Index(fields=["tenant", "category"]),
        ]

    def __str__(self):
        vendor = self.vendor_name or (str(self.vendor_person) if self.vendor_person_id else "—")
        return f"₹{self.amount} to {vendor} on {self.date}"
