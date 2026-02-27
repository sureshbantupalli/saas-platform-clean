from datetime import timedelta

from django.db import transaction
from django.db.models import Prefetch, Q
from django.utils import timezone

from members.models import Member
from apps.memberships.models import Membership


class MemberService:

    # =====================================================
    # Queryset with Search + Status Filter + Expiring Filter
    # =====================================================

    @staticmethod
    def get_queryset(
        user,
        search_query=None,
        status_filter=None,
        expiring_filter=False
    ):
        tenant = user.tenant

        queryset = (
            Member.objects
            .filter(
                tenant=tenant,
                is_deleted=False
            )
            .prefetch_related(
                Prefetch(
                    "memberships",
                    queryset=Membership.objects.filter(tenant=tenant)
                )
            )
            .prefetch_related("branches")
        )

        # 🔐 RBAC restriction
        if not user.is_platform_admin:
            queryset = queryset.filter(created_by=user)

        # 🔍 Search filter
        if search_query:
            queryset = queryset.filter(
                Q(first_name__icontains=search_query) |
                Q(last_name__icontains=search_query) |
                Q(email__icontains=search_query) |
                Q(phone__icontains=search_query)
            )

        # Convert queryset to list (we attach derived fields)
        members = list(queryset)

        # 🔥 Attach derived display_status
        for member in members:
            member.display_status = MemberService._derive_status(member)

        # 🎯 Status Filter (based on derived status)
        if status_filter:
            members = [
                m for m in members
                if m.display_status == status_filter
            ]

        # 🔥 Expiring Soon Filter
        if expiring_filter:
            today = timezone.now().date()
            threshold = today + timedelta(days=7)

            filtered_members = []

            for member in members:

                # Only ACTIVE members can expire soon
                if member.display_status != "ACTIVE":
                    continue

                for membership in member.memberships.all():

                    final_end = membership.final_end_date

                    if (
                        membership.status == "active"
                        and final_end
                        and today <= final_end <= threshold
                    ):
                        filtered_members.append(member)
                        break  # prevent duplicate counting

            members = filtered_members

        return members

    # =====================================================
    # Derive Status From Memberships
    # =====================================================

    @staticmethod
    def _derive_status(member):
        memberships = list(member.memberships.all())

        if not memberships:
            return "NO_PLAN"

        # Priority Order:
        # ACTIVE > PAUSED > EXPIRED > CANCELLED

        for m in memberships:
            if m.status == "active":
                return "ACTIVE"

        for m in memberships:
            if m.status == "paused":
                return "PAUSED"

        for m in memberships:
            if m.status == "expired":
                return "EXPIRED"

        for m in memberships:
            if m.status == "cancelled":
                return "CANCELLED"

        return "UNKNOWN"

    # =====================================================
    # Expiring Soon Count (Lifecycle Intelligence)
    # =====================================================

    @staticmethod
    def get_expiring_soon_count(members, days=7):
        """
        Count ACTIVE members whose membership
        final_end_date falls within next X days.
        """

        today = timezone.now().date()
        threshold = today + timedelta(days=days)

        count = 0

        for member in members:

            if getattr(member, "display_status", None) != "ACTIVE":
                continue

            for membership in member.memberships.all():

                final_end = membership.final_end_date

                if (
                    membership.status == "active"
                    and final_end
                    and today <= final_end <= threshold
                ):
                    count += 1
                    break  # Prevent double counting

        return count

    # =====================================================
    # Get By ID (RBAC Safe)
    # =====================================================

    @staticmethod
    def get_by_id(user, pk):
        tenant = user.tenant

        try:
            member = Member.objects.get(
                pk=pk,
                tenant=tenant,
                is_deleted=False
            )
        except Member.DoesNotExist:
            return None

        if not user.is_platform_admin and member.created_by != user:
            return None

        member.display_status = MemberService._derive_status(member)

        return member

    # =====================================================
    # Create Member (Tenant Safe)
    # =====================================================

    @staticmethod
    @transaction.atomic
    def create_member(user, data):
        branches = data.pop("branches", [])

        member = Member.objects.create(
            tenant=user.tenant,
            created_by=user,
            **data
        )

        if branches:
            member.branches.set(branches)

        return member

    # =====================================================
    # Soft Delete
    # =====================================================

    @staticmethod
    def soft_delete(member):
        member.is_deleted = True
        member.save(update_fields=["is_deleted", "updated_at"])

    # =====================================================
    # KPI Summary
    # =====================================================

    @staticmethod
    def get_kpis(members):
        """
        members: list (already derived with display_status)
        """

        summary = {
            "total": len(members),
            "ACTIVE": 0,
            "PAUSED": 0,
            "EXPIRED": 0,
            "CANCELLED": 0,
            "NO_PLAN": 0,
        }

        for member in members:
            status = getattr(member, "display_status", "UNKNOWN")
            if status in summary:
                summary[status] += 1

        return summary