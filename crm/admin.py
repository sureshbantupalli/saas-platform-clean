from django.contrib import admin, messages
from django.urls import path, reverse
from django.template.response import TemplateResponse
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect
from django.core.exceptions import ValidationError

from apps.core.models import Tenant

from .models import (
    LeadStage,
    EnquirySource,
    EnquiryLostReason,
    Enquiry,
    EnquiryActivity,
)

from .metrics import (
    get_crm_metrics,
    get_stale_enquiries,
    get_staff_performance,
    get_stage_funnel,
)


# ============================================================
# 🔐 GLOBAL TENANT SCOPED ADMIN
# ============================================================

class TenantScopedAdmin(admin.ModelAdmin):

    def get_queryset(self, request):
        qs = super().get_queryset(request)

        if request.user.is_superuser:
            return qs

        if hasattr(request.user, "tenant") and request.user.tenant:
            return qs.filter(tenant=request.user.tenant)

        return qs.none()

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser and not obj.pk:
            obj.tenant = request.user.tenant

        super().save_model(request, obj, form, change)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if not request.user.is_superuser:
            if hasattr(db_field.remote_field.model, "tenant"):
                kwargs["queryset"] = db_field.remote_field.model.objects.filter(
                    tenant=request.user.tenant
                )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_exclude(self, request, obj=None):
        exclude = list(super().get_exclude(request, obj) or [])

        if not request.user.is_superuser:
            if "tenant" not in exclude:
                exclude.append("tenant")

        return exclude


# ============================================================
# Lead Stage Admin
# ============================================================

@admin.register(LeadStage)
class LeadStageAdmin(TenantScopedAdmin):
    list_display = (
        "name",
        "tenant",
        "order",
        "is_conversion_stage",
        "is_loss_stage",
        "is_active",
    )
    list_filter = ("tenant", "is_active")
    ordering = ("tenant", "order")


# ============================================================
# Enquiry Source Admin
# ============================================================

@admin.register(EnquirySource)
class EnquirySourceAdmin(TenantScopedAdmin):
    list_display = ("name", "tenant", "is_active")
    list_filter = ("tenant", "is_active")


# ============================================================
# Enquiry Lost Reason Admin
# ============================================================

@admin.register(EnquiryLostReason)
class EnquiryLostReasonAdmin(TenantScopedAdmin):
    list_display = ("name", "tenant", "is_active")
    list_filter = ("tenant", "is_active")


# ============================================================
# Enquiry Admin (UPDATED SAFE VERSION)
# ============================================================

@admin.register(Enquiry)
class EnquiryAdmin(TenantScopedAdmin):

    change_list_template = "admin/crm/enquiry/change_list.html"

    list_display = (
        "full_name",
        "phone",
        "branch",
        "current_stage",
        "assigned_to",
        "next_followup_date",
        "created_at",
    )

    search_fields = ("full_name", "phone", "email")
    autocomplete_fields = ("assigned_to",)
    exclude = ("created_by",)

    def response_add(self, request, obj, post_url_continue=None):
        if "_continue" not in request.POST:
            return redirect(reverse("crm_ui:enquiry_list"))
        return super().response_add(request, obj, post_url_continue)

    def response_change(self, request, obj):
        if "_continue" not in request.POST:
            return redirect(reverse("crm_ui:enquiry_list"))
        return super().response_change(request, obj)

    # --------------------------------------------------------
    # Dynamic Display
    # --------------------------------------------------------

    def get_list_display(self, request):
        fields = list(self.list_display)

        if request.user.is_superuser:
            fields.insert(2, "tenant")

        return tuple(fields)

    def get_list_filter(self, request):
        filters = ["branch", "current_stage"]

        if request.user.is_superuser:
            filters.insert(0, "tenant")

        return filters

    # --------------------------------------------------------
    # Hide Stage During Creation
    # --------------------------------------------------------

    def get_fields(self, request, obj=None):
        fields = super().get_fields(request, obj)

        if obj is None:
            fields = [f for f in fields if f != "current_stage"]

        if not request.user.is_superuser:
            fields = [f for f in fields if f != "tenant"]

        return fields

    # --------------------------------------------------------
    # SAFE SAVE LOGIC
    # --------------------------------------------------------

    def save_model(self, request, obj, form, change):

        if not request.user.is_superuser:
            obj.tenant = request.user.tenant

        obj.created_by = request.user

        super().save_model(request, obj, form, change)

    # --------------------------------------------------------
    # 🔥 NEW SAFE CONVERSION ENDPOINT
    # --------------------------------------------------------

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<int:pk>/convert/",
                self.admin_site.admin_view(self.convert_enquiry),
                name="crm_enquiry_convert",
            ),
        ]
        return custom_urls + urls

    def convert_enquiry(self, request, pk):
        enquiry = get_object_or_404(Enquiry, pk=pk)

        # 🔒 Prevent manual access if already converted
        if enquiry.converted_member:
            messages.warning(
                request,
                "This enquiry has already been converted."
            )
            return redirect(
                reverse("admin:crm_enquiry_change", args=[pk])
            )

        # 🔒 Prevent conversion if not in conversion stage
        if not enquiry.current_stage or not enquiry.current_stage.is_conversion_stage:
            messages.error(
                request,
                "Enquiry must be in a conversion stage before converting."
            )
            return redirect(
                reverse("admin:crm_enquiry_change", args=[pk])
            )

        try:
            enquiry.convert_to_member(request.user)
            messages.success(request, "Enquiry successfully converted to Member.")
        except Exception as e:
            messages.error(request, str(e))

        return redirect(
            reverse("admin:crm_enquiry_change", args=[pk])
        )

    # --------------------------------------------------------
    # Show Convert Button Only If Eligible
    # --------------------------------------------------------

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}

        enquiry = Enquiry.objects.filter(pk=object_id).first()

        if (
            enquiry
            and not enquiry.converted_member
            and enquiry.current_stage
            and enquiry.current_stage.is_conversion_stage
        ):
            extra_context["show_convert_button"] = True

        return super().change_view(request, object_id, form_url, extra_context)

    # --------------------------------------------------------
    # Lock After Conversion
    # --------------------------------------------------------

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))

        if obj and obj.converted_member:
            readonly.extend(
                field.name for field in self.model._meta.fields
            )

        return list(set(readonly))

    # --------------------------------------------------------
    # Superadmin Visibility
    # --------------------------------------------------------

    def get_queryset(self, request):
        if request.user.is_superuser:
            return Enquiry._base_manager.all()
        return super().get_queryset(request)

    # --------------------------------------------------------
    # KPI Dashboard Metrics
    # --------------------------------------------------------

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}

        response = super().changelist_view(request, extra_context=extra_context)

        if not hasattr(response, "context_data"):
            return response

        cl = response.context_data.get("cl")
        queryset = cl.queryset if cl else self.model.objects.none()

        total = queryset.count()
        converted = queryset.filter(
            converted_member__isnull=False
        ).count()
        lost = queryset.filter(
            current_stage__is_loss_stage=True
        ).count()

        conversion_rate = round((converted / total) * 100, 2) if total else 0

        response.context_data.update({
            "total_enquiries": total,
            "converted_count": converted,
            "lost_count": lost,
            "conversion_rate": conversion_rate,
        })

        return response


# ============================================================
# Enquiry Activity Admin
# ============================================================

@admin.register(EnquiryActivity)
class EnquiryActivityAdmin(TenantScopedAdmin):
    list_display = (
        "enquiry",
        "action_type",
        "performed_by",
        "created_at",
    )
    list_filter = ("action_type", "tenant")
    search_fields = ("enquiry__full_name", "enquiry__phone")


# ============================================================
# CRM Dashboard View
# ============================================================

def crm_dashboard_view(request):
    tenant_id = request.GET.get("tenant_id")

    if tenant_id:
        tenant = Tenant.objects.filter(id=tenant_id).first()
    else:
        tenant = Tenant.objects.first()

    metrics = get_crm_metrics(tenant) if tenant else {}
    stale_enquiries = get_stale_enquiries(tenant) if tenant else []
    staff_performance = get_staff_performance(tenant) if tenant else []
    funnel = get_stage_funnel(tenant) if tenant else []

    enquiry_changelist_url = reverse("admin:crm_enquiry_changelist")

    context = {
        **admin.site.each_context(request),
        "metrics": metrics,
        "tenant": tenant,
        "tenants": Tenant.objects.all(),
        "stale_enquiries": stale_enquiries,
        "staff_performance": staff_performance,
        "funnel": funnel,
        "enquiry_changelist_url": enquiry_changelist_url,
    }

    return TemplateResponse(
        request,
        "admin/crm_dashboard.html",
        context,
    )


def get_admin_urls(original_get_urls):
    def get_urls():
        urls = [
            path(
                "crm/dashboard/",
                admin.site.admin_view(crm_dashboard_view),
                name="crm_dashboard",
            ),
        ]
        return urls + original_get_urls()
    return get_urls


admin.site.get_urls = get_admin_urls(admin.site.get_urls)