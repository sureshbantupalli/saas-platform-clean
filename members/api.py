from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import IsAuthenticated
from rest_framework import filters

from .serializers import MemberSerializer
from apps.core.drf_permissions import MemberPermission
from members.services.member_service import MemberService
from members.models import Member


class MemberViewSet(ModelViewSet):
    serializer_class = MemberSerializer
    permission_classes = [IsAuthenticated, MemberPermission]

    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["first_name", "last_name", "email"]
    ordering_fields = ["created_at", "updated_at", "first_name", "last_name"]
    ordering = ["-created_at"]

    def get_queryset(self):
        queryset = MemberService.get_queryset(self.request.user)

        # 🔥 FIX: Ensure it's always a QuerySet
        if isinstance(queryset, list):
            ids = [obj.id for obj in queryset]
            queryset = Member.objects.filter(id__in=ids)

        return queryset

    def perform_create(self, serializer):
        serializer.save(
            tenant=self.request.user.tenant,
            created_by=self.request.user
        )

    def perform_destroy(self, instance):
        MemberService.soft_delete(instance)