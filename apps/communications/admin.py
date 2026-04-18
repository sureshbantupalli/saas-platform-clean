from django.contrib import admin
from .models import CommunicationLog, MessageTemplate, TriggerRule


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
    list_display   = ["channel", "recipient", "status", "tenant", "created_at"]
    list_filter    = ["channel", "status"]
    readonly_fields = ["created_at", "updated_at"]
