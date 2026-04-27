from django.urls import path
from . import views

app_name = 'roles'

urlpatterns = [
    path('',                            views.role_list,        name='list'),
    path('create/',                     views.role_create,      name='create'),
    path('<uuid:role_id>/edit/',        views.role_edit,        name='edit'),
    path('<uuid:role_id>/delete/',      views.role_delete,      name='delete'),
    path('<uuid:role_id>/permissions/', views.role_permissions,  name='permissions'),
    path('<uuid:role_id>/users/',       views.role_users,       name='users'),
]
