"""
Follow-Up Service

Central place for creating and updating FollowUp records.
Works for both Enquiry (pre-conversion) and Member (post-conversion) contexts.
"""
import logging
from datetime import date

from django.utils import timezone

from crm.models import EnquiryActivity, FollowUp

logger = logging.getLogger("crm.followup")


class FollowUpService:

    # ── Creation ──────────────────────────────────────────────────────────────

    @staticmethod
    def create_for_enquiry(
        enquiry,
        followup_type=FollowUp.TYPE_CALL,
        due_date=None,
        notes="",
        reference_type="",
        reference_id="",
        created_by=None,
    ) -> FollowUp:
        """Create a follow-up task linked to an enquiry."""
        if due_date is None:
            due_date = timezone.now().date()

        fu = FollowUp.objects.create(
            tenant        = enquiry.tenant,
            enquiry       = enquiry,
            followup_type = followup_type,
            due_date      = due_date,
            status        = FollowUp.STATUS_PENDING,
            notes         = notes,
            reference_type = reference_type,
            reference_id   = str(reference_id) if reference_id else "",
            created_by    = created_by,
        )
        logger.info("FollowUp created for enquiry %s: %s", enquiry.pk, fu.pk)
        return fu

    @staticmethod
    def create_for_member(
        member,
        tenant,
        followup_type=FollowUp.TYPE_CALL,
        due_date=None,
        notes="",
        reference_type="",
        reference_id="",
        created_by=None,
    ) -> FollowUp:
        """Create a follow-up task linked to a converted member."""
        if due_date is None:
            due_date = timezone.now().date()

        fu = FollowUp.objects.create(
            tenant         = tenant,
            member         = member,
            followup_type  = followup_type,
            due_date       = due_date,
            status         = FollowUp.STATUS_PENDING,
            notes          = notes,
            reference_type = reference_type,
            reference_id   = str(reference_id) if reference_id else "",
            created_by     = created_by,
        )
        logger.info("FollowUp created for member %s: %s", member.pk, fu.pk)
        return fu

    # ── Status transitions ────────────────────────────────────────────────────

    @staticmethod
    def mark_done(followup: FollowUp, user=None) -> FollowUp:
        """Mark a follow-up as done and log to EnquiryActivity if applicable."""
        followup.status = FollowUp.STATUS_DONE
        followup.save(update_fields=["status", "updated_at"])

        if followup.enquiry:
            EnquiryActivity.objects.create(
                tenant      = followup.tenant,
                enquiry     = followup.enquiry,
                action_type = "FOLLOWUP_DONE",
                performed_by = user,
                notes       = f"{followup.get_followup_type_display()} completed",
            )
            # Update denormalized next_followup_date on Enquiry
            FollowUpService._sync_enquiry_next_date(followup.enquiry)

        return followup

    @staticmethod
    def mark_missed(followup: FollowUp) -> FollowUp:
        followup.status = FollowUp.STATUS_MISSED
        followup.save(update_fields=["status", "updated_at"])

        if followup.enquiry:
            EnquiryActivity.objects.create(
                tenant      = followup.tenant,
                enquiry     = followup.enquiry,
                action_type = "FOLLOWUP_MISSED",
                notes       = f"{followup.get_followup_type_display()} follow-up on {followup.due_date} was missed",
            )
        return followup

    @staticmethod
    def mark_overdue_as_missed(tenant=None):
        """
        Batch: mark all pending follow-ups past due_date as missed.
        Pass tenant=None to run across all tenants (for management commands).
        """
        today = timezone.now().date()
        qs = FollowUp.objects.filter(status=FollowUp.STATUS_PENDING, due_date__lt=today)
        if tenant:
            qs = qs.filter(tenant=tenant)
        count = 0
        for fu in qs.select_related("enquiry"):
            FollowUpService.mark_missed(fu)
            count += 1
        logger.info("Marked %d follow-ups as missed", count)
        return count

    # ── Queue ─────────────────────────────────────────────────────────────────

    @staticmethod
    def get_queue(tenant):
        """
        Return pending follow-ups for the tenant ordered:
        overdue → today → upcoming.
        """
        today = timezone.now().date()
        return (
            FollowUp.objects.filter(tenant=tenant, status=FollowUp.STATUS_PENDING)
            .select_related("enquiry", "member")
            .order_by("due_date")
        )

    @staticmethod
    def get_queue_sections(tenant):
        """Return (overdue, today, upcoming) querysets."""
        today = timezone.now().date()
        base = FollowUp.objects.filter(
            tenant=tenant, status=FollowUp.STATUS_PENDING
        ).select_related("enquiry", "member")

        return (
            base.filter(due_date__lt=today).order_by("due_date"),
            base.filter(due_date=today).order_by("due_date"),
            base.filter(due_date__gt=today).order_by("due_date"),
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _sync_enquiry_next_date(enquiry):
        """Update Enquiry.next_followup_date to the next pending follow-up date."""
        next_fu = (
            FollowUp.objects.filter(enquiry=enquiry, status=FollowUp.STATUS_PENDING)
            .order_by("due_date")
            .first()
        )
        new_date = next_fu.due_date if next_fu else None
        if enquiry.next_followup_date != new_date:
            enquiry.next_followup_date = new_date
            enquiry._acting_user = None
            enquiry.save(update_fields=["next_followup_date"])
