from django.urls import path
from . import views

app_name = "bookings"

urlpatterns = [
    path("", views.booking_list, name="booking_list"),
    path("create/", views.booking_create, name="booking_create"),
    path("<uuid:booking_id>/cancel/", views.booking_cancel, name="booking_cancel"),
]
