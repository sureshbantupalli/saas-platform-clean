import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.urls import reverse

from .models import IntakeForm, FormField, FormResponse
from .services.form_service import FormService, FormLifecycleError
from .services.prefill_service import PrefillService


# ─── Form Builder List ────────────────────────────────────────────────────────

@login_required
def form_builder_list(request):
    forms = IntakeForm.base_objects.filter(
        tenant=request.user.tenant, is_deleted=False
    ).order_by("name")
    return render(request, "intake/form_builder_list.html", {"forms": forms})


@login_required
def form_create(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        description = request.POST.get("description", "").strip()
        entity_type = request.POST.get("entity_type", "member")
        if name:
            f = IntakeForm.base_objects.create(
                tenant=request.user.tenant,
                name=name,
                description=description,
                entity_type=entity_type,
                status="draft",
            )
            return redirect("intake:form_builder_detail", form_id=f.pk)
    return redirect("intake:form_builder_list")


# ─── Form Builder Detail ──────────────────────────────────────────────────────

@login_required
def form_builder_detail(request, form_id):
    form = get_object_or_404(
        IntakeForm.base_objects, pk=form_id, tenant=request.user.tenant, is_deleted=False
    )
    fields = form.fields.filter(is_deleted=False).order_by("order")
    field_type_choices = FormField._meta.get_field("field_type").choices
    return render(request, "intake/form_builder_detail.html", {
        "form": form,
        "fields": fields,
        "field_type_choices": field_type_choices,
    })


# ─── Lifecycle Actions ────────────────────────────────────────────────────────

@login_required
@require_POST
def form_activate(request, form_id):
    form = get_object_or_404(
        IntakeForm.base_objects, pk=form_id, tenant=request.user.tenant, is_deleted=False
    )
    try:
        FormService.activate_form(form)
        messages.success(request, f'"{form.name}" is now active.')
    except FormLifecycleError as e:
        messages.error(request, str(e))
    return redirect("intake:form_builder_detail", form_id=form.pk)


@login_required
@require_POST
def form_deactivate(request, form_id):
    form = get_object_or_404(
        IntakeForm.base_objects, pk=form_id, tenant=request.user.tenant, is_deleted=False
    )
    FormService.deactivate_form(form)
    messages.success(request, f'"{form.name}" deactivated.')
    return redirect("intake:form_builder_detail", form_id=form.pk)


@login_required
@require_POST
def form_save_draft(request, form_id):
    form = get_object_or_404(
        IntakeForm.base_objects, pk=form_id, tenant=request.user.tenant, is_deleted=False
    )
    if form.status == "active":
        FormService.save_draft(form)
        messages.info(request, f'"{form.name}" moved back to draft.')
    return redirect("intake:form_builder_detail", form_id=form.pk)


# ─── Field CRUD (AJAX) ────────────────────────────────────────────────────────

@login_required
@require_POST
def field_create(request, form_id):
    form = get_object_or_404(
        IntakeForm.base_objects, pk=form_id, tenant=request.user.tenant
    )
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    max_order = form.fields.filter(is_deleted=False).count()
    field = FormField.objects.create(
        form=form,
        label=body.get("label", "New Field"),
        field_key=body.get("field_key", ""),
        field_type=body.get("field_type", "text"),
        placeholder=body.get("placeholder", ""),
        help_text=body.get("help_text", ""),
        is_required=body.get("is_required", False),
        order=body.get("order", max_order),
        options=body.get("options", []),
        scale_config=body.get("scale_config", {}),
    )
    return JsonResponse({"id": str(field.id), "label": field.label, "order": field.order})


@login_required
@require_POST
def field_update(request, form_id, field_id):
    field = get_object_or_404(
        FormField, pk=field_id, form__id=form_id, form__tenant=request.user.tenant
    )
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    for attr in ("label", "field_key", "field_type", "placeholder", "help_text",
                 "is_required", "order", "options", "scale_config"):
        if attr in body:
            setattr(field, attr, body[attr])
    field.save()
    return JsonResponse({"ok": True})


@login_required
@require_POST
def field_delete(request, form_id, field_id):
    field = get_object_or_404(
        FormField, pk=field_id, form__id=form_id, form__tenant=request.user.tenant
    )
    field.is_deleted = True
    field.save()
    return JsonResponse({"ok": True})


# ─── Form Renderer (User-facing submission) ───────────────────────────────────

@login_required
def form_render(request, form_id):
    """
    Renders an intake form for submission.
    - ACTIVE forms: live submission, saves to form_responses, redirects to
      membership selection (or explicit ?next=).
    - Draft/Inactive forms: preview-only (no submission accepted).
    Prefills from lead or member when entity_type + entity_id are supplied.
    """
    form = get_object_or_404(
        IntakeForm.base_objects, pk=form_id, tenant=request.user.tenant, is_deleted=False
    )

    # entity_type / entity_id can arrive via GET params on first load
    # and must be preserved through POST (sent as hidden fields in the template)
    entity_type = (request.POST.get("entity_type") or request.GET.get("entity_type", "")).strip()
    entity_id   = (request.POST.get("entity_id")   or request.GET.get("entity_id",   "")).strip()
    next_url    = (request.POST.get("next")         or request.GET.get("next", "")).strip()

    fields = form.fields.filter(is_deleted=False).order_by("order")

    # ── Cancel URL ────────────────────────────────────────────────────────────
    # Prefer: member detail → CRM enquiry detail → intake form list
    if entity_type == "member" and entity_id:
        cancel_url = reverse("members:member_detail", args=[entity_id])
    elif entity_type == "lead" and entity_id:
        try:
            from crm.models import Enquiry
            enq = Enquiry.objects.get(pk=entity_id, tenant=request.user.tenant)
            cancel_url = reverse("crm:enquiry_detail", args=[enq.pk])
        except Exception:
            cancel_url = reverse("intake:form_builder_list")
    else:
        cancel_url = reverse("intake:form_builder_list")

    # ── Prefill data ──────────────────────────────────────────────────────────
    prefill_data = {}
    if entity_type == "lead" and entity_id:
        from crm.models import Enquiry
        try:
            lead = Enquiry.objects.get(pk=entity_id, tenant=request.user.tenant)
            prefill_data = PrefillService.prefill_from_lead(form, lead)
        except Enquiry.DoesNotExist:
            pass
    elif entity_type == "member" and entity_id:
        from members.models import Member
        try:
            member = Member.objects.get(pk=entity_id, tenant=request.user.tenant)
            prefill_data = PrefillService.prefill_from_member(form, member)
        except Member.DoesNotExist:
            pass

    # Overlay any previously saved response (idempotent resubmission)
    if entity_id:
        existing = FormService.get_existing_response(form, entity_id)
        if existing:
            prefill_data.update(existing.data)

    # ── Handle submission ─────────────────────────────────────────────────────
    errors = {}
    if request.method == "POST":
        # Draft/inactive forms must not accept responses
        if form.status != "active":
            messages.warning(request, "This form is not active and cannot accept responses.")
            return redirect("intake:form_builder_detail", form_id=form.pk)

        data = {}
        for field in fields:
            if field.field_type == "multiselect":
                data[field.field_key] = request.POST.getlist(field.field_key)
            elif field.field_type == "boolean":
                data[field.field_key] = field.field_key in request.POST
            else:
                data[field.field_key] = request.POST.get(field.field_key, "").strip()

        effective_entity_type = entity_type or "generic"
        effective_entity_id   = entity_id   or "00000000-0000-0000-0000-000000000000"

        response, errors = FormService.submit_response(
            form=form,
            entity_type=effective_entity_type,
            entity_id=effective_entity_id,
            data=data,
            submitted_by=request.user,
        )

        if not errors:
            # Redirect priority: explicit next > membership add (for members) > success
            if next_url:
                return redirect(next_url)
            if effective_entity_type == "member" and effective_entity_id != "00000000-0000-0000-0000-000000000000":
                return redirect(f"{reverse('membership_add')}?member={effective_entity_id}")
            return render(request, "intake/form_success.html", {
                "form": form, "cancel_url": cancel_url
            })

        # Validation failed — re-render with submitted data as prefill
        prefill_data = data

    return render(request, "intake/form_renderer.html", {
        "form": form,
        "fields": fields,
        "prefill_data": prefill_data,
        "errors": errors,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "next_url": next_url,
        "cancel_url": cancel_url,
        "is_preview": form.status != "active",
    })
