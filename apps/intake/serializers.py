from rest_framework import serializers
from .models import IntakeForm, FormField, FormResponse


class FormFieldSerializer(serializers.ModelSerializer):
    class Meta:
        model = FormField
        fields = [
            "id", "label", "field_key", "field_type", "placeholder",
            "help_text", "is_required", "order", "options", "scale_config",
        ]


class IntakeFormSerializer(serializers.ModelSerializer):
    fields = FormFieldSerializer(many=True, read_only=True)

    class Meta:
        model = IntakeForm
        fields = [
            "id", "name", "description", "entity_type",
            "status", "published_at", "fields",
        ]


class IntakeFormWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = IntakeForm
        fields = ["name", "description", "entity_type"]


class FormResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = FormResponse
        fields = ["id", "form", "entity_type", "entity_id", "data", "created_at"]
        read_only_fields = ["id", "created_at"]


class FormSubmitSerializer(serializers.Serializer):
    entity_type = serializers.ChoiceField(choices=["lead", "member", "generic"])
    entity_id = serializers.UUIDField()
    data = serializers.DictField()
