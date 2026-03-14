from django.contrib import admin, messages
from django import forms

from .models import Member
from crm.models import Enquiry, EnquiryActivity
from crm.admin import TenantScopedAdmin
from apps.core.models import Branch


# -------------------------------------------------
# Custom Admin Form (forces branch filtering)
# -------------------------------------------------

class MemberAdminForm(forms.ModelForm):

    class Meta:
        model = Member
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        request = kwargs.pop("request", None)

        super().__init__(*args, **kwargs)

        if request:

            # Superadmin sees all branches
            if request.user.is_superuser:
                self.fields["branches"].queryset = Branch.objects.all()

            else:
                tenant = getattr(request.user, "tenant", None)

                if tenant:
                    self.fields["branches"].queryset = Branch.objects.filter(
                        tenant=tenant
                    )
                else:
                    self.fields["branches"].queryset = Branch.objects.none()


# -------------------------------------------------
# Member Admin
# -------------------------------------------------

@admin.register(Member)
class MemberAdmin(TenantScopedAdmin):

    form = MemberAdminForm

    list_display = (
        "first_name",
        "last_name",
        "email",
        "tenant",
    )

    list_filter = ("tenant",)

    search_fields = (
        "first_name",
        "last_name",
        "email",
    )

    filter_horizontal = ("branches",)

    exclude = ("created_by",)

    # -------------------------------------------------
    # Branch filtering for filter_horizontal widget
    # -------------------------------------------------

    def formfield_for_manytomany(self, db_field, request, **kwargs):

        if db_field.name == "branches":

            if request.user.is_superuser:
                kwargs["queryset"] = Branch.objects.all()

            elif getattr(request.user, "tenant", None):
                kwargs["queryset"] = Branch.objects.filter(
                    tenant=request.user.tenant
                )

            else:
                kwargs["queryset"] = Branch.objects.none()

        return super().formfield_for_manytomany(db_field, request, **kwargs)

    # -------------------------------------------------
    # Inject request into form
    # -------------------------------------------------

    def get_form(self, request, obj=None, **kwargs):

        form = super().get_form(request, obj, **kwargs)

        class FormWithRequest(form):
            def __new__(cls, *args, **kw):
                kw["request"] = request
                return form(*args, **kw)

        return FormWithRequest

    # -------------------------------------------------
    # Prevent manual member creation
    # -------------------------------------------------

    def has_add_permission(self, request):
        return False

    # -------------------------------------------------
    # Queryset filtering
    # -------------------------------------------------

    def get_queryset(self, request):

        if request.user.is_superuser:
            return Member._base_manager.all()

        tenant = getattr(request.user, "tenant", None)

        if tenant:
            return Member._base_manager.filter(tenant=tenant)

        return Member._base_manager.none()

    # -------------------------------------------------
    # Hide tenant field for tenant users
    # -------------------------------------------------

    def get_fields(self, request, obj=None):

        fields = super().get_fields(request, obj)

        if not request.user.is_superuser:
            fields = [f for f in fields if f != "tenant"]

        return fields

    # -------------------------------------------------
    # Save member
    # -------------------------------------------------

    def save_model(self, request, obj, form, change):

        if not request.user.is_superuser:
            obj.tenant = request.user.tenant

        if not change:
            obj.created_by = request.user

        super().save_model(request, obj, form, change)

    # -------------------------------------------------
    # CRM Conversion Logic
    # -------------------------------------------------

    def save_related(self, request, form, formsets, change):

        super().save_related(request, form, formsets, change)

        enquiry_id = request.GET.get("from_enquiry")

        if enquiry_id:

            try:

                enquiry = Enquiry.objects.get(id=enquiry_id)

                if enquiry.converted_member:
                    return

                member = form.instance

                enquiry.converted_member = member
                enquiry.save(update_fields=["converted_member"])

                if enquiry.branch:
                    member.branches.add(enquiry.branch)

                EnquiryActivity.objects.create(
                    tenant=enquiry.tenant,
                    enquiry=enquiry,
                    action_type="CONVERTED",
                    performed_by=request.user,
                    new_value=f"Converted to Member ID {member.id}",
                )

                messages.success(
                    request,
                    "Member created and linked to Enquiry successfully."
                )

            except Enquiry.DoesNotExist:
                pass

    # -------------------------------------------------
    # Remove tenant column for tenant users
    # -------------------------------------------------

    def get_list_display(self, request):

        fields = list(super().get_list_display(request))

        if not request.user.is_superuser and "tenant" in fields:
            fields.remove("tenant")

        return tuple(fields)