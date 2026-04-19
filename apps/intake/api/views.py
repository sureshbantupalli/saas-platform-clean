from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from apps.intake.models import IntakeForm, FormField, FormResponse
from apps.intake.serializers import (
    IntakeFormSerializer,
    IntakeFormWriteSerializer,
    FormFieldSerializer,
    FormResponseSerializer,
    FormSubmitSerializer,
)
from apps.intake.services.form_service import FormService, FormLifecycleError
from apps.intake.services.prefill_service import PrefillService


class IntakeFormViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return IntakeFormWriteSerializer
        return IntakeFormSerializer

    def get_queryset(self):
        user = self.request.user
        return IntakeForm.base_objects.filter(
            tenant=user.tenant, is_deleted=False
        ).prefetch_related("fields")

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.user.tenant)

    @action(detail=True, methods=["get"], url_path="prefill")
    def prefill(self, request, pk=None):
        """
        GET /api/intake/forms/{id}/prefill/?entity_type=lead&entity_id=<uuid>
        Returns a data dict suitable for pre-populating the form.
        """
        form = self.get_object()
        entity_type = request.query_params.get("entity_type")
        entity_id = request.query_params.get("entity_id")

        if not entity_type or not entity_id:
            return Response({"detail": "entity_type and entity_id are required."}, status=400)

        data = {}
        if entity_type == "lead":
            from crm.models import Enquiry
            try:
                lead = Enquiry.objects.get(pk=entity_id, tenant=request.user.tenant)
                data = PrefillService.prefill_from_lead(form, lead)
            except Enquiry.DoesNotExist:
                pass
        elif entity_type == "member":
            from members.models import Member
            try:
                member = Member.objects.get(pk=entity_id, tenant=request.user.tenant)
                data = PrefillService.prefill_from_member(form, member)
            except Member.DoesNotExist:
                pass

        return Response({"prefill_data": data})

    @action(detail=True, methods=["post"], url_path="submit")
    def submit(self, request, pk=None):
        """POST /api/intake/forms/{id}/submit/"""
        form = self.get_object()
        ser = FormSubmitSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        response, errors = FormService.submit_response(
            form=form,
            entity_type=ser.validated_data["entity_type"],
            entity_id=ser.validated_data["entity_id"],
            data=ser.validated_data["data"],
            submitted_by=request.user,
        )
        if errors:
            return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)

        return Response(FormResponseSerializer(response).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"], url_path="response")
    def get_response(self, request, pk=None):
        """GET /api/intake/forms/{id}/response/?entity_id=<uuid>"""
        form = self.get_object()
        entity_id = request.query_params.get("entity_id")
        if not entity_id:
            return Response({"detail": "entity_id is required."}, status=400)

        response = FormService.get_existing_response(form, entity_id)
        if not response:
            return Response({"detail": "No response found."}, status=404)

        return Response(FormResponseSerializer(response).data)

    @action(detail=True, methods=["post"], url_path="publish")
    def publish(self, request, pk=None):
        """POST /api/intake/forms/{id}/publish/ — activates the form."""
        form = self.get_object()
        try:
            FormService.activate_form(form)
        except FormLifecycleError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(IntakeFormSerializer(form).data)

    @action(detail=True, methods=["post"], url_path="deactivate")
    def deactivate(self, request, pk=None):
        """POST /api/intake/forms/{id}/deactivate/"""
        form = self.get_object()
        FormService.deactivate_form(form)
        return Response(IntakeFormSerializer(form).data)

    @action(detail=False, methods=["get"], url_path="active")
    def active_form(self, request):
        """GET /api/intake/forms/active/?entity_type=member"""
        entity_type = request.query_params.get("entity_type")
        form = FormService.get_active_form_for_entity(request.user.tenant, entity_type)
        if not form:
            return Response({"detail": "No active form found."}, status=404)
        return Response(IntakeFormSerializer(form).data)


class FormFieldViewSet(viewsets.ModelViewSet):
    """
    Query: /api/intake/fields/?form_id=<uuid>
    Body for create: include form (UUID) field.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = FormFieldSerializer

    def get_queryset(self):
        qs = FormField.objects.filter(
            form__tenant=self.request.user.tenant,
            is_deleted=False
        )
        form_id = self.request.query_params.get("form_id")
        if form_id:
            qs = qs.filter(form__id=form_id)
        return qs.order_by("order")
