from django.apps import AppConfig


class CrmConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "crm"
    verbose_name = "Sales CRM"

    def ready(self):
        import crm.handlers  # noqa: F401 — registers signal receivers