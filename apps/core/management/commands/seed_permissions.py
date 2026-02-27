from django.core.management.base import BaseCommand
from apps.core.permissions.definition_registry import PERMISSION_DEFINITIONS
from apps.authority.models import PermissionAction


class Command(BaseCommand):
    help = "Seeds PermissionAction table from PERMISSION_DEFINITIONS"

    def handle(self, *args, **options):
        created_count = 0
        existing_count = 0

        self.stdout.write(self.style.WARNING("Seeding permissions...\n"))

        for module, actions in PERMISSION_DEFINITIONS.items():
            for action in actions:
                obj, created = PermissionAction.objects.get_or_create(
                    module=module,
                    action=action
                )

                if created:
                    created_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(f"Created: {module}:{action}")
                    )
                else:
                    existing_count += 1
                    self.stdout.write(
                        self.style.NOTICE(f"Exists: {module}:{action}")
                    )

        self.stdout.write("\n----------------------------")
        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Created: {created_count}, Already Existing: {existing_count}"
            )
        )