from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import MembershipViewSet, MembershipCreateView


router = DefaultRouter()
router.register(r"memberships", MembershipViewSet, basename="membership")


urlpatterns = [

    # HTML Membership Creation
    path("add/", MembershipCreateView.as_view(), name="membership_add"),

]

# API Routes
urlpatterns += router.urls