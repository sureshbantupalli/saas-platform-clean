from django.urls import path
from .views import next_actions_api

app_name = "actions"

urlpatterns = [
    path("next/", next_actions_api, name="next"),
]
