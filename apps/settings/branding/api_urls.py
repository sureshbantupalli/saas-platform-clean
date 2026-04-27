from django.urls import path

from . import api_views

urlpatterns = [
    path('generate-palette/', api_views.generate_palette, name='generate_palette'),
]
