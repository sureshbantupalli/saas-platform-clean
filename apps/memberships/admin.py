from django.contrib import admin
from django import forms

from .models import Membership, MembershipPlan, MembershipAdjustment
from apps.core.models import Branch
from apps.core.admin_base import PlatformAdminMixin


# =========================================================
# Membership Admin Form
# =========================================================

class MembershipAdminForm(forms.ModelForm):

    class Meta:
        model = Membership
        fields = "__all__"

    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)

        # -------------------------------------------------
        # Always show all branches in admin (platform tool)
        # -------------------------------------------------

        self.fields["branch"].queryset = Branch.base_objects.all()

        # -------------------------------------------------
        # Default: show all active plans
        # -------------------------------------------------

        self.fields["plan"].queryset = MembershipPlan.base_objects.filter(
            is_active=True
        )

        branch_id = None

        # -------------------------------------------------
        # Case 1 — Editing existing membership
        # -------------------------------------------------

        if self.instance.pk and self.instance.branch_id:
            branch_id = self.instance.branch_id

        # -------------------------------------------------
        # Case 2 — Branch selected in form
        # -------------------------------------------------

        elif "branch" in self.data:
            try:
                branch_id = self.data.get("branch")
            except (ValueError, TypeError):
                pass

        # -------------------------------------------------
        # Filter plans by branch
        # -------------------------------------------------

        if branch_id:
            self.fields["plan"].queryset = MembershipPlan.base_objects.filter(
                branch_id=branch_id,
                is_active=True
            )


# =========================================================
# Adjustment Inline
# =========================================================

class MembershipAdjustmentInline(admin.TabularInline):

    model = MembershipAdjustment
    extra = 0

    readonly_fields = (
        "created_by",
        "created_at",
    )

    fields = (
        "adjustment_type",
        "days",
        "remarks",
        "created_by",
        "created_at",
    )


# =========================================================
# Membership Admin
# =========================================================

@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):

    form = MembershipAdminForm

    exclude = (
        "created_by",
        "plan_name",
    )

    list_display = (
        "member",
        "branch",
        "plan",
        "status",
        "start_date",
        "formatted_end_date",
        "formatted_final_end_date",
        "fee_amount",
    )

    list_filter = (
        "status",
        "branch",
    )

    search_fields = (
        "member__first_name",
        "member__last_name",
        "plan_name",
    )

    inlines = [MembershipAdjustmentInline]

    # -----------------------------------------------------
    # Readonly calculated fields
    # -----------------------------------------------------

    def get_readonly_fields(self, request, obj=None):

        readonly = [
            "end_date",
            "base_amount",
            "fee_amount",
            "formatted_end_date",
            "formatted_final_end_date",
        ]

        if obj:
            readonly.append("tenant")

        return readonly

    # -----------------------------------------------------
    # Display calculated end date
    # -----------------------------------------------------

    def formatted_end_date(self, obj):
        return obj.end_date.strftime("%Y-%m-%d") if obj.end_date else "-"

    formatted_end_date.short_description = "End Date"

    # -----------------------------------------------------
    # Display final expiry date
    # -----------------------------------------------------

    def formatted_final_end_date(self, obj):
        return obj.final_end_date.strftime("%Y-%m-%d") if obj.final_end_date else "-"

    formatted_final_end_date.short_description = "Final End Date"

    # -----------------------------------------------------
    # Save logic
    # -----------------------------------------------------

    def save_model(self, request, obj, form, change):

        if not obj.created_by:
            obj.created_by = request.user

        if obj.branch:
            obj.tenant = obj.branch.tenant

        # Snapshot plan name (important for historical tracking)
        if obj.plan:
            obj.plan_name = obj.plan.name

        super().save_model(request, obj, form, change)

    # -----------------------------------------------------
    # Save inline adjustments
    # -----------------------------------------------------

    def save_formset(self, request, form, formset, change):

        instances = formset.save(commit=False)

        for obj in instances:

            if not obj.created_by:
                obj.created_by = request.user

            if not obj.tenant_id and form.instance.branch:
                obj.tenant = form.instance.branch.tenant

            obj.save()

        formset.save_m2m()


# =========================================================
# Membership Plan Admin
# =========================================================

@admin.register(MembershipPlan)
class MembershipPlanAdmin(PlatformAdminMixin):

    model = MembershipPlan

    exclude = ("tenant",)

    list_display = (
        "name",
        "branch",
        "plan_type",
        "price",
        "billing_cycle_type",
        "billing_interval",
        "is_template",
        "is_active",
    )

    list_filter = (
        "branch",
        "plan_type",
        "billing_cycle_type",
        "is_template",
        "is_active",
    )

    search_fields = ("name",)

    # ------------------------------------------------
    # Filter branch dropdown
    # ------------------------------------------------

    def formfield_for_foreignkey(self, db_field, request, **kwargs):

        if db_field.name == "branch":

            if request.user.is_superuser or getattr(request.user, "is_platform_admin", False):
                kwargs["queryset"] = Branch.base_objects.all()

            elif getattr(request.user, "tenant", None):
                kwargs["queryset"] = Branch.base_objects.filter(
                    tenant=request.user.tenant
                )

            else:
                kwargs["queryset"] = Branch.base_objects.none()

        return super().formfield_for_foreignkey(db_field, request, **kwargs)