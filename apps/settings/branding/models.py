import re

from django.core.exceptions import ValidationError
from django.db import models


def _validate_hex(value):
    if value and not re.fullmatch(r'#[0-9A-Fa-f]{6}', value):
        raise ValidationError('Enter a valid hex colour, e.g. #1a2b3c.')


class TenantBranding(models.Model):
    tenant = models.OneToOneField(
        'core.Tenant',
        on_delete=models.CASCADE,
        related_name='branding',
    )
    logo            = models.ImageField(upload_to='tenant/logos/',    blank=True, null=True)
    favicon         = models.ImageField(upload_to='tenant/favicons/', blank=True, null=True)
    primary_color   = models.CharField(max_length=7, default='#0d6efd', validators=[_validate_hex])
    secondary_color = models.CharField(max_length=7, default='#6c757d', validators=[_validate_hex])
    login_title     = models.CharField(max_length=100, blank=True)
    custom_css      = models.TextField(blank=True)
    whitelabel_enabled = models.BooleanField(
        default=False,
        help_text='Enable white-label branding for this tenant.',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'settings_branding'

    def __str__(self):
        return f'Branding for {self.tenant_id}'
