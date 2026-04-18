from django.urls import path
from . import views

app_name = "communications"

urlpatterns = [
    # Message Templates
    path("templates/",                   views.template_list,   name="template_list"),
    path("templates/create/",            views.template_create, name="template_create"),
    path("templates/<uuid:pk>/edit/",    views.template_edit,   name="template_edit"),
    path("templates/<uuid:pk>/toggle/",  views.template_toggle, name="template_toggle"),

    # Trigger Rules
    path("triggers/",                    views.trigger_list,    name="trigger_list"),
    path("triggers/create/",             views.trigger_create,  name="trigger_create"),
    path("triggers/<uuid:pk>/edit/",     views.trigger_edit,    name="trigger_edit"),
    path("triggers/<uuid:pk>/toggle/",   views.trigger_toggle,  name="trigger_toggle"),

    # Logs
    path("logs/",                        views.log_list,        name="log_list"),
]
