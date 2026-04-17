from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import IsAuthenticated
from django.db.models import Prefetch

from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views.generic import CreateView
from django.urls import reverse
from django.shortcuts import get_object_or_404
from django import forms

from .models import Membership, MembershipPlan
from .serializers import MembershipSerializer

from members.models import Member
from apps.core.models import Branch


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
        fields = ["plan", "branch", "start_date", "end_date", "status"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "end_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)

        if tenant:
            self.fields["branch"].queryset = Branch.objects.filter(
                tenant=tenant, is_active=True, is_deleted=False
            )
            self.fields["plan"].queryset = MembershipPlan.objects.filter(
                tenant=tenant, is_active=True
            )
        else:
            self.fields["branch"].queryset = Branch.objects.none()
            self.fields["plan"].queryset = MembershipPlan.objects.none()

        # end_date is auto-calculated by model.save() from the plan; not required from user
        self.fields["end_date"].required = False

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
        fields = ["member"] + MembershipForm.Meta.fields

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, tenant=tenant, **kwargs)

        if tenant:
            self.fields["member"].queryset = Member.objects.filter(
                tenant=tenant, is_deleted=False
            ).order_by("first_name", "last_name")

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
        member = self.member or self.object.member
        return reverse("members:member_detail", args=[member.id])

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["member"] = self.member
        return ctx
