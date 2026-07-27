from django.urls import path
from . import views

app_name = 'staff'

urlpatterns = [
    path('',                         views.user_list,       name='list'),
    path('invite/',                  views.user_invite,     name='invite'),
    path('<int:user_id>/edit/',      views.user_edit,       name='edit'),
    path('<int:user_id>/toggle/',    views.user_toggle,     name='toggle'),
]
