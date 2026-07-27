from django.urls import path, include
from . import views

urlpatterns = [
    # Root → redirect to general
    path('',                  views.settings_index,          name='index'),

    # Active settings sections
    path('general/',          views.general_settings,        name='general'),
    path('payments/',         views.payments_settings,       name='payments'),
    path('payments/test-webhook/', views.test_webhook,        name='test_webhook'),
    path('communications/',   views.communications_settings, name='communications'),

    # Branch management (tenant self-service)
    path('branches/',         include(('apps.settings.branches.urls', 'branches'), namespace='branches')),

    # Staff user management (tenant self-service)
    path('users/',            include(('apps.settings.users.urls', 'staff'), namespace='staff')),

    # RBAC (Phase 1 — already implemented)
    path('roles/',            include(('apps.settings.roles.urls', 'roles'), namespace='roles')),

    # Vocabulary (Phase 3)
    path('vocabulary/',       include(('apps.settings.vocabulary.urls', 'vocabulary'), namespace='vocabulary')),

    # Branding (Phase 4)
    path('branding/',         include(('apps.settings.branding.urls', 'branding'), namespace='branding')),
]
