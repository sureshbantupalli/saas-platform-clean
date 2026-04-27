from django.urls import path

from . import views

urlpatterns = [
    path('', views.vocabulary_settings, name='vocabulary'),
]
