from django.core.exceptions import ValidationError


def ensure_enquiry_not_converted(enquiry):
    """
    Prevent modification of enquiries that are already converted to members.
    """

    if enquiry.converted_member:
        raise ValidationError(
            "This enquiry has already been converted and cannot be modified."
        )