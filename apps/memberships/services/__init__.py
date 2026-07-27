from django.db import transaction
from django.core.exceptions import ValidationError

from apps.memberships.models import Membership


class MembershipService:

    @staticmethod
    @transaction.atomic
    def create_membership(
        *,
        member,
        branch,
        plan_name,
        start_date,
        end_date,
        fee_amount,
        created_by,
        auto_renew=False,
        status="active",
    ):
        """
        Creates a membership with full validation and tenant enforcement.
        """

        membership = Membership(
            member=member,
            branch=branch,
            plan_name=plan_name,
            start_date=start_date,
            end_date=end_date,
            fee_amount=fee_amount,
            created_by=created_by,
            auto_renew=auto_renew,
            status=status,
        )

        membership.save()  # Triggers full_clean + tenant enforcement

        # Audit — fires after commit so the log only reflects persisted state.
        # fee_amount is intentionally excluded: financial values belong in the
        # Membership model, not in the audit log.
        _t     = membership.tenant
        _mid   = str(membership.id)
        _memid = str(member.id)
        _plan  = plan_name
        _st    = status
        _user  = created_by
        transaction.on_commit(lambda: _audit_membership_created(
            tenant=_t, membership_id=_mid, member_id=_memid,
            plan_name=_plan, status=_st, user=_user,
        ))

        return membership


def log_membership_enrolled(membership, *, created_by=None):
    """
    Standalone audit helper — call this when a membership is created outside
    MembershipService (e.g. directly via serializer or shell).
    """
    _audit_membership_created(
        tenant=membership.tenant,
        membership_id=str(membership.id),
        member_id=str(membership.member_id),
        plan_name=getattr(membership, 'plan_name', ''),
        status=membership.status,
        user=created_by,
    )


def _audit_membership_updated(*, tenant, membership_id, member_id, old_status, new_status, user=None):
    try:
        from apps.audit.services import log_membership_change
        log_membership_change(
            tenant=tenant,
            user=user,
            action='update',
            field_name='status',
            old_value=old_status,
            new_value=new_status,
            metadata={
                'membership_id': membership_id,
                'member_id':     member_id,
            },
        )
    except Exception:
        pass


def _audit_membership_created(*, tenant, membership_id, member_id, plan_name, status, user):
    try:
        from apps.audit.services import log_membership_change
        log_membership_change(
            tenant=tenant,
            user=user,
            action='create',
            field_name='status',
            new_value=status,
            metadata={
                'membership_id': membership_id,
                'member_id':     member_id,
                'plan_name':     plan_name,
            },
        )
    except Exception:
        pass  # log_membership_change is fault-tolerant; this catches import errors
