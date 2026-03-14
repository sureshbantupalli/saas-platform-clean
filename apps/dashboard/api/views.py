from rest_framework.views import APIView
from rest_framework.response import Response

from apps.dashboard.services.widget_service import WidgetService
from apps.core.models import Tenant


class DashboardWidgetsAPIView(APIView):
    """
    Return dashboard widgets.
    """

    def get(self, request):

        # Try tenant from request middleware
        tenant = getattr(request, "tenant", None)

        # Development fallback
        if tenant is None:
            tenant = Tenant.objects.first()

        branch = getattr(request, "branch", None)

        service = WidgetService(
            tenant=tenant,
            branch=branch
        )

        widgets = service.run_all_widgets()

        return Response(widgets)