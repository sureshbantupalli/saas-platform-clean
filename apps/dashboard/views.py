from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from apps.dashboard.registry import get_widget


class WidgetDataView(APIView):
    """
    Generic API to fetch widget data by key
    """

    def get(self, request, widget_key):
        widget_class = get_widget(widget_key)

        if not widget_class:
            return Response(
                {"error": "Invalid widget key"},
                status=status.HTTP_404_NOT_FOUND
            )

        widget = widget_class(request=request)

        return Response(widget.get_data())