from django.utils import timezone
from datetime import timedelta

from crm.models import Enquiry, EnquiryActivity, FollowUp, LeadStage


class EnquiryLifecycleService:
    """
    Handles lifecycle operations for enquiries.
    This centralizes all lifecycle rules in one place.
    """

    # ==========================================================
    # STAGE MOVEMENT
    # ==========================================================

    @staticmethod
    def change_stage(enquiry, new_stage, user):
        """
        Change enquiry stage and log activity.
        """

        old_stage = enquiry.current_stage

        # If stage did not change, do nothing
        if old_stage == new_stage:
            return enquiry

        enquiry.current_stage = new_stage
        enquiry._acting_user = user
        enquiry.save(update_fields=["current_stage"])

        EnquiryActivity.objects.create(
            tenant=enquiry.tenant,
            enquiry=enquiry,
            performed_by=user,
            action_type="STAGE_CHANGED",
            old_value=old_stage.name if old_stage else None,
            new_value=new_stage.name if new_stage else None,
        )

        return enquiry


    # ==========================================================
    # NEXT PIPELINE STAGE
    # ==========================================================

    @staticmethod
    def get_next_pipeline_stage(enquiry):
        """
        Find the next stage in the tenant pipeline based on order.
        """

        if not enquiry.current_stage:
            return None

        next_stage = LeadStage.objects.filter(
            tenant=enquiry.tenant,
            is_active=True,
            show_in_pipeline=True,
            order__gt=enquiry.current_stage.order
        ).order_by("order").first()

        return next_stage


    # ==========================================================
    # CALL LOGGING
    # ==========================================================

    @staticmethod
    def log_call(enquiry, user, notes="Phone call made"):
        """
        Log a phone call activity, mark any pending follow-up done,
        and schedule the next follow-up for tomorrow.
        """
        EnquiryActivity.objects.create(
            tenant=enquiry.tenant,
            enquiry=enquiry,
            performed_by=user,
            action_type="CALL_LOGGED",
            notes=notes,
        )

        # Mark the earliest pending follow-up as done
        pending = (
            FollowUp.objects.filter(enquiry=enquiry, status=FollowUp.STATUS_PENDING)
            .order_by("due_date")
            .first()
        )
        if pending:
            from crm.services.followup_service import FollowUpService
            FollowUpService.mark_done(pending, user=user)

        # Auto-schedule next follow-up in 2 days (staff can adjust)
        FollowUp.objects.create(
            tenant        = enquiry.tenant,
            enquiry       = enquiry,
            followup_type = FollowUp.TYPE_CALL,
            due_date      = timezone.now().date() + timedelta(days=2),
            status        = FollowUp.STATUS_PENDING,
            notes         = "Follow-up after call",
            created_by    = user,
        )
        # Sync denormalized date
        enquiry.next_followup_date = timezone.now().date() + timedelta(days=2)
        enquiry._acting_user = user
        enquiry.save(update_fields=["next_followup_date"])


    # ==========================================================
    # FOLLOWUP SCHEDULING
    # ==========================================================

    @staticmethod
    def schedule_followup(enquiry, followup_date, user, notes="Follow-up scheduled",
                          followup_type=None):
        """
        Schedule next follow-up — updates Enquiry.next_followup_date AND
        creates a FollowUp record for status tracking.
        """
        old_date = enquiry.next_followup_date

        enquiry.next_followup_date = followup_date
        enquiry._acting_user = user
        enquiry.save(update_fields=["next_followup_date"])

        EnquiryActivity.objects.create(
            tenant=enquiry.tenant,
            enquiry=enquiry,
            performed_by=user,
            action_type="FOLLOWUP_SCHEDULED",
            old_value=str(old_date) if old_date else None,
            new_value=str(followup_date),
            notes=notes,
        )

        # Create a FollowUp record for queue tracking
        FollowUp.objects.create(
            tenant        = enquiry.tenant,
            enquiry       = enquiry,
            followup_type = followup_type or FollowUp.TYPE_CALL,
            due_date      = followup_date,
            status        = FollowUp.STATUS_PENDING,
            notes         = notes,
            created_by    = user,
        )


    # ==========================================================
    # MARK LOST
    # ==========================================================

    @staticmethod
    def mark_lost(enquiry, reason, user):
        """
        Mark enquiry as lost.
        """

        old_stage = enquiry.current_stage

        enquiry.lost_reason = reason
        enquiry._acting_user = user
        enquiry.save(update_fields=["lost_reason"])

        EnquiryActivity.objects.create(
            tenant=enquiry.tenant,
            enquiry=enquiry,
            performed_by=user,
            action_type="MARKED_LOST",
            old_value=old_stage.name if old_stage else None,
            new_value="Lost",
            notes=reason,
        )