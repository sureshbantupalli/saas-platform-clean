from django.contrib import admin, messages
from .models import Member
from crm.models import Enquiry, EnquiryActivity
from crm.admin import TenantScopedAdmin


@admin.register(Member)
class MemberAdmin(TenantScopedAdmin):
    list_display = (
        "first_name",
        "last_name",
        "email",
        "tenant",
    )
    list_filter = ("tenant",)
    search_fields = ("first_name", "last_name", "email")
    filter_horizontal = ("branches",)
    exclude = ("created_by",)

    def has_add_permission(self, request):
        # Prevent manual creation of Member from admin
        return False

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user

        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        """
        Called after save_model and after m2m relationships are saved.
        Safe place to modify ManyToMany fields.
        """
        super().save_related(request, form, formsets, change)

        enquiry_id = request.GET.get("from_enquiry")

        if enquiry_id:
            try:
                enquiry = Enquiry.objects.get(id=enquiry_id)

                # Prevent double linking
                if enquiry.converted_member:
                    return

                member = form.instance

                # Link enquiry → member
                enquiry.converted_member = member
                enquiry.save(update_fields=["converted_member"])

                # 🔥 Auto-assign branch properly
                member.branches.add(enquiry.branch)

                # Log conversion activity
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

    # -----------------------------------
    # Link Member Back To Enquiry
    # -----------------------------------
    def save_model(self, request, obj, form, change):

        is_new = obj.pk is None

        super().save_model(request, obj, form, change)

        # Only run on new member creation
        if is_new:
            enquiry_id = request.GET.get("from_enquiry")

            if enquiry_id:
                from crm.models import Enquiry

                enquiry = Enquiry.objects.filter(
                    pk=enquiry_id,
                    tenant=obj.tenant
                ).first()

                if enquiry and not enquiry.converted_member:
                    enquiry.converted_member = obj
                    enquiry.save(update_fields=["converted_member"])

    # -----------------------------------
    # Enforce Tenant Filtering Explicitly
    # -----------------------------------
    def get_queryset(self, request):
        qs = super().get_queryset(request)

        if request.user.is_superuser:
            return qs

        if hasattr(request.user, "tenant") and request.user.tenant:
            return qs.filter(tenant=request.user.tenant)

        return qs.none()

    def get_queryset(self, request):
        print("USER:", request.user, "SUPERUSER:", request.user.is_superuser)
        print("USER TENANT:", getattr(request.user, "tenant", None))

        qs = super().get_queryset(request)

        if request.user.is_superuser:
            print("Returning ALL")
            return qs

        if hasattr(request.user, "tenant") and request.user.tenant:
            print("Filtering by:", request.user.tenant)
            return qs.filter(tenant=request.user.tenant)

        print("Returning NONE")
        return qs.none()
    
    def get_exclude(self, request, obj=None):
        exclude = list(super().get_exclude(request, obj) or [])

        if not request.user.is_superuser:
            if "tenant" not in exclude:
                exclude.append("tenant")

        return exclude

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser:
            obj.tenant = request.user.tenant

        if not change:
            obj.created_by = request.user

        super().save_model(request, obj, form, change)

    def get_list_display(self, request):
        fields = list(super().get_list_display(request))

        if not request.user.is_superuser:
            if "tenant" in fields:
                fields.remove("tenant")

        return tuple(fields)

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "branches":
            if not request.user.is_superuser:
                kwargs["queryset"] = db_field.remote_field.model.objects.filter(
                    tenant=request.user.tenant
                )

        return super().formfield_for_manytomany(db_field, request, **kwargs)

    def get_queryset(self, request):
        if request.user.is_superuser:
            return Member._base_manager.all()

        return super().get_queryset(request)

    def get_fields(self, request, obj=None):
        fields = super().get_fields(request, obj)

        if not request.user.is_superuser:
            fields = [f for f in fields if f != "tenant"]

        return fields

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser:
            obj.tenant = request.user.tenant

        super().save_model(request, obj, form, change)