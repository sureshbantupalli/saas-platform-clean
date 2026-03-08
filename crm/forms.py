from django import forms
from .models import Enquiry, LeadStage, EnquirySource


class EnquiryForm(forms.ModelForm):

    class Meta:
        model = Enquiry

        fields = [
            "full_name",
            "phone",
            "email",
            "source",
            "current_stage",
            "assigned_to",
            "lost_reason",
            "next_followup_date",
            "notes",
        ]

        widgets = {
            "next_followup_date": forms.DateInput(
                attrs={
                    "type": "date",
                    "class": "form-control",
                }
            ),
        }

    def __init__(self, *args, **kwargs):

        # Capture tenant passed from view
        self.tenant = kwargs.pop("tenant", None)

        super().__init__(*args, **kwargs)

        # Apply bootstrap styling
        for name, field in self.fields.items():
            if name != "next_followup_date":
                field.widget.attrs.update({"class": "form-control"})

        # Filter stages by tenant
        if self.tenant:
            self.fields["current_stage"].queryset = LeadStage.objects.filter(
                tenant=self.tenant,
                is_active=True
            ).order_by("order")

        # Filter lead sources by tenant
        if self.tenant:
            self.fields["source"].queryset = EnquirySource.objects.filter(
                tenant=self.tenant,
                is_active=True
            ).order_by("name")

        # Default stage = New
        if self.tenant and not self.instance.pk:

            new_stage = LeadStage.objects.filter(
                tenant=self.tenant,
                name__iexact="New"
            ).first()

            if new_stage:
                self.initial["current_stage"] = new_stage
                self.fields["current_stage"].disabled = True

        # Lock form after conversion
        if self.instance and self.instance.converted_member:
            for field in self.fields.values():
                field.disabled = True

    # --------------------------------------------------
    # Hard Duplicate Phone Validation
    # --------------------------------------------------

    def clean_phone(self):

        phone = self.cleaned_data.get("phone")

        if not phone:
            return phone

        if self.tenant:

            existing = Enquiry.objects.filter(
                tenant=self.tenant,
                phone=phone
            ).exclude(pk=self.instance.pk)

            if existing.exists():
                raise forms.ValidationError(
                    "An enquiry with this phone number already exists."
                )

        return phone

    # --------------------------------------------------
    # Soft Duplicate Email Warning
    # --------------------------------------------------

    def clean_email(self):

        email = self.cleaned_data.get("email")

        if not email:
            return email

        if self.tenant:

            existing = Enquiry.objects.filter(
                tenant=self.tenant,
                email__iexact=email
            ).exclude(pk=self.instance.pk).first()

            if existing:
                print("DEBUG DUPLICATE FOUND:", existing)
                # Save duplicate lead for warning message
                self.duplicate_email_warning = existing

        return email