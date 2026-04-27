from django.urls import path
from . import views

app_name = "payments"

urlpatterns = [
    path("",                                    views.payment_list,              name="payment_list"),
    path("record/",                             views.payment_record,            name="payment_record"),
    path("create/",                             views.payment_create,            name="payment_create"),
    path("settings/",                           views.payment_settings,          name="payment_settings"),
    path("member-memberships/",                 views.member_memberships_json,   name="member_memberships_json"),
    path("<uuid:pk>/",                          views.payment_detail,            name="payment_detail"),
    path("<uuid:pk>/mark-success/",             views.payment_mark_success,      name="payment_mark_success"),
    path("<uuid:pk>/mark-failed/",              views.payment_mark_failed,       name="payment_mark_failed"),
    path("<uuid:pk>/checkout/",                 views.payment_checkout,          name="payment_checkout"),
]
