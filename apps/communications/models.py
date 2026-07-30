from django.db import models
from apps.core.models import TenantAwareModel, BaseModel
from apps.payments.utils.encryption import EncryptedCharField


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


class MessagingProvider(models.TextChoices):
    MSG91           = "msg91",           "MSG91 (SMS, India)"
    WHATSAPP_CLOUD  = "whatsapp_cloud",  "Meta WhatsApp Cloud API"


class TenantMessagingConfig(BaseModel):
    """Per-tenant SMS / WhatsApp credentials.

    Why this exists
    ---------------
    Credentials for these two channels are legally the TENANT's, not ANJASI's.
    Under TRAI DLT the Principal Entity is whoever's content it is, and the
    sender header is registered against their PAN/GST; a WhatsApp Business
    Account binds to the studio's own phone number and verified name.

    Until this model existed both were read from global environment variables,
    which is fine for a single tenant and actively wrong for a second: their
    messages would go out under the first tenant's DLT header and WhatsApp
    number. That is a compliance violation, not merely a bug.

    Deliberately mirrors payments.TenantPaymentConfig — same BaseModel + explicit
    tenant FK (NOT TenantAwareModel, because adapters run in commands and cron
    where there is no tenant context and the filtering manager would return
    nothing), same encrypted-secret approach, same is_active flag, same
    unique_together, and the same env-var fallback for development.

    Field reuse across providers
    ----------------------------
    The two providers need the same SHAPE of credential, so the columns are
    generic rather than provider-prefixed:

        field          MSG91                   WhatsApp Cloud
        ------------   ---------------------   -----------------------
        api_key        auth key (secret)       access token (secret)
        sender_id      sender / header ID      phone number ID
        template_id    DLT template ID         approved template name
        template_lang  unused                  template language code
    """

    tenant = models.ForeignKey(
        "core.Tenant",
        on_delete=models.CASCADE,
        related_name="messaging_configs",
    )
    provider = models.CharField(max_length=30, choices=MessagingProvider.choices)

    # Secret. Encrypted at rest; never expose in API responses or logs.
    api_key = EncryptedCharField(
        blank=True,
        help_text="MSG91 auth key, or Meta WhatsApp access token.",
    )
    sender_id = models.CharField(
        max_length=100, blank=True,
        help_text="MSG91 sender/header ID, or Meta WhatsApp phone number ID.",
    )
    template_id = models.CharField(
        max_length=200, blank=True,
        help_text="MSG91 DLT template ID, or the approved Meta template name.",
    )
    template_lang = models.CharField(
        max_length=20, blank=True,
        help_text="Meta template language code (e.g. en, en_US). Unused for MSG91.",
    )

    is_active = models.BooleanField(
        default=False,
        help_text="Off until the tenant's own registration/verification completes.",
    )

    class Meta:
        db_table = "tenant_messaging_configs"
        unique_together = [["tenant", "provider"]]

    def __str__(self):
        state = "active" if self.is_active else "inactive"
        return f"{self.tenant} — {self.provider} [{state}]"
