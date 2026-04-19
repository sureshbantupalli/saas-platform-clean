from django.db import models
from apps.core.models import TenantAwareModel


class Channel(models.TextChoices):
    SMS       = "SMS",       "SMS"
    WHATSAPP  = "WHATSAPP",  "WhatsApp"
    EMAIL     = "EMAIL",     "Email"


class MessageStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    SENT    = "SENT",    "Sent"
    FAILED  = "FAILED",  "Failed"
    SKIPPED = "SKIPPED", "Skipped"  # intentional suppression (e.g. deduplication)


class Priority(models.IntegerChoices):
    HIGH   = 1, "High"
    MEDIUM = 2, "Medium"
    LOW    = 3, "Low"


class MessageTemplate(TenantAwareModel):
    name    = models.CharField(max_length=200)
    channel = models.CharField(max_length=20, choices=Channel.choices)
    subject = models.CharField(max_length=500, blank=True, help_text="Email subject (leave blank for SMS/WhatsApp).")
    content = models.TextField(help_text="Use {{variable_name}} placeholders, e.g. {{member_name}}, {{amount}}.")
    variables = models.JSONField(
        default=dict,
        blank=True,
        help_text="Optional documentation of expected placeholder variables.",
    )
    priority  = models.IntegerField(choices=Priority.choices, default=Priority.MEDIUM)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "communication_templates"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} [{self.channel}]"


class TriggerRule(TenantAwareModel):
    event_name = models.CharField(
        max_length=100,
        help_text='System event name, e.g. "payment_success", "booking_confirmed".',
    )
    template = models.ForeignKey(
        MessageTemplate,
        on_delete=models.PROTECT,
        related_name="trigger_rules",
    )
    conditions = models.JSONField(
        default=dict,
        blank=True,
        help_text='Optional JSON conditions. Example: {"amount": {">": 1000}}',
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "communication_trigger_rules"
        ordering = ["event_name"]

    def __str__(self):
        return f"{self.event_name} → {self.template.name}"


class CommunicationLog(TenantAwareModel):
    channel         = models.CharField(max_length=20, choices=Channel.choices)
    event_type      = models.CharField(max_length=100, blank=True, help_text="System event that triggered this message.")
    recipient       = models.CharField(max_length=500)
    subject         = models.CharField(max_length=500, blank=True)
    message         = models.TextField()
    status          = models.CharField(max_length=20, choices=MessageStatus.choices, default=MessageStatus.PENDING)
    reference_type  = models.CharField(max_length=100, blank=True)
    reference_id    = models.CharField(max_length=100, blank=True)
    error_message   = models.TextField(blank=True)
    retry_count     = models.PositiveSmallIntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    next_attempt_at = models.DateTimeField(null=True, blank=True, db_index=True)
    priority        = models.IntegerField(choices=Priority.choices, default=Priority.MEDIUM)
    dedupe_key      = models.CharField(max_length=64, blank=True, db_index=True)

    class Meta:
        db_table = "communication_logs"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.channel} → {self.recipient} [{self.status}]"

    @property
    def can_retry(self) -> bool:
        from apps.communications.services.retry_service import MAX_RETRIES
        return self.status == MessageStatus.FAILED and self.retry_count < MAX_RETRIES
