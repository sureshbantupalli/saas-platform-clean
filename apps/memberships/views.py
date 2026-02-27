from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import IsAuthenticated
from django.db.models import Prefetch

from .models import Membership
from .serializers import MembershipSerializer


class MembershipViewSet(ModelViewSet):
    """
    API endpoint for managing memberships.
    """

    serializer_class = MembershipSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user

        queryset = Membership.base_objects.select_related(
            "member",
            "branch",
            "plan",
            "tenant",
            "created_by"
        )

        # Platform Admin → Full access
        if user.is_platform_admin:
            return queryset

        # Tenant Restricted Users
        return queryset.filter(
            tenant=user.tenant
        )

    def perform_create(self, serializer):
        serializer.save(
            created_by=self.request.user,
            tenant=self.request.user.tenant
        )