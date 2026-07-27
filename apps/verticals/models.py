from django.db import models
from django.utils.text import slugify

from apps.core.models import TenantAwareModel


class BusinessVertical(TenantAwareModel):
    """
    A configurable business line within a tenant.
    Created as data (not code) — tenants define their own verticals.
    Examples: "Yoga Training", "Therapy", "Personal Coaching".
    """
    name        = models.CharField(max_length=100)
    slug        = models.SlugField(max_length=100)
    description = models.TextField(blank=True)
    is_active   = models.BooleanField(default=True)

    class Meta:
        unique_together = [("tenant", "slug")]
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.tenant.name})"
