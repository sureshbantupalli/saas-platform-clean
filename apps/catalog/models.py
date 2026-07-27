from django.db import models

from apps.core.models import TenantAwareModel


class Service(TenantAwareModel):
    """
    A named, priced offering within a business vertical.
    DocumentLineItems and sessions can optionally reference a Service for
    consistent pricing and reporting ("what do we sell most?").

    Examples: "Monthly Yoga Class", "Back Pain Therapy", "Personal Training (60 min)".
    """
    vertical      = models.ForeignKey(
        "verticals.BusinessVertical",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="services",
    )
    name          = models.CharField(max_length=200)
    description   = models.TextField(blank=True)
    default_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    is_active     = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.tenant.name})"
