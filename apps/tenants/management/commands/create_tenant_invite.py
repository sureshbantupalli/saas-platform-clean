"""Issue a tenant invitation and email it.

Replaces SSH + `provision_tenant` as the way a new studio gets onboarded: the
owner sets their own password through a link, so no one has to handle it for
them.

    manage.py create_tenant_invite --studio "Setu Yoga" --email owner@setu.com
    manage.py create_tenant_invite --studio "Setu Yoga" --email owner@setu.com \
        --subdomain setu --owner-name "Suresh" --expiry-days 14
    manage.py create_tenant_invite ... --no-email     # print the link, send nothing

The raw token is shown ONCE, here. It is stored only as a hash, so it cannot
be recovered later — if it is lost, revoke the invite and issue a new one.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.tenants.invite_service import (
    InviteError,
    build_invite_url,
    create_invite,
    send_invite_email,
    suggest_subdomain,
)


class Command(BaseCommand):
    help = "Create a tenant invitation and email the setup link to the owner."

    def add_arguments(self, parser):
        parser.add_argument("--studio", required=True, help="Studio / tenant name.")
        parser.add_argument("--email", required=True, help="Owner's email address.")
        parser.add_argument("--subdomain", default="", help="Defaults to a slug of --studio.")
        parser.add_argument("--owner-name", default="", help="Used to address the email.")
        parser.add_argument("--expiry-days", type=int, default=None)
        parser.add_argument(
            "--no-email",
            action="store_true",
            help="Create the invite and print the link without sending it.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would happen without creating anything.",
        )

    def handle(self, *args, **options):
        studio = options["studio"].strip()
        email = options["email"].strip()
        subdomain = options["subdomain"].strip()

        if options["dry_run"]:
            resolved = subdomain or suggest_subdomain(studio)
            self.stdout.write(
                f"[dry-run] Would invite {email} to create '{studio}' "
                f"at subdomain '{resolved}'."
            )
            return

        try:
            raw_token, invite = create_invite(
                studio_name=studio,
                email=email,
                subdomain=subdomain or None,
                owner_name=options["owner_name"],
                expiry_days=options["expiry_days"],
            )
        except InviteError as exc:
            raise CommandError(str(exc))

        url = build_invite_url(raw_token)

        self.stdout.write(self.style.SUCCESS(f"Invite created for {invite.email}"))
        self.stdout.write(f"  studio    : {invite.studio_name}")
        self.stdout.write(f"  subdomain : {invite.subdomain}")
        self.stdout.write(f"  expires   : {invite.expires_at:%Y-%m-%d %H:%M} "
                          f"({invite.days_until_expiry} days)")
        self.stdout.write("")
        self.stdout.write(self.style.WARNING("  Setup link (shown once, not recoverable):"))
        self.stdout.write(f"  {url}")
        self.stdout.write("")

        if options["no_email"]:
            self.stdout.write("  --no-email set; nothing was sent. Share the link yourself.")
            return

        if send_invite_email(invite, raw_token):
            self.stdout.write(self.style.SUCCESS("  Invitation email sent."))
        else:
            self.stdout.write(self.style.ERROR(
                "  Invitation email NOT sent. The invite is still valid — share "
                "the link above manually.\n"
                "  Check: platform tenant exists (ensure_platform_tenant), "
                "templates seeded (seed_platform_comms), and EMAIL_HOST is set."
            ))
