from django.urls import path
from . import views

app_name = "intake"

urlpatterns = [
    # Builder
    path("", views.form_builder_list, name="form_builder_list"),
    path("create/", views.form_create, name="form_create"),
    path("<uuid:form_id>/", views.form_builder_detail, name="form_builder_detail"),

    # Lifecycle
    path("<uuid:form_id>/activate/", views.form_activate, name="form_activate"),
    path("<uuid:form_id>/deactivate/", views.form_deactivate, name="form_deactivate"),
    path("<uuid:form_id>/save-draft/", views.form_save_draft, name="form_save_draft"),

    # User-facing renderer
    path("<uuid:form_id>/render/", views.form_render, name="form_render"),

    # Field CRUD (AJAX)
    path("<uuid:form_id>/fields/create/", views.field_create, name="field_create"),
    path("<uuid:form_id>/fields/<uuid:field_id>/update/", views.field_update, name="field_update"),
    path("<uuid:form_id>/fields/<uuid:field_id>/delete/", views.field_delete, name="field_delete"),
]
