from rest_framework import serializers
from members.models import Member
from apps.core.models import Branch


class MemberSerializer(serializers.ModelSerializer):

    class Meta:
        model = Member
        fields = [
            "id",
            "tenant",
            "created_by",
            "first_name",
            "last_name",
            "email",
            "phone",
            "branches",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["tenant", "created_by"]

    def get_fields(self):
        fields = super().get_fields()

        request = self.context.get("request")

        if request and request.user.is_authenticated:
            tenant = request.user.tenant

            fields["branches"].queryset = Branch.base_objects.filter(
                tenant=tenant,
                is_active=True
            )
        else:
            fields["branches"].queryset = Branch.base_objects.none()

        return fields

    # 🔥 ADD THIS
    def validate_branches(self, value):
        if not value or len(value) == 0:
            raise serializers.ValidationError(
                "Member must belong to at least one branch."
            )
        return value