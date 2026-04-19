from django.contrib import admin
from .models import IntakeForm, FormField, FormResponse


class FormFieldInline(admin.TabularInline):
    model = FormField
    extra = 0
    fields = ("label", "field_key", "field_type", "is_required", "order")


@admin.register(IntakeForm)
class IntakeFormAdmin(admin.ModelAdmin):
    list_display = ("name", "entity_type", "status", "tenant")
    list_filter = ("entity_type", "status")
    inlines = [FormFieldInline]


@admin.register(FormResponse)
class FormResponseAdmin(admin.ModelAdmin):
    list_display = ("form", "entity_type", "entity_id", "created_at")
    readonly_fields = ("data",)
