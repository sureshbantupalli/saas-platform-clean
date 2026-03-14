from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import View
from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponseForbidden
from django.db.models import Count

from apps.accounts.models import User
from crm.models import Enquiry

# Adjust Tenant import if needed

try:
    from apps.core.models import Tenant
except ImportError:
    from members.models import Tenant

class PlatformDashboardView(LoginRequiredMixin, View):


    template_name = "platform/dashboard/dashboard.html"

    def get(self, request):

        if not getattr(request.user, "is_platform_admin", False):
            return HttpResponseForbidden("Tenant users cannot access platform control.")

        total_tenants = Tenant.objects.count()
        total_users = User.objects.count()
        total_enquiries = Enquiry.objects.count()
        converted = Enquiry.objects.filter(current_stage__name="Converted").count()

        conversion_rate = 0
        if total_enquiries > 0:
            conversion_rate = round((converted / total_enquiries) * 100, 2)

        context = {
            "total_tenants": total_tenants,
            "total_users": total_users,
            "total_enquiries": total_enquiries,
            "conversion_rate": conversion_rate,
        }

        return render(request, self.template_name, context)


class TenantListView(LoginRequiredMixin, View):

    template_name = "platform/tenant_list.html"

    def get(self, request):

        if not getattr(request.user, "is_platform_admin", False):
            return HttpResponseForbidden("Tenant users cannot access platform control.")

        tenants = (
            Tenant.objects
            .annotate(user_count=Count("users"))
            .annotate(enquiry_count=Count("enquiries"))
        )

        context = {
            "tenants": tenants
        }

        return render(request, self.template_name, context)


class ToggleTenantStatusView(LoginRequiredMixin, View):


    def post(self, request, tenant_id):

        if not getattr(request.user, "is_platform_admin", False):
            return HttpResponseForbidden("Tenant users cannot access platform control.")

        tenant = get_object_or_404(Tenant, id=tenant_id)
        tenant.is_active = not tenant.is_active
        tenant.save()

        return redirect("platform:tenants")