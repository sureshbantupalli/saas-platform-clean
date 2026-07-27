from django.urls import path

from . import views

app_name = "audit"

urlpatterns = [
    # Timeline views (HTML)
    path("",                              views.tenant_timeline,  name="tenant"),
    path("member/<uuid:member_id>/",      views.member_timeline,  name="member"),
    path("payment/<uuid:payment_id>/",    views.payment_timeline, name="payment"),
    path("user/<uuid:user_id>/",          views.user_timeline,    name="user"),

    # Explain views (JSON)
    path("explain/member/<uuid:member_id>/",   views.member_explain_view,  name="explain_member"),
    path("explain/payment/<uuid:payment_id>/", views.payment_explain_view, name="explain_payment"),
    path("explain/nudge/<uuid:member_id>/",    views.nudge_explain_view,   name="explain_nudge"),
]
