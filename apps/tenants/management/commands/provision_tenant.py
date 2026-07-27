"""
Provision a new tenant (studio) with its default roles, permissions and owner.

Replaces hand-running TenantService.create_tenant() in a production Django
shell, which was the only way to onboard a customer. Adds the safety the raw
service lacks:

  * runs inside a transaction, so a failure cannot leave an orphaned tenant
  * refuses to run if PermissionAction rows are not seeded (otherwise roles
    are created silently holding zero permissions)
  * validates the email and subdomain before writing anything
  * reads the owner password from a prompt or the environment, never from
    argv, so it does not land in shell history or the process list
  * --dry-run to rehearse against production safely

Usage:
    python manage.py provision_tenant \
        --name "Setu Yoga Studio" \
        --subdomain setu \
        --admin-email owner@setuyoga.com

    # non-interactive (CI / scripted):
    TENANT_ADMIN_PASSWORD=... python manage.py provision_tenant ... --no-input
"""

import os
import re
from getpass import getpass

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db import transaction

from apps.authority.models import PermissionAction
from apps.core.models import Tenant
from apps.tenants.services import TenantService

User = get_user_model()

SUBDOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
PASSWORD_ENV_VAR = "TENANT_ADMIN_PASSWORD"
MIN_PASSWORD_LENGTH = 12


class Command(BaseCommand):
    help = "Provision a new tenant with default roles, permissions and an owner user."

    def add_arguments(self, parser):
        parser.add_argument("--name", required=True, help='Studio name, e.g. "Setu Yoga Studio"')
        parser.add_argument("--subdomain", required=True, help="Lowercase slug, e.g. setu")
        parser.add_argument("--admin-email", required=True, help="Owner login email")
        parser.add_argument(
            "--no-input",
            action="store_true",
            help=f"Do not prompt; read the password from ${PASSWORD_ENV_VAR}.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate everything and roll back without persisting.",
        )

    # ---------------------------------------------------------------- helpers

    def _validate(self, name, subdomain, admin_email):
        """Fail fast on bad input before touching the database."""
        errors = []

        if not name.strip():
            errors.append("--name cannot be blank.")

        if not SUBDOMAIN_RE.match(subdomain):
            errors.append(
                f"--subdomain '{subdomain}' is invalid: use lowercase letters, "
                "digits and hyphens only, and it may not start or end with a hyphen."
            )

        try:
            validate_email(admin_email)
        except ValidationError:
            errors.append(f"--admin-email '{admin_email}' is not a valid email address.")

        # Uniqueness — checked up front so the operator gets one clear message
        # rather than an IntegrityError partway through provisioning.
        if Tenant.objects.filter(name=name).exists():
            errors.append(f"A tenant named '{name}' already exists.")
        if Tenant.objects.filter(subdomain=subdomain).exists():
            errors.append(f"Subdomain '{subdomain}' is already taken.")
        if User.objects.filter(email=admin_email).exists():
            errors.append(f"A user with email '{admin_email}' already exists.")

        if errors:
            raise CommandError("Cannot provision tenant:\n  - " + "\n  - ".join(errors))

    def _check_permissions_seeded(self):
        """create_tenant() grants RolePermissions by iterating PermissionAction.

        If that table is empty the tenant is created with four roles that hold
        no permissions at all — and nothing errors. Refuse instead.
        """
        count = PermissionAction.objects.count()
        if count == 0:
            raise CommandError(
                "PermissionAction table is empty, so the new tenant's roles would "
                "be created with zero permissions.\n"
                "Run this first:\n"
                "    python manage.py seed_permissions"
            )
        return count

    def _get_password(self, no_input):
        password = os.environ.get(PASSWORD_ENV_VAR)

        if password:
            source = f"${PASSWORD_ENV_VAR}"
        elif no_input:
            raise CommandError(
                f"--no-input given but ${PASSWORD_ENV_VAR} is not set."
            )
        else:
            password = getpass("Owner password: ")
            confirm = getpass("Confirm password: ")
            if password != confirm:
                raise CommandError("Passwords do not match.")
            source = "interactive prompt"

        if len(password) < MIN_PASSWORD_LENGTH:
            raise CommandError(
                f"Password must be at least {MIN_PASSWORD_LENGTH} characters "
                f"(got {len(password)})."
            )
        return password, source

    # ------------------------------------------------------------------ main

    def handle(self, *args, **options):
        name = options["name"]
        subdomain = options["subdomain"].lower().strip()
        admin_email = options["admin_email"].strip()
        dry_run = options["dry_run"]

        perm_count = self._check_permissions_seeded()
        self._validate(name, subdomain, admin_email)
        password, password_source = self._get_password(options["no_input"])

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Provisioning tenant"))
        self.stdout.write(f"  name       : {name}")
        self.stdout.write(f"  subdomain  : {subdomain}")
        self.stdout.write(f"  owner email: {admin_email}")
        self.stdout.write(f"  password   : from {password_source}")
        self.stdout.write(f"  permissions: {perm_count} actions available")
        if dry_run:
            self.stdout.write(self.style.WARNING("  mode       : DRY RUN (will roll back)"))
        self.stdout.write("")

        class _Rollback(Exception):
            """Signals an intentional dry-run rollback."""

        try:
            # Atomic: create_tenant() writes a Tenant, four Roles, a large set of
            # RolePermissions and finally the owner User. Without this wrapper a
            # failure at the last step leaves the first three behind.
            with transaction.atomic():
                tenant = TenantService.create_tenant(
                    name=name,
                    subdomain=subdomain,
                    admin_email=admin_email,
                    password=password,
                )
                owner = User.objects.get(email=admin_email)
                roles = list(
                    tenant.role_set.values_list("name", flat=True)
                ) if hasattr(tenant, "role_set") else []

                if dry_run:
                    raise _Rollback

        except _Rollback:
            self.stdout.write(self.style.WARNING("Dry run complete — rolled back, nothing saved."))
            self.stdout.write("Re-run without --dry-run to provision for real.")
            return

        self.stdout.write(self.style.SUCCESS("Tenant provisioned."))
        self.stdout.write(f"  tenant id : {tenant.id}")
        self.stdout.write(f"  owner id  : {owner.id}")
        if roles:
            self.stdout.write(f"  roles     : {', '.join(sorted(roles))}")
        self.stdout.write("")
        self.stdout.write("Next: sign in as the owner and change the password.")
