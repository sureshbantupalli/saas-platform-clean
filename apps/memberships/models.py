from datetime import timedelta
from dateutil.relativedelta import relativedelta
import uuid

from django.db import models
from django.conf import settings
from django.db.models import Q, Sum
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.core.models import TenantAwareModel, Branch


# =========================================================
# Membership Model
# =========================================================

class Membership(TenantAwareModel):

    STATUS_CHOICES = [
        ("active", "Active"),
        ("paused", "Paused"),
        ("expired", "Expired"),
        ("cancelled", "Cancelled"),
    ]

    DISCOUNT_TYPE_CHOICES = [
        ("NONE", "No Discount"),
        ("FIXED", "Fixed Amount"),
        ("PERCENTAGE", "Percentage"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    member = models.ForeignKey(
        "members.Member",
        on_delete=models.CASCADE,
        related_name="memberships"
    )

    branch = models.ForeignKey(
        "core.Branch",
        on_delete=models.CASCADE,
        related_name="memberships"
    )

    plan = models.ForeignKey(
        "memberships.MembershipPlan",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="memberships"
    )

    plan_name = models.CharField(max_length=120)

    start_date = models.DateField()
    end_date = models.DateField()

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="active"
    )

    # ------------------------------
    # Pricing
    # ------------------------------

    base_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True
    )

    discount_type = models.CharField(
        max_length=20,
        choices=DISCOUNT_TYPE_CHOICES,
        default="NONE"
    )

    discount_value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    fee_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    auto_renew = models.BooleanField(default=False)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # =====================================================
    # Meta
    # =====================================================

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["member", "branch"],
                condition=Q(status="active"),
                name="unique_active_membership_per_branch"
            )
        ]

    # =====================================================
    # Validation
    # =====================================================

    def clean(self):
        from django.core.exceptions import ValidationError

        # Ensure required relationships exist before using them
        if not self.member_id or not self.branch_id:
            return

        # Ensure branch belongs to member
        if not self.member.branches.filter(id=self.branch_id).exists():
            raise ValidationError(
                "Selected branch is not assigned to this member."
            )

    # =====================================================
    # Save Override
    # =====================================================

    def save(self, *args, **kwargs):

        # Tenant auto-assignment
        if not self.tenant_id:
            from apps.core.tenant_context import get_current_tenant
            current_tenant = get_current_tenant()
            if current_tenant:
                self.tenant = current_tenant

        # ------------------------------
        # Pricing Logic
        # ------------------------------

        if self.discount_type == "NONE":
            self.discount_value = 0

        if self.discount_value in [None, ""]:
            self.discount_value = 0

        if self.plan:
            self.base_amount = self.plan.price

            if self.discount_type == "NONE":
                self.fee_amount = self.base_amount

            elif self.discount_type == "FIXED":
                self.fee_amount = max(
                    self.base_amount - self.discount_value,
                    0
                )

            elif self.discount_type == "PERCENTAGE":
                discount_amount = (
                    self.base_amount * self.discount_value / 100
                )
                self.fee_amount = max(
                    self.base_amount - discount_amount,
                    0
                )

        # ------------------------------
        # End Date Calculation
        # ------------------------------

        if self.plan and self.start_date:

            cycle = self.plan.billing_cycle_type
            interval = self.plan.billing_interval

            if cycle == "DAILY":
                self.end_date = self.start_date + timedelta(days=interval)

            elif cycle == "WEEKLY":
                self.end_date = self.start_date + timedelta(weeks=interval)

            elif cycle == "MONTHLY":
                self.end_date = self.start_date + relativedelta(months=interval)

            elif cycle == "YEARLY":
                self.end_date = self.start_date + relativedelta(years=interval)

        # Validation
        self.full_clean()

        # Lifecycle sync
        self.sync_status_with_lifecycle()

        super().save(*args, **kwargs)

    # =====================================================
    # Lifecycle Intelligence
    # =====================================================

    @property
    def final_end_date(self):

        if not self.end_date:
            return None

        extension_days = self.adjustments.filter(
            adjustment_type="EXTENSION"
        ).aggregate(total=Sum("days"))["total"] or 0

        freeze_days = self.adjustments.filter(
            adjustment_type="FREEZE"
        ).aggregate(total=Sum("days"))["total"] or 0

        correction_days = self.adjustments.filter(
            adjustment_type="CORRECTION"
        ).aggregate(total=Sum("days"))["total"] or 0

        return self.end_date + timedelta(
            days=extension_days + freeze_days + correction_days
        )

    @property
    def effective_expiry_date(self):
        if not self.final_end_date:
            return None

        grace = self.tenant.grace_days if self.tenant else 0
        return self.final_end_date + timedelta(days=grace)

    @property
    def lifecycle_status(self):
        today = timezone.now().date()

        if not self.final_end_date:
            return "UNKNOWN"

        if today <= self.final_end_date:
            return "ACTIVE"

        if today <= self.effective_expiry_date:
            return "GRACE"

        return "EXPIRED"

    # =====================================================
    # Status Sync
    # =====================================================

    def sync_status_with_lifecycle(self):
        """
        Status is lifecycle-driven,
        except when manually paused or cancelled.
        """

        if self.status in ["paused", "cancelled"]:
            return

        if self.lifecycle_status == "EXPIRED":
            self.status = "expired"
        else:
            self.status = "active"

    def __str__(self):
        return f"{self.member} - {self.branch} ({self.status})"


# =========================================================
# Membership Adjustment Model
# =========================================================

class MembershipAdjustment(TenantAwareModel):

    ADJUSTMENT_TYPE_CHOICES = [
        ("EXTENSION", "Extension"),
        ("FREEZE", "Freeze"),
        ("CORRECTION", "Correction"),
    ]

    membership = models.ForeignKey(
        Membership,
        on_delete=models.CASCADE,
        related_name="adjustments"
    )

    adjustment_type = models.CharField(
        max_length=20,
        choices=ADJUSTMENT_TYPE_CHOICES
    )

    days = models.IntegerField()
    remarks = models.TextField()

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.adjustment_type} ({self.days} days)"


# =========================================================
# Membership Plan Model
# =========================================================

class MembershipPlan(TenantAwareModel):

    BILLING_CYCLE_CHOICES = [
        ("DAILY", "Daily"),
        ("WEEKLY", "Weekly"),
        ("MONTHLY", "Monthly"),
        ("YEARLY", "Yearly"),
        ("CUSTOM", "Custom"),
    ]

    DURATION_TYPE_CHOICES = [
        ("FIXED_PERIOD", "Fixed Period"),
        ("OPEN_ENDED", "Open Ended"),
        ("CUSTOM_DATE_RANGE", "Custom Date Range"),
    ]

    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name="membership_plans"
    )

    name = models.CharField(max_length=150)
    price = models.DecimalField(max_digits=10, decimal_places=2)

    billing_cycle_type = models.CharField(
        max_length=20,
        choices=BILLING_CYCLE_CHOICES
    )

    billing_interval = models.PositiveIntegerField(default=1)

    duration_type = models.CharField(
        max_length=30,
        choices=DURATION_TYPE_CHOICES
    )

    duration_value = models.PositiveIntegerField(
        null=True,
        blank=True
    )

    allow_custom_dates = models.BooleanField(default=False)
    auto_renew_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("tenant", "branch", "name")
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.branch.name})"