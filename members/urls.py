from django.urls import path
from . import views

app_name = "members"

urlpatterns = [
    path("", views.member_list, name="member_list"),
    path("create/", views.member_create, name="member_create"),
    path("<uuid:pk>/", views.member_detail, name="member_detail"),
    path("<uuid:pk>/edit/", views.member_update, name="member_update"),
    path("<uuid:pk>/delete/", views.member_delete, name="member_delete"),
]