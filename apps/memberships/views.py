from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import IsAuthenticated
from django.db.models import Prefetch

from django.views.generic import CreateView
from django.urls import reverse
from django.shortcuts import get_object_or_404
from django import forms

from .models import Membership
from .serializers import MembershipSerializer

from members.models import Member


# ==============================================
# Membership API (DRF)
# ==============================================

class MembershipViewSet(ModelViewSet):
    """
    API endpoint for managing memberships.
    """

    serializer_class = MembershipSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user

        queryset = Membership.base_objects.select_related(
            "member",
            "branch",
            "plan",
            "tenant",
            "created_by"
        )

        # Platform Admin → Full access
        if user.is_platform_admin:
            return queryset

        # Tenant Restricted Users
        return queryset.filter(
            tenant=user.tenant
        )

    def perform_create(self, serializer):
        serializer.save(
            created_by=self.request.user,
            tenant=self.request.user.tenant
        )


# ==============================================
# Membership HTML Form
# ==============================================

class MembershipForm(forms.ModelForm):
    """
    Custom form so we can enable HTML5 date pickers
    """

    class Meta:
        model = Membership
        fields = [
            "plan",
            "branch",
            "start_date",
            "end_date",
            "status"
        ]

        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }


# ==============================================
# Membership Create View
# ==============================================

class MembershipCreateView(CreateView):

    model = Membership
    form_class = MembershipForm

    template_name = "memberships/membership_form.html"

    def dispatch(self, request, *args, **kwargs):

        self.member = get_object_or_404(
            Member,
            id=request.GET.get("member")
        )

        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):

        form.instance.member = self.member
        form.instance.tenant = self.request.user.tenant
        form.instance.created_by = self.request.user   # ⭐ important audit tracking

        return super().form_valid(form)

    def get_success_url(self):

        return reverse(
            "members:member_detail",
            args=[self.member.id]
        )