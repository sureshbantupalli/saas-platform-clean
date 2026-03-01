from django.urls import path
from . import views
from .views import AssignEnquiryView

app_name = "crm_ui"

urlpatterns = [
    path("dashboard/", views.CRMdashboardView.as_view(), name="dashboard"),
    path("enquiries/", views.EnquiryListView.as_view(), name="enquiry_list"),
    path("enquiries/<int:pk>/", views.EnquiryDetailView.as_view(), name="enquiry_detail"),
    path("enquiries/<int:pk>/assign/", AssignEnquiryView.as_view(), name="assign_enquiry"),
]