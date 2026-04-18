from django.db import models, transaction
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import timedelta


class LeadStage(models.Model):

    STAGE_TYPE_CHOICES = [
        ("NEW", "New"),
        ("CONTACTED", "Contacted"),
        ("DEMO", "Demo"),
        ("CONVERTED", "Converted"),
        ("LOST", "Lost"),
        ("CUSTOM", "Custom"),
    ]

    tenant = models.ForeignKey(
        "core.Tenant",
        on_delete=models.CASCADE,
        related_name="lead_stages"
    )

    name = models.CharField(max_length=100)

    order = models.PositiveIntegerField(default=0)

    color = models.CharField(max_length=20, blank=True)

    # NEW FIELD (Safe addition)
    stage_type = models.CharField(
        max_length=20,
        choices=STAGE_TYPE_CHOICES,
        default="CUSTOM"
    )

    # NEW FIELD (Controls Kanban visibility)
    show_in_pipeline = models.BooleanField(
        default=True,
        help_text="Whether this stage should appear in the Kanban pipeline"
    )

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

        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "phone"],
                name="unique_enquiry_phone_per_tenant"
            )
        ]

        indexes = [
            models.Index(fields=["phone"]),
            models.Index(fields=["created_at"]),
        ]

    # ==================================
    # LEAD TEMPERATURE ENGINE
    # ==================================

    @property
    def lead_temperature(self):

        today = timezone.now().date()

        if not self.next_followup_date:
            return "cold"

        if self.next_followup_date <= today:
            return "hot"

        if self.next_followup_date <= today + timedelta(days=2):
            return "warm"

        return "cold"

    @property
    def temperature_label(self):

        if self.lead_temperature == "hot":
            return "🔥 Hot"

        if self.lead_temperature == "warm":
            return "🟡 Warm"

        return "❄ Cold"

    @property
    def lead_age_days(self):

        today = timezone.now().date()

        return (today - self.created_at.date()).days

    @property
    def lead_priority(self):
        """
        Calculates priority score for the lead based on
        follow-up urgency and lead aging.
        """

        score = 0

        # Follow-up urgency
        if self.next_followup_date:
            today = timezone.now().date()

            if self.next_followup_date < today:
                score += 5  # overdue follow-up
            elif self.next_followup_date == today:
                score += 3  # follow-up today

        # Lead aging
        if hasattr(self, "lead_age_days"):
            if self.lead_age_days >= 5:
                score += 3
            elif self.lead_age_days >= 3:
                score += 1

        return score

    # ==================================
    # VALIDATION
    # ==================================

    def clean(self):

        if self.current_stage and self.current_stage.is_loss_stage:
            if not self.lost_reason:
                raise ValidationError(
                    {"lost_reason": "Lost reason is required when stage is marked as Lost."}
                )

        if self.current_stage and self.current_stage.is_conversion_stage:
            if not self.phone:
                raise ValidationError(
                    {"phone": "Phone number is required before converting to Member."}
                )

        if self.pk:
            original = Enquiry.objects.filter(pk=self.pk).first()

            if original and original.converted_member:
                if self.current_stage != original.current_stage:
                    raise ValidationError(
                        "Cannot change stage after enquiry has been converted."
                    )

    # ==================================
    # CONVERSION ENGINE
    # ==================================

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

            member.branches.add(self.branch)

            self.converted_member = member

            self.save(update_fields=["converted_member"])

            EnquiryActivity.objects.create(
                tenant=self.tenant,
                enquiry=self,
                action_type="CONVERTED",
                performed_by=user,
                notes=f"Converted to Member: {member.id}"
            )

        return member

    # ==================================
    # SAVE HOOK
    # ==================================

    def save(self, *args, **kwargs):

        self.full_clean()

        is_new = self.pk is None
        old_stage = None

        if not is_new:
            try:
                old_stage = Enquiry.objects.get(pk=self.pk).current_stage
            except Enquiry.DoesNotExist:
                pass

        super().save(*args, **kwargs)

        if is_new:

            EnquiryActivity.objects.create(
                tenant=self.tenant,
                enquiry=self,
                action_type="CREATED",
                performed_by=self.created_by
            )

            # Auto-schedule an initial call follow-up for the next day
            try:
                FollowUp.objects.create(
                    tenant=self.tenant,
                    enquiry=self,
                    followup_type=FollowUp.TYPE_CALL,
                    due_date=timezone.now().date() + timedelta(days=1),
                    status=FollowUp.STATUS_PENDING,
                    notes="Initial follow-up call",
                    reference_type="lead_created",
                    created_by=self.created_by,
                )
            except Exception:
                pass  # non-critical — enquiry is saved regardless

        elif old_stage != self.current_stage:

            acting_user = getattr(self, "_acting_user", None)

            EnquiryActivity.objects.create(
                tenant=self.tenant,
                enquiry=self,
                action_type="STAGE_CHANGED",
                performed_by=acting_user,
                old_value=old_stage.name if old_stage else None,
                new_value=self.current_stage.name if self.current_stage else None,
            )

    def __str__(self):
        return f"{self.full_name} - {self.phone}"


class EnquiryActivity(models.Model):

    ACTION_CHOICES = [
        ("CREATED",             "Created"),
        ("STAGE_CHANGED",       "Stage Changed"),
        ("ASSIGNED",            "Assigned"),
        ("NOTE_ADDED",          "Note Added"),
        ("CALL_LOGGED",         "Call Logged"),
        ("CONVERTED",           "Converted"),
        ("LOST",                "Lost"),
        ("FOLLOWUP_SCHEDULED",  "Follow-up Scheduled"),
        ("FOLLOWUP_DONE",       "Follow-up Completed"),
        ("FOLLOWUP_MISSED",     "Follow-up Missed"),
        ("MARKED_LOST",         "Marked as Lost"),
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
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.action_type} - {self.enquiry.full_name}"


# ============================================================
# FOLLOW-UP MODEL
# ============================================================

class FollowUp(models.Model):
    """
    Tracks individual follow-up tasks for enquiries and/or members.

    Enquiry follow-ups are created automatically on lead creation and
    by staff when scheduling calls. Member follow-ups are created when
    events like session_missed or payment_failed occur post-conversion.
    """

    TYPE_CALL    = "call"
    TYPE_MESSAGE = "message"
    TYPE_VISIT   = "visit"

    STATUS_PENDING = "pending"
    STATUS_DONE    = "done"
    STATUS_MISSED  = "missed"

    TYPE_CHOICES = [
        (TYPE_CALL,    "Call"),
        (TYPE_MESSAGE, "Message"),
        (TYPE_VISIT,   "Visit"),
    ]
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_DONE,    "Done"),
        (STATUS_MISSED,  "Missed"),
    ]

    tenant = models.ForeignKey(
        "core.Tenant",
        on_delete=models.CASCADE,
        related_name="followups",
    )

    # At least one of enquiry / member must be set
    enquiry = models.ForeignKey(
        Enquiry,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="followups",
    )
    member = models.ForeignKey(
        "members.Member",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="followups",
    )

    followup_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TYPE_CALL)
    due_date      = models.DateField()
    status        = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    notes         = models.TextField(blank=True)

    # Source event context
    reference_type = models.CharField(max_length=100, blank=True)
    reference_id   = models.CharField(max_length=100, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "crm_followups"
        ordering = ["due_date", "status"]

    @property
    def is_overdue(self):
        return self.status == self.STATUS_PENDING and self.due_date < timezone.now().date()

    @property
    def display_name(self):
        if self.enquiry:
            return self.enquiry.full_name
        if self.member:
            return f"{self.member.first_name} {self.member.last_name}"
        return "Unknown"

    @property
    def phone(self):
        if self.enquiry:
            return self.enquiry.phone
        if self.member:
            return self.member.phone
        return ""

    def __str__(self):
        return f"{self.get_followup_type_display()} — {self.display_name} [{self.due_date}]"