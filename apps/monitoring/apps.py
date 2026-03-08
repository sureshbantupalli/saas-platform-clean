from django.apps import AppConfig


class MonitoringConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.monitoring"

    def ready(self):
        # Register monitoring permissions
        from apps.core.permissions.registry import register_permission
        from .permissions import MonitoringPermission

        register_permission("monitoring", MonitoringPermission)