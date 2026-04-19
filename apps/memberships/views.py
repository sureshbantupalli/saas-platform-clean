from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import IsAuthenticated

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views.generic import CreateView, UpdateView
from django.urls import reverse, reverse_lazy
from django.shortcuts import get_object_or_404, redirect, render
from django import forms

from .models import Membership, MembershipPlan
from .serializers import MembershipSerializer

from members.models import Member
from apps.core.models import Branch
from apps.core.permissions import require_permission


# ==============================================
# Membership API (DRF)
# ==============================================

class MembershipViewSet(ModelViewSet):

    serializer_class = MembershipSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user

        queryset = Membership.base_objects.select_related(
            "member", "branch", "plan", "tenant", "created_by"
        )

        if user.is_platform_admin:
            return queryset

        return queryset.filter(tenant=user.tenant)

    def perform_create(self, serializer):
        serializer.save(
            created_by=self.request.user,
            tenant=self.request.user.tenant
        )


# ==============================================
# Membership HTML Forms
# ==============================================

class MembershipForm(forms.ModelForm):

    class Meta:
        model = Membership
        fields = ["plan", "branch", "start_date", "discount_type", "discount_value"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)

        if tenant:
            self.fields["branch"].queryset = Branch.base_objects.filter(
                tenant=tenant, is_active=True, is_deleted=False
            )
            self.fields["plan"].queryset = MembershipPlan.base_objects.filter(
                tenant=tenant, is_active=True
            )
        else:
            self.fields["branch"].queryset = Branch.objects.none()
            self.fields["plan"].queryset = MembershipPlan.objects.none()

        self.fields["discount_value"].required = False
        self.fields["discount_value"].initial = 0

        for field in self.fields.values():
            if not isinstance(field.widget, forms.DateInput):
                field.widget.attrs.setdefault("class", "form-control")


class MembershipFormWithMember(MembershipForm):
    """Form variant that includes a member selector (for standalone use)."""

    member = forms.ModelChoiceField(
        queryset=Member.objects.none(),
        required=True,
        empty_label="-- Select Member --",
    )

    class Meta(MembershipForm.Meta):
        fields = ["member"] + MembershipForm.Meta.fields  # type: ignore[assignment]

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, tenant=tenant, **kwargs)

        if tenant:
            self.fields["member"].queryset = Member.objects.filter(
                tenant=tenant, is_deleted=False
            ).order_by("first_name", "last_name")  # Member uses plain Manager, no TenantManager

        self.fields["member"].widget.attrs["class"] = "form-select"


# ==============================================
# Membership Create View
# ==============================================

@method_decorator(login_required, name="dispatch")
class MembershipCreateView(CreateView):

    model = Membership
    template_name = "memberships/membership_form.html"

    def dispatch(self, request, *args, **kwargs):
        member_id = request.GET.get("member")

        if member_id:
            self.member = get_object_or_404(
                Member,
                id=member_id,
                tenant=request.user.tenant
            )
        else:
            self.member = None

        return super().dispatch(request, *args, **kwargs)

    def get_form_class(self):
        if self.member is None:
            return MembershipFormWithMember
        return MembershipForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["tenant"] = self.request.user.tenant
        return kwargs

    def form_valid(self, form):
        if self.member:
            form.instance.member = self.member
        form.instance.tenant = self.request.user.tenant
        form.instance.created_by = self.request.user
        return super().form_valid(form)

    def get_success_url(self):
        membership = self.object
        member     = self.member or membership.member
        # Redirect to payment_create pre-filled with membership context.
        # Admin can record full or partial payment.
        base = reverse("payments:payment_create")
        return (
            f"{base}"
            f"?reference_type=membership"
            f"&reference_id={membership.pk}"
            f"&amount={membership.fee_amount}"
            f"&member_id={member.pk}"
            f"&purpose=membership"
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["member"] = self.member
        return ctx


# ==============================================
# Membership Plan Form
# ==============================================

class MembershipPlanForm(forms.ModelForm):

    class Meta:
        model = MembershipPlan
        fields = [
            "name",
            "branch",
            "plan_type",
            "price",
            "billing_cycle_type",
            "billing_interval",
            "class_count",
            "description",
            "allow_custom_dates",
            "auto_renew_default",
            "is_active",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)

        if tenant:
            self.fields["branch"].queryset = Branch.base_objects.filter(
                tenant=tenant, is_active=True, is_deleted=False
            )
        else:
            self.fields["branch"].queryset = Branch.objects.none()

        for name, field in self.fields.items():
            if name in ("allow_custom_dates", "auto_renew_default", "is_active"):
                field.widget.attrs.setdefault("class", "form-check-input")
            elif not isinstance(field.widget, forms.Textarea):
                field.widget.attrs.setdefault("class", "form-control")

        self.fields["class_count"].required = False
        self.fields["class_count"].help_text = "Number of sessions included (Class Pack only)"

    def clean(self):
        cleaned = super().clean()
        plan_type = cleaned.get("plan_type")
        class_count = cleaned.get("class_count")

        if plan_type == "CLASS_PACK" and not class_count:
            self.add_error("class_count", "Class count is required for Class Pack plans.")

        return cleaned


# ==============================================
# Membership Plan Views
# ==============================================

@login_required
def membership_detail(request, pk):
    """Financial breakdown for a single membership."""
    membership = get_object_or_404(
        Membership.base_objects, pk=pk, tenant=request.user.tenant
    )
    from apps.payments.models import Payment
    payments = Payment.base_objects.filter(
        reference_type="membership",
        reference_id=membership.pk,
        is_deleted=False,
    ).order_by("-created_at")
    return render(request, "memberships/membership_detail.html", {
        "membership": membership,
        "payments": payments,
    })


@login_required
def plan_list(request):
    tenant = request.user.tenant

    plans = MembershipPlan.base_objects.filter(
        tenant=tenant
    ).select_related("branch").order_by("branch__name", "name")

    branch_filter = request.GET.get("branch", "")
    active_filter = request.GET.get("active", "")

    if branch_filter:
        plans = plans.filter(branch_id=branch_filter)

    if active_filter == "1":
        plans = plans.filter(is_active=True)
    elif active_filter == "0":
        plans = plans.filter(is_active=False)

    branches = Branch.objects.filter(tenant=tenant, is_active=True, is_deleted=False)

    context = {
        "plans": plans,
        "branches": branches,
        "branch_filter": branch_filter,
        "active_filter": active_filter,
    }
    return render(request, "memberships/plan_list.html", context)


@login_required
def plan_create(request):
    tenant = request.user.tenant

    if request.method == "POST":
        form = MembershipPlanForm(request.POST, tenant=tenant)
        if form.is_valid():
            plan = form.save(commit=False)
            plan.tenant = tenant
            plan.save()
            messages.success(request, f'Plan "{plan.name}" created successfully.')
            return redirect("plan_list")
    else:
        form = MembershipPlanForm(tenant=tenant)

    return render(request, "memberships/plan_form.html", {"form": form, "action": "Create"})


@login_required
def plan_edit(request, pk):
    tenant = request.user.tenant
    plan = get_object_or_404(MembershipPlan.base_objects, pk=pk, tenant=tenant)

    if request.method == "POST":
        form = MembershipPlanForm(request.POST, instance=plan, tenant=tenant)
        if form.is_valid():
            form.save()
            messages.success(request, f'Plan "{plan.name}" updated successfully.')
            return redirect("plan_list")
    else:
        form = MembershipPlanForm(instance=plan, tenant=tenant)

    return render(request, "memberships/plan_form.html", {"form": form, "plan": plan, "action": "Edit"})


@login_required
def plan_toggle_active(request, pk):
    tenant = request.user.tenant
    plan = get_object_or_404(MembershipPlan.base_objects, pk=pk, tenant=tenant)

    if request.method == "POST":
        plan.is_active = not plan.is_active
        # bypass full_clean to avoid re-validating unchanged data
        MembershipPlan.base_objects.filter(pk=plan.pk).update(is_active=plan.is_active)
        state = "activated" if plan.is_active else "deactivated"
        messages.success(request, f'Plan "{plan.name}" {state}.')

    return redirect("plan_list")
