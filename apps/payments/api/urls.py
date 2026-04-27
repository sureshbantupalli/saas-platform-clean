from django.urls import path
from . import views

urlpatterns = [
    path("create/",                       views.create_payment,          name="api_payment_create"),
    path("generate-checkout-link/",       views.generate_checkout_link,  name="api_payment_checkout_link"),
    path("<uuid:pk>/",                    views.payment_detail,          name="api_payment_detail"),
    path("<uuid:pk>/mark-success/",       views.mark_success,            name="api_payment_mark_success"),
    path("<uuid:pk>/mark-failed/",        views.mark_failed,             name="api_payment_mark_failed"),
    path("webhook/",                      views.webhook,                  name="api_payment_webhook"),
]
