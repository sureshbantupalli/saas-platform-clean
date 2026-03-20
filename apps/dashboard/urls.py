from django.urls import path
from .views import WidgetDataView

urlpatterns = [
    path("widgets/<str:widget_key>/", WidgetDataView.as_view(), name="dashboard-widgets"),
]