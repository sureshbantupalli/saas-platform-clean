from django.utils import timezone

from crm.models import Enquiry, EnquiryActivity, LeadStage


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
        Log a phone call activity and optionally move stage forward.
        """

        EnquiryActivity.objects.create(
            tenant=enquiry.tenant,
            enquiry=enquiry,
            performed_by=user,
            action_type="CALL_LOGGED",
            notes=notes,
        )

       

    # ==========================================================
    # FOLLOWUP SCHEDULING
    # ==========================================================

    @staticmethod
    def schedule_followup(enquiry, followup_date, user, notes="Follow-up scheduled"):
        """
        Schedule next follow-up.
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