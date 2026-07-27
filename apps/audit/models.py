from django.db import models
from django.conf import settings


class AuditModule(models.TextChoices):
    PAYMENTS    = 'payments'
    MEMBERSHIPS = 'memberships'
    SETTINGS    = 'settings'
    BRANDING    = 'branding'
    ROLES       = 'roles'
    VOCABULARY  = 'vocabulary'
    WHATSAPP    = 'whatsapp'
    CRM         = 'crm'
    ATTENDANCE  = 'attendance'
    BOOKINGS    = 'bookings'


class AuditAction(models.TextChoices):
    CREATE = 'create'
    UPDATE = 'update'
    DELETE = 'delete'


class AuditSource(models.TextChoices):
    USER   = 'user'    # initiated by a human via UI or API
    SYSTEM = 'system'  # initiated by automated flow (webhook, lifecycle, cron)


class SettingsAuditLog(models.Model):
    tenant = models.ForeignKey(
        'core.Tenant',
        on_delete=models.CASCADE,
        related_name='audit_logs',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='audit_logs',
    )
    module     = models.CharField(max_length=50, choices=AuditModule.choices)
    action     = models.CharField(max_length=50, choices=AuditAction.choices)
    source     = models.CharField(max_length=20, choices=AuditSource.choices, default=AuditSource.SYSTEM)
    field_name = models.CharField(max_length=100, null=True, blank=True)
    old_value  = models.TextField(null=True, blank=True)
    new_value  = models.TextField(null=True, blank=True)
    timestamp  = models.DateTimeField(auto_now_add=True)
    metadata   = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['tenant', 'module', 'action']),
            models.Index(fields=['tenant', '-timestamp']),
        ]

    def __str__(self):
        return f'{self.module}:{self.action} ({self.source}) by {self.user_id} at {self.timestamp}'
