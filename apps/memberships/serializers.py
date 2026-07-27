from rest_framework import serializers
from django.db import IntegrityError

from .models import Membership
from apps.core.models import Branch
from members.models import Member


class MembershipSerializer(serializers.ModelSerializer):

    class Meta:
        model = Membership
        fields = "__all__"
        read_only_fields = ("id", "tenant", "created_at", "updated_at")

    def validate(self, attrs):
        request = self.context["request"]
        user = request.user

        member = attrs.get("member")
        branch = attrs.get("branch")

        # 🔒 Ensure branch belongs to user's tenant
        if not user.is_platform_admin:
            if branch.tenant != user.tenant:
                raise serializers.ValidationError(
                    "Branch does not belong to your tenant."
                )

        # 🔒 Ensure member belongs to same tenant
        if not user.is_platform_admin:
            if member.tenant != user.tenant:
                raise serializers.ValidationError(
                    "Member does not belong to your tenant."
                )

        return attrs

    def create(self, validated_data):
        try:
            membership = Membership.objects.create(**validated_data)
        except IntegrityError:
            raise serializers.ValidationError(
                "Active membership already exists for this member in this branch."
            )
        # Audit — fire outside the except block so exceptions don't swallow it
        try:
            from apps.memberships.services import log_membership_enrolled
            user = self.context.get("request") and self.context["request"].user or None
            log_membership_enrolled(membership, created_by=user)
        except Exception:
            pass
        return membership