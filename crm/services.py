from django.db import transaction
from django.core.exceptions import ValidationError
from .models import Enquiry, EnquiryActivity


@transaction.atomic
def change_enquiry_stage(enquiry, new_stage, user):
    """
    Handles stage transition with:
    - Loss validation
    - Phone validation for conversion
    - Activity logging
    - Conversion trigger signal (no auto member creation)
    """

    old_stage = enquiry.current_stage

    # 🔴 Loss stage validation
    if new_stage.is_loss_stage:
        if not enquiry.lost_reason:
            raise ValidationError(
                "Lost reason must be selected before marking as Lost."
            )

    # 🟢 Conversion stage validation
    if new_stage.is_conversion_stage:
        if not enquiry.phone:
            raise ValidationError(
                "Phone number is required before converting to Member."
            )

        if enquiry.converted_member:
            raise ValidationError(
                "This enquiry is already converted."
            )

    # Update stage
    enquiry.current_stage = new_stage
    enquiry.save()

    # Log stage change
    EnquiryActivity.objects.create(
        tenant=enquiry.tenant,
        enquiry=enquiry,
        action_type="STAGE_CHANGED",
        performed_by=user,
        old_value=old_stage.name,
        new_value=new_stage.name,
    )

    # If conversion stage reached → signal UI to redirect
    if new_stage.is_conversion_stage:
        return {
            "status": "conversion_required",
            "enquiry_id": enquiry.id
        }

    return {
        "status": "stage_updated",
        "enquiry_id": enquiry.id
    }

def check_duplicate_phone(tenant, phone, exclude_enquiry_id=None):
    """
    Soft duplicate detection.
    Returns existing enquiry with same phone number within tenant.
    Does NOT block creation.
    """

    from .models import Enquiry

    if not phone:
        return None

    queryset = Enquiry.objects.filter(
        tenant=tenant,
        phone=phone
    )

    if exclude_enquiry_id:
        queryset = queryset.exclude(id=exclude_enquiry_id)

    return queryset.first()

def assign_enquiry(enquiry, user_to_assign, performed_by):
    """
    Assign or reassign an enquiry.
    Logs assignment changes.
    """

    old_user = enquiry.assigned_to

    # If no change, do nothing
    if old_user == user_to_assign:
        return enquiry

    enquiry.assigned_to = user_to_assign
    enquiry.save()

    EnquiryActivity.objects.create(
        tenant=enquiry.tenant,
        enquiry=enquiry,
        action_type="ASSIGNED",
        performed_by=performed_by,
        old_value=str(old_user) if old_user else None,
        new_value=str(user_to_assign) if user_to_assign else None,
    )

    return enquiry

def complete_conversion(enquiry, member, performed_by):
    """
    Finalizes CRM conversion after Member is successfully created.
    """

    if enquiry.converted_member:
        return enquiry  # Already linked

    enquiry.converted_member = member
    enquiry.save()

    EnquiryActivity.objects.create(
        tenant=enquiry.tenant,
        enquiry=enquiry,
        action_type="CONVERTED",
        performed_by=performed_by,
        new_value=str(member),
    )

    return enquiry