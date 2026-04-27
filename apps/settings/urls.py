from django.urls import path, include
from . import views

urlpatterns = [
    # Root → redirect to general
    path('',                  views.settings_index,          name='index'),

    # Active settings sections
    path('general/',          views.general_settings,        name='general'),
    path('payments/',         views.payments_settings,       name='payments'),
    path('communications/',   views.communications_settings, name='communications'),

    # RBAC (Phase 1 — already implemented)
    path('roles/',            include(('apps.settings.roles.urls', 'roles'), namespace='roles')),

    # Vocabulary (Phase 3)
    path('vocabulary/',       include(('apps.settings.vocabulary.urls', 'vocabulary'), namespace='vocabulary')),

    # Branding (Phase 4)
    path('branding/',         include(('apps.settings.branding.urls', 'branding'), namespace='branding')),
    # TODO: path('branding/',        include('apps.settings.branding.urls')),     # Phase 4
    # TODO: path('feature-flags/',   include('apps.settings.features.urls')),     # Phase 5
    # TODO: path('audit/',           include('apps.settings.audit.urls')),        # Phase 6
]
