from django.urls import path
from . import views

app_name = 'branches'

urlpatterns = [
    path('',                             views.branch_list,   name='list'),
    path('create/',                      views.branch_create, name='create'),
    path('<uuid:branch_id>/edit/',       views.branch_edit,   name='edit'),
    path('<uuid:branch_id>/toggle/',     views.branch_toggle, name='toggle'),
]
