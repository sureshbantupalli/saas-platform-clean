from django.db import models

from apps.core.models import TenantAwareModel


class TenantVocabulary(TenantAwareModel):
    tenant = models.ForeignKey(
        'core.Tenant',
        on_delete=models.CASCADE,
        related_name='vocabulary_entries',
    )
    key          = models.CharField(max_length=60, db_index=True)
    label        = models.CharField(max_length=120)
    plural_label = models.CharField(max_length=120, blank=True)

    class Meta:
        db_table = 'settings_vocabulary'
        unique_together = [('tenant', 'key')]
        ordering = ['key']

    def __str__(self):
        return f'{self.tenant_id}:{self.key} → {self.label}'
