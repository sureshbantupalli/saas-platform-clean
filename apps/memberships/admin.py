from django import forms
from django.contrib import admin
from .models import Membership, MembershipPlan, MembershipAdjustment


# ==========================================
# Tenant-Aware Membership Admin Form
# ==========================================

class MembershipAdminForm(forms.ModelForm):

    class Meta:
        model = Membership
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Default: show no plans until tenant is known
        self.fields["plan"].queryset = MembershipPlan.objects.none()

        # CASE 1: Editing existing membership
        if self.instance.pk and self.instance.tenant_id:
            self.fields["plan"].queryset = MembershipPlan.objects.filter(
                tenant_id=self.instance.tenant_id
            )

        # CASE 2: Adding new membership (tenant selected in form POST)
        elif "tenant" in self.data:
            try:
                tenant_id = self.data.get("tenant")
                self.fields["plan"].queryset = MembershipPlan.objects.filter(
                    tenant_id=tenant_id
                )
            except (ValueError, TypeError):
                pass


# ==========================================
# Adjustment Inline
# ==========================================

class MembershipAdjustmentInline(admin.TabularInline):
    model = MembershipAdjustment
    extra = 0
    readonly_fields = ("created_by", "created_at")
    fields = (
        "adjustment_type",
        "days",
        "remarks",
        "created_by",
        "created_at",
    )


# ==========================================
# Membership Admin
# ==========================================

@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    form = MembershipAdminForm

    # -------------------------
    # Formatted Dates
    # -------------------------

    def formatted_end_date(self, obj):
        return obj.end_date.strftime("%Y-%m-%d") if obj.end_date else "-"
    formatted_end_date.short_description = "End Date"

    def formatted_final_end_date(self, obj):
        return obj.final_end_date.strftime("%Y-%m-%d") if obj.final_end_date else "-"
    formatted_final_end_date.short_description = "Final End Date"

    list_display = (
        "member",
        "branch",
        "plan",
        "status",
        "start_date",
        "formatted_end_date",
        "formatted_final_end_date",
    )

    inlines = [MembershipAdjustmentInline]

    # -------------------------
    # Hide created_by from form
    # -------------------------

    def get_exclude(self, request, obj=None):
        return ("created_by",)

    # -------------------------
    # Readonly Handling
    # -------------------------

    def get_readonly_fields(self, request, obj=None):
        readonly = [
            "formatted_end_date",
            "base_amount",
            "fee_amount",
            "formatted_final_end_date",
        ]

        # 🔒 Lock tenant after creation
        if obj:
            readonly.append("tenant")

        return readonly

    # -------------------------
    # Save Handling
    # -------------------------

    def save_model(self, request, obj, form, change):
        # Auto-assign logged-in user
        if not obj.created_by:
            obj.created_by = request.user

        super().save_model(request, obj, form, change)

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)

        for obj in instances:
            if not obj.created_by:
                obj.created_by = request.user

            if not obj.tenant_id:
                obj.tenant = form.instance.tenant

            obj.save()

        formset.save_m2m()


# ==========================================
# Membership Plan Admin
# ==========================================

@admin.register(MembershipPlan)
class MembershipPlanAdmin(admin.ModelAdmin):

    list_display = (
        "name",
        "branch",
        "price",
        "billing_cycle_type",
        "billing_interval",
        "is_active",
    )

    list_filter = (
        "branch",
        "billing_cycle_type",
        "is_active",
    )

    search_fields = ("name",)