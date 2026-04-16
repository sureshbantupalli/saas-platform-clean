from django.apps import AppConfig


class PlatformSessionsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.sessions'
    label = 'gym_sessions'

    def ready(self):
        import apps.sessions.signals