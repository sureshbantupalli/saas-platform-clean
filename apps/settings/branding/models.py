import re

from django.core.exceptions import ValidationError
from django.db import models


def _validate_hex(value):
    if value and not re.fullmatch(r'#[0-9A-Fa-f]{6}', value):
        raise ValidationError('Enter a valid hex colour, e.g. #1a2b3c.')


# Bare hostname/subdomain: labels separated by dots, no protocol, no path.
_DOMAIN_RE = re.compile(
    r'^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$'
)


def _validate_custom_domain(value):
    """Reject values with protocols, paths, or invalid hostname characters."""
    if not value:
        return
    if not _DOMAIN_RE.fullmatch(value):
        raise ValidationError(
            'Enter a bare domain name without protocol or path, e.g. app.mygym.com.'
        )


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
    custom_domain = models.CharField(
        max_length=253,
        blank=True,
        validators=[_validate_custom_domain],
        help_text='Tenant custom domain (e.g. app.mygym.com). Used to brand payment and checkout links.',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'settings_branding'

    def __str__(self):
        return f'Branding for {self.tenant_id}'
