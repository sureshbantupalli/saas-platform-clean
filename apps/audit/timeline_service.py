from apps.audit.models import SettingsAuditLog


def _metadata_contains(qs, key, value):
    return qs.filter(metadata__icontains=f'"{key}": "{value}"')


def get_timeline(
    *,
    tenant,
    module=None,
    user_id=None,
    member_id=None,
    payment_id=None,
    limit=50,
    before=None,
):
    qs = SettingsAuditLog.objects.filter(tenant=tenant)

    if module:
        qs = qs.filter(module=module)

    if user_id:
        qs = qs.filter(user_id=user_id)

    if member_id:
        qs = _metadata_contains(qs, "member_id", member_id)

    if payment_id:
        qs = _metadata_contains(qs, "payment_id", payment_id)

    if before:
        qs = qs.filter(timestamp__lt=before)

    return qs.select_related("user").order_by("-timestamp")[:limit]
