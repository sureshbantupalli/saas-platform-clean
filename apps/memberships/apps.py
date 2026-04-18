from django.apps import AppConfig


class MembershipsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.memberships"

    def ready(self):
        import apps.memberships.handlers  # noqa: F401 — registers payment signal receivers