from django.utils import timezone
from apps.memberships.models import Membership


def validate_member_for_attendance(member, session):
    """
    Central policy validation for attendance (FINAL SAFE VERSION)
    """

    # ✅ Always use DATE (avoid datetime issues)
    today = timezone.now().date()

    # =========================================================
    # 1. Get active membership (STRICT FILTER)
    # =========================================================
    membership = (
        Membership.base_objects
        .filter(
            member=member,
            tenant=member.tenant,
            status="active",
            is_deleted=False
        )
        .order_by("-end_date")
        .first()
    )

    if not membership:
        return {
            "allowed": False,
            "reason": "No active membership"
        }

    # =========================================================
    # 2. Validate membership start date
    # =========================================================
    if membership.start_date and membership.start_date > today:
        return {
            "allowed": False,
            "reason": "Membership not started yet"
        }

    # =========================================================
    # 3. Validate expiry
    # =========================================================
    if membership.end_date and membership.end_date < today:
        return {
            "allowed": False,
            "reason": "Membership expired"
        }

    # =========================================================
    # 4. OPTIONAL: Tenant safety (VERY IMPORTANT FOR SaaS)
    # =========================================================
    if hasattr(member, "tenant") and hasattr(session, "tenant"):
        if member.tenant != session.tenant:
            return {
                "allowed": False,
                "reason": "Tenant mismatch"
            }

    # =========================================================
    # 5. OPTIONAL: Branch validation (future-ready)
    # =========================================================
    if hasattr(membership, "branch") and hasattr(session, "branch"):
        if membership.branch and session.branch:
            if membership.branch != session.branch:
                return {
                    "allowed": False,
                    "reason": "Membership not valid for this branch"
                }

    # =========================================================
    # ✅ FINAL PASS
    # =========================================================
    return {
        "allowed": True,
        "reason": "Allowed",
        "membership": membership
    }