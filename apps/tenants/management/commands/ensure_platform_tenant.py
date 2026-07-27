"""Create (or adopt) the internal ANJASI platform tenant.

Idempotent — safe to run on every deploy. See apps/core/platform.py for why
ANJASI is modelled as a tenant rather than a separate messaging path.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.core.models import Tenant
from apps.core.platform import PLATFORM_TENANT_NAME, PLATFORM_TENANT_SUBDOMAIN


class Command(BaseCommand):
    help = "Create the internal platform tenant used for ANJASI's own messaging."

    def add_arguments(self, parser):
        parser.add_argument("--name", default=PLATFORM_TENANT_NAME)
        parser.add_argument("--subdomain", default=PLATFORM_TENANT_SUBDOMAIN)
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would happen without writing anything.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        name = options["name"].strip()
        subdomain = options["subdomain"].strip().lower()
        dry_run = options["dry_run"]

        if not name or not subdomain:
            raise CommandError("--name and --subdomain must both be non-empty.")

        existing = Tenant.objects.filter(is_platform=True).first()
        if existing:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Platform tenant already exists: {existing.name} "
                    f"({existing.subdomain}) — nothing to do."
                )
            )
            return

        # A tenant may already exist under this subdomain from a manual
        # provision; adopt it rather than failing on the unique constraint.
        clash = Tenant.objects.filter(subdomain=subdomain).first()
        if clash:
            if dry_run:
                self.stdout.write(
                    f"[dry-run] Would flag existing tenant '{clash.name}' "
                    f"({clash.subdomain}) as the platform tenant."
                )
                return
            clash.is_platform = True
            clash.save(update_fields=["is_platform"])
            self.stdout.write(
                self.style.SUCCESS(
                    f"Adopted existing tenant '{clash.name}' as the platform tenant."
                )
            )
            return

        if dry_run:
            self.stdout.write(
                f"[dry-run] Would create platform tenant '{name}' ({subdomain})."
            )
            return

        tenant = Tenant.objects.create(
            name=name, subdomain=subdomain, is_platform=True
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Created platform tenant '{tenant.name}' ({tenant.subdomain}).\n"
                "Next: seed its MessageTemplates and TriggerRules for the "
                "platform events you want to send."
            )
        )
