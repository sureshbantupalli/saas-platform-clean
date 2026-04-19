from rest_framework.views import APIView
from rest_framework.response import Response

from apps.dashboard.services.widget_service import WidgetService


class DashboardWidgetsAPIView(APIView):
    """
    Return dashboard widgets.
    """

    def get(self, request):

        tenant = getattr(request, "tenant", None)

        if tenant is None:
            return Response({"error": "Tenant not found for this user."}, status=400)

        branch = getattr(request, "branch", None)

        service = WidgetService(
            tenant=tenant,
            branch=branch
        )

        widgets = service.run_all_widgets()

        return Response(widgets)