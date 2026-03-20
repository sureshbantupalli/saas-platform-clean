from django.db import models
from apps.core.tenant_context import get_current_tenant


class TenantQuerySet(models.QuerySet):

    def for_current_tenant(self):
        tenant = get_current_tenant()

        if tenant is None:
            return self.none()

        return self.filter(tenant=tenant)


class TenantManager(models.Manager):

    def get_queryset(self):
        queryset = super().get_queryset()
        tenant = get_current_tenant()

        if tenant is None:
            return queryset.none()

        return queryset.filter(tenant=tenant)