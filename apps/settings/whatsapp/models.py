from django.db import models


class Tone(models.TextChoices):
    FORMAL   = 'FORMAL',   'Formal (Dear {name})'
    FRIENDLY = 'FRIENDLY', 'Friendly (Hi {name}!)'
    MINIMAL  = 'MINIMAL',  'Minimal (no greeting)'


class CTAStyle(models.TextChoices):
    PAY_NOW = 'PAY_NOW', 'Pay Now (link)'
    CONFIRM = 'CONFIRM', 'Confirm (Reply YES)'
    CONTACT = 'CONTACT', 'Contact (phone number)'
    NONE    = 'NONE',    'None'


class TenantWhatsAppSettings(models.Model):
    """Per-tenant WhatsApp message branding configuration."""
    tenant = models.OneToOneField(
        'core.Tenant',
        on_delete=models.CASCADE,
        related_name='whatsapp_settings',
    )
    tone               = models.CharField(max_length=10, choices=Tone.choices, default=Tone.FRIENDLY)
    signature_enabled  = models.BooleanField(default=True)
    cta_style          = models.CharField(max_length=10, choices=CTAStyle.choices, default=CTAStyle.NONE)
    # Maps event_name → custom template string (overrides MessageTemplate.content for WA channel)
    template_overrides = models.JSONField(default=dict, blank=True)
    updated_at         = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'settings_whatsapp'

    def __str__(self):
        return f'WhatsApp settings for {self.tenant_id}'
