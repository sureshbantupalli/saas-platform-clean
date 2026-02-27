from django.urls import path
from . import views

urlpatterns = [
    path("role-permissions/", views.role_permissions_view, name="role_permissions"),
]