from django.db.models import Count, Q
from django.views.generic import TemplateView, ListView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth import get_user_model
from .models import Enquiry
from django.shortcuts import redirect, get_object_or_404
from django.urls import reverse
from django.views import View



# ============================================================
# CRM DASHBOARD VIEW
# ============================================================

class CRMdashboardView(LoginRequiredMixin, TemplateView):
    template_name = "crm/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        user = self.request.user
        qs = Enquiry.objects.all()

        # Tenant isolation
        if not user.is_superuser and hasattr(user, "tenant"):
            qs = qs.filter(tenant=user.tenant)

        # =========================
        # KPI METRICS
        # =========================
        total_enquiries = qs.count()
        converted_count = qs.filter(converted_member__isnull=False).count()
        new_count = qs.filter(converted_member__isnull=True).count()

        conversion_rate = 0
        if total_enquiries > 0:
            conversion_rate = round((converted_count / total_enquiries) * 100, 2)

        # =========================
        # FUNNEL DATA
        # =========================
        stage_counts = [
            {
                "label": "New",
                "count": new_count,
                "percentage": round((new_count / total_enquiries) * 100, 2)
                if total_enquiries > 0 else 0,
            },
            {
                "label": "Converted",
                "count": converted_count,
                "percentage": round((converted_count / total_enquiries) * 100, 2)
                if total_enquiries > 0 else 0,
            },
        ]

        # =========================
        # RECENT ENQUIRIES
        # =========================
        recent_enquiries = qs.order_by("-created_at")[:5]

        # =========================
        # STAFF PERFORMANCE
        # =========================
        staff_stats = (
            qs.filter(assigned_to__isnull=False)
            .values("assigned_to__id", "assigned_to__email")
            .annotate(
                total_assigned=Count("id"),
                converted_assigned=Count(
                    "id",
                    filter=Q(converted_member__isnull=False)
                ),
            )
        )

        staff_performance = []

        for staff in staff_stats:
            total_assigned = staff["total_assigned"]
            converted_assigned = staff["converted_assigned"]

            conversion_percent = 0
            if total_assigned > 0:
                conversion_percent = round(
                    (converted_assigned / total_assigned) * 100, 2
                )

            staff_performance.append({
                "display": staff["assigned_to__email"],
                "total": total_assigned,
                "converted": converted_assigned,
                "conversion_rate": conversion_percent,
            })

        context.update({
            "total_enquiries": total_enquiries,
            "new_count": new_count,
            "converted_count": converted_count,
            "conversion_rate": conversion_rate,
            "stage_counts": stage_counts,
            "recent_enquiries": recent_enquiries,
            "staff_performance": staff_performance,
        })

        return context


# ============================================================
# ENQUIRY LIST VIEW
# ============================================================

class EnquiryListView(LoginRequiredMixin, ListView):
    model = Enquiry
    template_name = "crm/enquiry_list.html"
    context_object_name = "enquiries"
    paginate_by = 10

    def get_queryset(self):
        user = self.request.user
        qs = Enquiry.objects.all()

        # Tenant isolation
        if not user.is_superuser and hasattr(user, "tenant"):
            qs = qs.filter(tenant=user.tenant)

        # Stage filtering
        stage = self.request.GET.get("stage")
        if stage == "converted":
            qs = qs.filter(converted_member__isnull=False)
        elif stage == "new":
            qs = qs.filter(converted_member__isnull=True)

        # Assigned filter
        assigned = self.request.GET.get("assigned")
        if assigned:
            qs = qs.filter(assigned_to__id=assigned)

        # Search
        search = self.request.GET.get("search")
        if search:
            qs = qs.filter(full_name__icontains=search)

        return qs.order_by("-created_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["selected_stage"] = self.request.GET.get("stage", "")
        context["search_query"] = self.request.GET.get("search", "")

        # Provide staff list for filter dropdown

        User = get_user_model()

        print("==== DEBUG STAFF USERS ====")
        print("Current User:", self.request.user.email)
        print("Current Tenant:", self.request.user.tenant)
        print("Platform Admin:", self.request.user.is_platform_admin)

        all_users = User.objects.all()
        print("All Users:", list(all_users.values("email", "tenant_id", "role_id")))

        staff_role_users = User.objects.filter(role__name__icontains="staff")
        print("Role Filter Users:", list(staff_role_users.values("email")))

        tenant_filtered = User.objects.filter(
            tenant=self.request.user.tenant,
            role__name__icontains="staff"
        )
        print("Tenant + Role Users:", list(tenant_filtered.values("email")))


        if self.request.user.is_platform_admin:
            staff_users = User.objects.filter(
                role__name__icontains="staff"
            )
        else:
            staff_users = User.objects.filter(
                tenant=self.request.user.tenant,
                role__name__icontains="staff"
            )

        context["staff_users"] = staff_users

        return context


# ============================================================
# ENQUIRY DETAIL VIEW
# ============================================================

class EnquiryDetailView(LoginRequiredMixin, DetailView):
    model = Enquiry
    template_name = "crm/enquiry_detail.html"
    context_object_name = "enquiry"

    def get_queryset(self):
        user = self.request.user
        qs = Enquiry.objects.all()

        # Tenant isolation
        if not user.is_superuser and hasattr(user, "tenant"):
            qs = qs.filter(tenant=user.tenant)

        return qs

class AssignEnquiryView(LoginRequiredMixin, View):

    def post(self, request, pk):
        enquiry = get_object_or_404(Enquiry, pk=pk)

        # Tenant protection
        if not request.user.is_superuser and hasattr(request.user, "tenant"):
            if enquiry.tenant != request.user.tenant:
                return redirect("crm_ui:enquiry_list")

        user_id = request.POST.get("assigned_to")

        if user_id:
            User = get_user_model()
            assigned_user = User.objects.filter(id=user_id).first()

            # Ensure same tenant
            if assigned_user:
                if request.user.is_superuser or (
                    hasattr(assigned_user, "tenant")
                    and assigned_user.tenant == enquiry.tenant
                ):
                    enquiry.assigned_to = assigned_user
                    enquiry.save()

        return redirect(reverse("crm_ui:enquiry_list"))