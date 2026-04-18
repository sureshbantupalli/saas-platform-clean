from django.apps import AppConfig


class CommunicationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.communications"
    label = "communications"
    verbose_name = "Communications"

    def ready(self):
        import apps.communications.handlers  # noqa: F401 — registers signal receivers
