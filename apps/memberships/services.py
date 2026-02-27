from django.db import transaction
from django.core.exceptions import ValidationError

from .models import Membership


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
        return membership