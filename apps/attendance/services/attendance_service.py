import logging

from members.models import Member
from apps.attendance.models import Attendance
from apps.memberships.services.policy_service import validate_member_for_attendance

logger = logging.getLogger(__name__)


def bulk_mark_attendance(session, member_ids, tenant, marked_by=None):
    """
    Mark attendance for multiple members in a session.
    Validates membership policy for each member before marking.
    Returns a dict with 'success' and 'failed' lists.
    """

    success = []
    failed = []

    members = Member.objects.filter(id__in=member_ids, tenant=tenant)

    for member in members:

        result = validate_member_for_attendance(member, session)

        if not result["allowed"]:
            failed.append({"member_id": str(member.id), "reason": result["reason"]})
            continue

        membership = result.get("membership")

        session_date = session.start_time.date()

        if Attendance.objects.filter(member=member, session_date=session_date, tenant=tenant).exists():
            failed.append({"member_id": str(member.id), "reason": "Already marked for this session"})
            continue

        if membership and hasattr(membership.plan, "plan_type"):
            if membership.plan.plan_type == "CLASS_PACK":
                if membership.remaining_sessions is not None and membership.remaining_sessions <= 0:
                    failed.append({"member_id": str(member.id), "reason": "No remaining sessions"})
                    continue

        attendance = Attendance.objects.create(
            member=member,
            tenant=tenant,
            attendance_type="session",
            session_date=session_date,
            check_in_time=session.start_time,
        )

        _audit_attendance_marked(
            tenant=tenant,
            attendance_id=str(attendance.id),
            member_id=str(member.id),
            session_id=str(session.id),
            marked_by=marked_by,
        )

        success.append({"member_id": str(member.id), "status": "marked"})

    logger.info(
        "Bulk attendance complete for session %s: %d marked, %d failed",
        session.id, len(success), len(failed)
    )

    return {"success": success, "failed": failed}


def _audit_attendance_marked(*, tenant, attendance_id, member_id, session_id, marked_by):
    try:
        from apps.audit.services import log_attendance_change
        log_attendance_change(
            tenant=tenant,
            user=marked_by,
            action='create',
            field_name='status',
            new_value='present',
            metadata={
                'attendance_id': attendance_id,
                'member_id':     member_id,
                'session_id':    session_id,
            },
        )
    except Exception:
        pass
