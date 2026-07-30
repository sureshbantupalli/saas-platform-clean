from django.contrib import admin

from apps.tenants.models import InviteStatus, TenantInvite


@admin.register(TenantInvite)
class TenantInviteAdmin(admin.ModelAdmin):
    """Read-mostly view of invitations.

    Invites are issued with `manage.py create_tenant_invite`, not here — the
    raw token is shown exactly once at creation and is never stored, so there
    is nothing this form could usefully create.
    """

    list_display = [
        "studio_name", "email", "subdomain", "status",
        "expires_at", "email_sent", "tenant",
    ]
    list_filter = ["status", "email_sent"]
    search_fields = ["studio_name", "email", "subdomain"]
    date_hierarchy = "created_at"

    # token_hash is excluded entirely: it is the credential's only stored form
    # and has no operational use in the UI.
    fields = [
        "studio_name", "subdomain", "email", "owner_name",
        "status", "expires_at", "accepted_at", "tenant",
        "invited_by", "email_sent", "email_error", "created_at",
    ]
    readonly_fields = [
        "studio_name", "subdomain", "email", "owner_name",
        "accepted_at", "tenant", "invited_by",
        "email_sent", "email_error", "created_at",
    ]

    actions = ["revoke_selected"]

    def has_add_permission(self, request):
        return False

    @admin.action(description="Revoke selected pending invitations")
    def revoke_selected(self, request, queryset):
        from apps.tenants.invite_service import revoke_invite, InviteError

        revoked = skipped = 0
        for invite in queryset:
            try:
                revoke_invite(invite)
                revoked += 1
            except InviteError:
                skipped += 1
        self.message_user(
            request,
            f"{revoked} invitation(s) revoked."
            + (f" {skipped} skipped (not pending)." if skipped else "")
        )
