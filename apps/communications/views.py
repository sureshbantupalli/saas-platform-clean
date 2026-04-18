import json

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import Channel, CommunicationLog, MessageTemplate, TriggerRule


# ── Forms ─────────────────────────────────────────────────────────────────────

class MessageTemplateForm(forms.ModelForm):
    class Meta:
        model  = MessageTemplate
        fields = ["name", "channel", "subject", "content", "variables", "is_active"]
        widgets = {
            "content":   forms.Textarea(attrs={"rows": 6}),
            "variables": forms.Textarea(attrs={"rows": 3}),
        }
        help_texts = {
            "content":   "Use {{variable_name}} placeholders, e.g. {{member_name}}, {{amount}}.",
            "variables": "Optional JSON documenting available variables, e.g. {\"member_name\": \"Member full name\"}.",
            "subject":   "Email only — leave blank for SMS/WhatsApp.",
        }

    def clean_variables(self):
        raw = self.cleaned_data.get("variables")
        if raw is None:
            return {}
        if isinstance(raw, dict):
            return raw
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            raise forms.ValidationError("Must be valid JSON, e.g. {}.")


class TriggerRuleForm(forms.Form):
    event_name  = forms.CharField(
        max_length=100,
        help_text='System event name, e.g. "payment_success", "booking_confirmed".',
    )
    template    = forms.ModelChoiceField(queryset=MessageTemplate.base_objects.none())
    conditions  = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 4}),
        required=False,
        initial="{}",
        help_text='Optional JSON. Example: {"amount": {">": 1000}, "payment_method": {"==": "online"}}',
    )
    is_active   = forms.BooleanField(required=False, initial=True)

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        if tenant:
            self.fields["template"].queryset = MessageTemplate.base_objects.filter(
                tenant=tenant, is_active=True
            ).order_by("name")

    def clean_conditions(self):
        raw = self.cleaned_data.get("conditions", "").strip() or "{}"
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise forms.ValidationError(f"Invalid JSON: {exc}")
        if not isinstance(parsed, dict):
            raise forms.ValidationError("Conditions must be a JSON object.")
        return parsed


# ── MessageTemplate CRUD ──────────────────────────────────────────────────────

@login_required
def template_list(request):
    templates = MessageTemplate.base_objects.filter(
        tenant=request.user.tenant, is_deleted=False
    ).order_by("name")
    return render(request, "communications/template_list.html", {"templates": templates})


@login_required
def template_create(request):
    if request.method == "POST":
        form = MessageTemplateForm(request.POST)
        if form.is_valid():
            tpl = form.save(commit=False)
            tpl.tenant = request.user.tenant
            tpl.save()
            messages.success(request, f'Template "{tpl.name}" created.')
            return redirect("communications:template_list")
    else:
        form = MessageTemplateForm()
    return render(request, "communications/template_form.html", {"form": form, "action": "Create"})


@login_required
def template_edit(request, pk):
    tpl = get_object_or_404(
        MessageTemplate.base_objects, pk=pk, tenant=request.user.tenant, is_deleted=False
    )
    if request.method == "POST":
        form = MessageTemplateForm(request.POST, instance=tpl)
        if form.is_valid():
            form.save()
            messages.success(request, f'Template "{tpl.name}" updated.')
            return redirect("communications:template_list")
    else:
        form = MessageTemplateForm(instance=tpl)
    return render(request, "communications/template_form.html", {
        "form": form, "action": "Edit", "object": tpl,
    })


@login_required
@require_POST
def template_toggle(request, pk):
    tpl = get_object_or_404(
        MessageTemplate.base_objects, pk=pk, tenant=request.user.tenant, is_deleted=False
    )
    tpl.is_active = not tpl.is_active
    tpl.save(update_fields=["is_active", "updated_at"])
    state = "activated" if tpl.is_active else "deactivated"
    messages.success(request, f'Template "{tpl.name}" {state}.')
    return redirect("communications:template_list")


# ── TriggerRule CRUD ──────────────────────────────────────────────────────────

@login_required
def trigger_list(request):
    rules = TriggerRule.base_objects.filter(
        tenant=request.user.tenant, is_deleted=False
    ).select_related("template").order_by("event_name")
    return render(request, "communications/trigger_list.html", {"rules": rules})


@login_required
def trigger_create(request):
    tenant = request.user.tenant
    if request.method == "POST":
        form = TriggerRuleForm(request.POST, tenant=tenant)
        if form.is_valid():
            d = form.cleaned_data
            rule = TriggerRule(
                tenant     = tenant,
                event_name = d["event_name"],
                template   = d["template"],
                conditions = d["conditions"],
                is_active  = d["is_active"],
            )
            rule.save()
            messages.success(request, f'Trigger rule for "{rule.event_name}" created.')
            return redirect("communications:trigger_list")
    else:
        form = TriggerRuleForm(tenant=tenant)
    return render(request, "communications/trigger_form.html", {"form": form, "action": "Create"})


@login_required
def trigger_edit(request, pk):
    tenant = request.user.tenant
    rule = get_object_or_404(
        TriggerRule.base_objects, pk=pk, tenant=tenant, is_deleted=False
    )
    if request.method == "POST":
        form = TriggerRuleForm(request.POST, tenant=tenant)
        if form.is_valid():
            d = form.cleaned_data
            rule.event_name = d["event_name"]
            rule.template   = d["template"]
            rule.conditions = d["conditions"]
            rule.is_active  = d["is_active"]
            rule.save()
            messages.success(request, f'Trigger rule for "{rule.event_name}" updated.')
            return redirect("communications:trigger_list")
    else:
        initial = {
            "event_name": rule.event_name,
            "template":   rule.template,
            "conditions": json.dumps(rule.conditions or {}, indent=2),
            "is_active":  rule.is_active,
        }
        form = TriggerRuleForm(initial=initial, tenant=tenant)
    return render(request, "communications/trigger_form.html", {
        "form": form, "action": "Edit", "object": rule,
    })


@login_required
@require_POST
def trigger_toggle(request, pk):
    rule = get_object_or_404(
        TriggerRule.base_objects, pk=pk, tenant=request.user.tenant, is_deleted=False
    )
    rule.is_active = not rule.is_active
    rule.save(update_fields=["is_active", "updated_at"])
    state = "activated" if rule.is_active else "deactivated"
    messages.success(request, f'Trigger rule for "{rule.event_name}" {state}.')
    return redirect("communications:trigger_list")


# ── Communication Logs ────────────────────────────────────────────────────────

@login_required
def log_list(request):
    logs = CommunicationLog.base_objects.filter(
        tenant=request.user.tenant, is_deleted=False
    ).order_by("-created_at")[:200]

    channel_filter = request.GET.get("channel")
    status_filter  = request.GET.get("status")

    qs = CommunicationLog.base_objects.filter(
        tenant=request.user.tenant, is_deleted=False
    )
    if channel_filter:
        qs = qs.filter(channel=channel_filter)
    if status_filter:
        qs = qs.filter(status=status_filter)
    logs = qs.order_by("-created_at")[:200]

    from .models import MessageStatus
    return render(request, "communications/log_list.html", {
        "logs":            logs,
        "channel_choices": Channel.choices,
        "status_choices":  MessageStatus.choices,
        "channel_filter":  channel_filter,
        "status_filter":   status_filter,
    })
