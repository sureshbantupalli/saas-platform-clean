from django.utils import timezone
from django.db import transaction
from apps.intake.models import IntakeForm, FormResponse


class FormLifecycleError(Exception):
    pass


class FormService:

    # ─── Lifecycle ────────────────────────────────────────────────────────────

    @staticmethod
    @transaction.atomic
    def activate_form(form):
        """
        Validates the form has at least 1 field, deactivates any currently
        active form for the same tenant, then marks this one active.
        Raises FormLifecycleError on rule violations.
        """
        field_count = form.fields.filter(is_deleted=False).count()
        if field_count == 0:
            raise FormLifecycleError("A form must have at least one field before it can be activated.")

        # Deactivate any currently active form for this tenant
        IntakeForm.base_objects.filter(
            tenant=form.tenant, status="active", is_deleted=False
        ).exclude(pk=form.pk).update(status="inactive")

        form.status = "active"
        form.published_at = timezone.now()
        form.save(update_fields=["status", "published_at", "updated_at"])
        return form

    @staticmethod
    def deactivate_form(form):
        form.status = "inactive"
        form.save(update_fields=["status", "updated_at"])
        return form

    @staticmethod
    def save_draft(form):
        """Marks a form as draft (used when an active form is being edited)."""
        form.status = "draft"
        form.save(update_fields=["status", "updated_at"])
        return form

    # ─── Queries ──────────────────────────────────────────────────────────────

    @staticmethod
    def get_active_form_for_entity(tenant, entity_type=None):
        """
        Returns the single active intake form for a tenant.
        Optionally filters by entity_type.
        """
        qs = IntakeForm.base_objects.filter(
            tenant=tenant, status="active", is_deleted=False
        )
        if entity_type:
            qs = qs.filter(entity_type=entity_type)
        return qs.first()

    @staticmethod
    def get_existing_response(form, entity_id):
        return (
            FormResponse.base_objects
            .filter(form=form, entity_id=entity_id, is_deleted=False)
            .first()
        )

    # ─── Validation & Submission ──────────────────────────────────────────────

    @staticmethod
    def validate_response(form, data):
        errors = {}
        for field in form.fields.filter(is_deleted=False).order_by("order"):
            value = data.get(field.field_key)
            if field.is_required and (value is None or value == "" or value == []):
                errors[field.field_key] = f"{field.label} is required."
        return errors

    @staticmethod
    def submit_response(form, entity_type, entity_id, data, submitted_by=None):
        """
        Validates that the form is active and that required fields are filled,
        then upserts the response.
        Returns (response, errors_dict). If errors is non-empty, response is None.
        """
        if form.status != "active":
            return None, {"__form__": "This form is not currently active and cannot accept responses."}

        errors = FormService.validate_response(form, data)
        if errors:
            return None, errors

        response, _ = FormResponse.base_objects.update_or_create(
            form=form,
            entity_id=entity_id,
            defaults={
                "tenant": form.tenant,
                "entity_type": entity_type,
                "data": data,
                "submitted_by": submitted_by,
                "is_deleted": False,
            }
        )
        return response, {}
