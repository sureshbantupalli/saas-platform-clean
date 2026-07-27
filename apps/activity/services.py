"""
Activity service layer.

Public API:
    create_activity(**kwargs)  — write one timeline entry; fault-tolerant

Design rules:
    - Always call from transaction.on_commit, never speculatively
    - Never store financial values (amount, price, fee) in metadata
    - Activity is reflective: (reference_type, reference_id) points to the source
    - Deleting all Activity rows must not affect any report or system behavior
"""
import logging

logger = logging.getLogger(__name__)


def create_activity(
    *,
    tenant,
    person,
    activity_type,
    title,
    vertical=None,
    reference_type="",
    reference_id=None,
    metadata=None,
    created_by=None,
):
    """
    Write one activity entry. Always call from transaction.on_commit.
    Fault-tolerant: logs exceptions but never raises into the caller.
    """
    try:
        from apps.activity.models import Activity
        Activity.base_objects.create(
            tenant=tenant,
            person=person,
            vertical=vertical,
            activity_type=activity_type,
            title=title,
            reference_type=reference_type,
            reference_id=reference_id,
            metadata=metadata or {},
            created_by=created_by,
        )
    except Exception:
        logger.exception("create_activity: failed to write activity entry")
