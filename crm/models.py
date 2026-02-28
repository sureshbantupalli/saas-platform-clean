from django.db import models, transaction
from django.conf import settings
from django.core.exceptions import ValidationError


class LeadStage(models.Model):
    tenant = models.ForeignKey(
        "core.Tenant",
        on_delete=models.CASCADE,
        related_name="lead_stages"
    )
    name = models.CharField(max_length=100)
    order = models.PositiveIntegerField(default=0)
    color = models.CharField(max_length=20, blank=True)

    is_conversion_stage = models.BooleanField(default=False)
    is_loss_stage = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order"]
        unique_together = ("tenant", "name")

    def clean(self):
        if self.is_conversion_stage and self.is_loss_stage:
            raise ValidationError(
                "Stage cannot be both conversion and loss stage."
            )

        if self.is_conversion_stage:
            existing = LeadStage.objects.filter(
                tenant=self.tenant,
                is_conversion_stage=True
            ).exclude(pk=self.pk)
            if existing.exists():
                raise ValidationError(
                    "Only one conversion stage allowed per tenant."
                )

        if self.is_loss_stage:
            existing = LeadStage.objects.filter(
                tenant=self.tenant,
                is_loss_stage=True
            ).exclude(pk=self.pk)
            if existing.exists():
                raise ValidationError(
                    "Only one loss stage allowed per tenant."
                )

    def __str__(self):
        return self.name


class EnquirySource(models.Model):
    tenant = models.ForeignKey(
        "core.Tenant",
        on_delete=models.CASCADE,
        related_name="enquiry_sources"
    )
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("tenant", "name")

    def __str__(self):
        return self.name


class EnquiryLostReason(models.Model):
    tenant = models.ForeignKey(
        "core.Tenant",
        on_delete=models.CASCADE,
        related_name="lost_reasons"
    )
    name = models.CharField(max_length=150)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("tenant", "name")

    def __str__(self):
        return self.name


class Enquiry(models.Model):

    tenant = models.ForeignKey(
        "core.Tenant",
        on_delete=models.CASCADE,
        related_name="enquiries"
    )

    branch = models.ForeignKey(
        "core.Branch",
        on_delete=models.CASCADE,
        related_name="enquiries"
    )

    full_name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True, null=True)

    interested_course = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)

    source = models.ForeignKey(
        EnquirySource,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    current_stage = models.ForeignKey(
        LeadStage,
        on_delete=models.PROTECT,
        related_name="enquiries",
        null=True,
        blank=True
    )

    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_enquiries"
    )

    lost_reason = models.ForeignKey(
        EnquiryLostReason,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    # 🔥 UPGRADED TO OneToOneField (true conversion integrity)
    converted_member = models.OneToOneField(
        "members.Member",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="source_enquiry"
    )

    next_followup_date = models.DateField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_enquiries"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Enquiry"
        verbose_name_plural = "Enquiries"
        indexes = [
            models.Index(fields=["phone"]),
            models.Index(fields=["created_at"]),
        ]

    # =============================
    # 🔒 VALIDATION LOGIC
    # =============================

    def clean(self):

        # Lost stage validation
        if self.current_stage and self.current_stage.is_loss_stage:
            if not self.lost_reason:
                raise ValidationError(
                    {"lost_reason": "Lost reason is required when stage is marked as Lost."}
                )

        # Conversion stage validation
        if self.current_stage and self.current_stage.is_conversion_stage:
            if not self.phone:
                raise ValidationError(
                    {"phone": "Phone number is required before converting to Member."}
                )

        # Prevent stage change after conversion
        if self.pk:
            original = Enquiry.objects.filter(pk=self.pk).first()
            if original and original.converted_member:
                if self.current_stage != original.current_stage:
                    raise ValidationError(
                        "Cannot change stage after enquiry has been converted."
                    )

    # =============================
    # 🔥 CONVERSION ENGINE (NEW)
    # =============================

    def convert_to_member(self, user):

        if self.converted_member:
            raise ValidationError("This enquiry is already converted.")

        if not self.current_stage or not self.current_stage.is_conversion_stage:
            raise ValidationError("Enquiry must be in a conversion stage.")

        from members.models import Member

        with transaction.atomic():

            member = Member.objects.create(
                tenant=self.tenant,
                created_by=user,
                first_name=self.full_name.split(" ")[0],
                last_name=" ".join(self.full_name.split(" ")[1:]) if len(self.full_name.split(" ")) > 1 else "",
                email=self.email,
                phone=self.phone,
            )

            # Assign branch (M2M)
            member.branches.add(self.branch)

            # Link back to enquiry
            self.converted_member = member
            self.save(update_fields=["converted_member"])

            # Log activity
            EnquiryActivity.objects.create(
                tenant=self.tenant,
                enquiry=self,
                action_type="CONVERTED",
                performed_by=user,
                notes=f"Converted to Member: {member.id}"
            )

        return member

    def save(self, *args, **kwargs):
        self.full_clean()
        is_new = self.pk is None
        super().save(*args, **kwargs)

        if is_new:
            EnquiryActivity.objects.create(
                tenant=self.tenant,
                enquiry=self,
                action_type="CREATED",
                performed_by=self.created_by
            )

    def __str__(self):
        return f"{self.full_name} - {self.phone}"


class EnquiryActivity(models.Model):

    ACTION_CHOICES = [
        ("CREATED", "Created"),
        ("STAGE_CHANGED", "Stage Changed"),
        ("ASSIGNED", "Assigned"),
        ("NOTE_ADDED", "Note Added"),
        ("CALL_LOGGED", "Call Logged"),
        ("CONVERTED", "Converted"),
        ("LOST", "Lost"),
    ]

    tenant = models.ForeignKey(
        "core.Tenant",
        on_delete=models.CASCADE,
        related_name="enquiry_activities"
    )

    enquiry = models.ForeignKey(
        Enquiry,
        on_delete=models.CASCADE,
        related_name="activities"
    )

    action_type = models.CharField(max_length=50, choices=ACTION_CHOICES)

    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True
    )

    old_value = models.TextField(blank=True, null=True)
    new_value = models.TextField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Enquiry Activity"
        verbose_name_plural = "Enquiry Activities"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.action_type} - {self.enquiry.full_name}"