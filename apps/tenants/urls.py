"""Public invite routes.

Deliberately unauthenticated — an invitee has no account until they use these.
The token in the path is the only credential; see views.accept_invite_view for
how it is constrained.
"""

from django.urls import path

from apps.tenants import views

app_name = "tenants"

urlpatterns = [
    path("invite/done/", views.invite_done_view, name="invite_done"),
    path("invite/<str:token>/", views.accept_invite_view, name="invite_accept"),
]
