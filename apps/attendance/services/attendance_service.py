from members.models import Member
from apps.attendance.models import Attendance
from apps.memberships.services.policy_service import validate_member_for_attendance


def bulk_mark_attendance(session, member_ids, tenant, marked_by=None):
    """
    Bulk attendance marking service (FINAL FIXED VERSION)
    """

    success = []
    failed = []

    members = Member.objects.filter(id__in=member_ids, tenant=tenant)

    for member in members:

        # =========================================================
        # 1. Validate policy
        # =========================================================
        result = validate_member_for_attendance(member, session)

        if not result["allowed"]:
            failed.append({
                "member_id": str(member.id),
                "reason": result["reason"]
            })
            continue

        membership = result.get("membership")

        # =========================================================
        # 2. Extract session date
        # =========================================================
        session_date = session.start_time.date()

        # =========================================================
        # 3. Prevent duplicate attendance
        # =========================================================
        existing = Attendance.objects.filter(
            member=member,
            session_date=session_date,
            tenant=tenant
        ).exists()

        if existing:
            failed.append({
                "member_id": str(member.id),
                "reason": "Already marked for this session"
            })
            continue

        # =========================================================
        # 4. Validate class pack usage
        # =========================================================
        if membership and hasattr(membership.plan, "plan_type"):
            if membership.plan.plan_type == "CLASS_PACK":
                if membership.remaining_sessions is not None and membership.remaining_sessions <= 0:
                    failed.append({
                        "member_id": str(member.id),
                        "reason": "No remaining sessions"
                    })
                    continue

        # =========================================================
        # 5. CREATE ATTENDANCE (🔥 FIX HERE)
        # =========================================================
        Attendance.objects.create(
            member=member,
            tenant=tenant,
            session_date=session_date,

            # 🔥 IMPORTANT FIX (was .time() before)
            check_in_time=session.start_time,
        )

        success.append({
            "member_id": str(member.id),
            "status": "marked"
        })

    return {
        "success": success,
        "failed": failed
    }