from django.contrib import admin
from .models import (
    CommunicationLog,
    MessageTemplate,
    TenantMessagingConfig,
    TriggerRule,
)


@admin.register(MessageTemplate)
class MessageTemplateAdmin(admin.ModelAdmin):
    list_display  = ["name", "channel", "tenant", "is_active", "created_at"]
    list_filter   = ["channel", "is_active"]
    search_fields = ["name", "content"]


@admin.register(TriggerRule)
class TriggerRuleAdmin(admin.ModelAdmin):
    list_display  = ["event_name", "template", "tenant", "is_active"]
    list_filter   = ["event_name", "is_active"]
    search_fields = ["event_name"]


@admin.register(CommunicationLog)
class CommunicationLogAdmin(admin.ModelAdmin):
    list_display    = ["channel", "event_type", "recipient", "status", "tenant", "created_at"]
    list_filter     = ["channel", "status", "event_type"]
    search_fields   = ["recipient", "event_type", "message"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(TenantMessagingConfig)
class TenantMessagingConfigAdmin(admin.ModelAdmin):
    """Where a tenant's own MSG91 / WhatsApp credentials are entered.

    Until the self-service portal exists this is the only place to set them,
    so it is deliberately explicit about which field means what per provider.
    """

    list_display  = ["tenant", "provider", "sender_id", "template_id", "is_active"]
    list_filter   = ["provider", "is_active"]
    search_fields = ["tenant__name", "sender_id", "template_id"]

    fieldsets = (
        (None, {
            "fields": ("tenant", "provider", "is_active"),
            "description": (
                "These credentials belong to the TENANT, not to ANJASI. Under "
                "TRAI DLT the SMS sender header is registered to the tenant's "
                "own Principal Entity, and a WhatsApp Business Account binds to "
                "their phone number and verified business name. Leave "
                "<b>is_active</b> off until their registration completes — an "
                "inactive row is ignored and the adapter stays silent rather "
                "than sending under the wrong identity."
            ),
        }),
        ("Credentials", {
            "fields": ("api_key", "sender_id", "template_id", "template_lang"),
            "description": (
                "<b>MSG91</b> — api_key: auth key &middot; sender_id: sender/header "
                "ID &middot; template_id: DLT template ID &middot; template_lang: unused."
                "<br><b>WhatsApp Cloud</b> — api_key: access token &middot; "
                "sender_id: phone number ID &middot; template_id: approved template "
                "name &middot; template_lang: e.g. en or en_US."
            ),
        }),
    )

    def get_readonly_fields(self, request, obj=None):
        # tenant+provider are unique together; changing them on an existing row
        # silently re-points live credentials at a different studio.
        return ["tenant", "provider"] if obj else []
