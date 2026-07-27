"""
Enrollment service layer.

Public API:
    enroll_person_in_service(**kwargs) → Enrollment

Design rules:
    - Service defines the offering; Enrollment records participation — never mix them
    - Activity fires only after successful DB commit (transaction.on_commit)
    - No ghost activities: if enrollment creation rolls back, no activity is created
    - Exactly one activity per successful enrollment call
"""
from datetime import date

from django.db import transaction


def enroll_person_in_service(
    *,
    person,
    service,
    vertical,
    start_date=None,
    source=None,
    notes="",
    created_by=None,
):
    """
    Enroll a person in a service within a vertical.

    person    — members.Member
    service   — catalog.Service (nullable: enroll in a vertical without a specific service)
    vertical  — verticals.BusinessVertical
    source    — optional dict {"type": ReferenceType-value, "id": UUID}
                stored as analytics lineage only; never used for business logic
    """
    from apps.enrollments.models import Enrollment

    tenant = person.tenant

    if service is not None and service.tenant_id != tenant.pk:
        raise ValueError("Service does not belong to person's tenant.")
    if vertical.tenant_id != tenant.pk:
        raise ValueError("Vertical does not belong to person's tenant.")

    if start_date is None:
        start_date = date.today()

    source_type = ""
    source_id   = None
    if source is not None:
        source_type = source.get("type") or ""
        source_id   = source.get("id")

    with transaction.atomic():
        enrollment = Enrollment.base_objects.create(
            tenant=tenant,
            person=person,
            vertical=vertical,
            service=service,
            start_date=start_date,
            source_type=source_type,
            source_id=source_id,
            notes=notes,
            created_by=created_by,
        )

        # Capture all values before the lambda closes over them —
        # the enrollment row is committed, but the objects stay valid.
        _t        = tenant
        _e_id     = enrollment.id       # UUID, not str — UUIDField accepts both
        _person   = person
        _vert     = vertical
        _svc_name = service.name if service is not None else ""

        transaction.on_commit(lambda: _log_enrollment_activity(
            tenant=_t,
            person=_person,
            vertical=_vert,
            enrollment_id=_e_id,
            service_name=_svc_name,
        ))

    return enrollment


def _log_enrollment_activity(*, tenant, person, vertical, enrollment_id, service_name):
    try:
        from apps.activity.models import ActivityType
        from apps.activity.services import create_activity
        create_activity(
            tenant=tenant,
            person=person,
            vertical=vertical,
            activity_type=ActivityType.ENROLLMENT,
            title=f"Enrolled in {service_name}" if service_name else "Enrolled",
            reference_type="enrollment",
            reference_id=enrollment_id,
        )
    except Exception:
        pass
