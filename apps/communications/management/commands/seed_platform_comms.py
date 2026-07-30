"""management command: seed_platform_comms

Creates the MessageTemplates and TriggerRules that ANJASI uses to speak as
itself — studio onboarding, subscription invoices, service notices — against
the internal platform tenant.

Without these, platform messaging is plumbed but silent: notify_platform()
finds no matching TriggerRule and returns False. This command is what makes
that path actually send.

Safe to run repeatedly — uses get_or_create, so edits made in the admin are
preserved.

    python manage.py ensure_platform_tenant     # must exist first
    python manage.py seed_platform_comms
    python manage.py seed_platform_comms --dry-run

Why every template is EMAIL
---------------------------
Platform messages are addressed to studio owners, not studio members, and
email is the only channel ANJASI owns outright. SMS and WhatsApp credentials
belong to each tenant — an SMS from ANJASI would have to go out under some
studio's DLT header, which is both wrong and a TRAI compliance problem. Email
is also the only channel with no external approval gate blocking it.

Subjects are mandatory here
---------------------------
adapters/email.py refuses to send a message with an empty subject, so every
template below sets one. A template added later without a subject will fail
at send time, not at seed time.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.communications.models import Channel, MessageTemplate, TriggerRule
from apps.communications.services import platform_comms as events
from apps.core.platform import PlatformTenantMissing, get_platform_tenant


# Each entry is one (event, template) pair. The `variables` field documents the
# placeholders the sending code must supply; `recipient` is a reminder that
# _resolve_recipient() reads context["email"] for the EMAIL channel, so the
# payload has to carry it.
PLATFORM_TEMPLATES = [
    {
        "event_name": events.TENANT_INVITED,
        "name": "Platform — Studio Invited",
        "subject": "Set up {{studio_name}} on ANJASI",
        "content": (
            "<p>Hi {{owner_name}},</p>"
            "<p>Your ANJASI workspace for <strong>{{studio_name}}</strong> is ready "
            "to set up. Use the link below to create your administrator account "
            "and choose a password.</p>"
            "<p><a href=\"{{invite_url}}\">Set up your workspace</a></p>"
            "<p>The link expires in {{expiry_days}} days. If it lapses, reply to "
            "this email and we will send a fresh one.</p>"
        ),
        "variables": {
            "owner_name": "Name of the person being invited",
            "studio_name": "Studio / tenant name",
            "invite_url": "Single-use activation URL",
            "expiry_days": "Days until the invite expires",
            "email": "Recipient address — required for the EMAIL channel",
        },
    },
    {
        "event_name": events.TENANT_ACTIVATED,
        "name": "Platform — Studio Activated",
        "subject": "{{studio_name}} is live on ANJASI",
        "content": (
            "<p>Hi {{owner_name}},</p>"
            "<p><strong>{{studio_name}}</strong> is now active. You can sign in at "
            "<a href=\"{{login_url}}\">{{login_url}}</a>.</p>"
            "<p>A good first step is adding your branches and staff, then your "
            "membership plans — members and bookings follow naturally from those.</p>"
            "<p>If anything looks wrong, reply to this email.</p>"
        ),
        "variables": {
            "owner_name": "Studio owner / primary admin",
            "studio_name": "Studio / tenant name",
            "login_url": "Tenant login URL",
            "email": "Recipient address — required for the EMAIL channel",
        },
    },
    {
        "event_name": events.SUBSCRIPTION_INVOICE,
        "name": "Platform — Subscription Invoice",
        "subject": "Invoice {{invoice_number}} for {{studio_name}}",
        "content": (
            "<p>Hi {{owner_name}},</p>"
            "<p>Invoice <strong>{{invoice_number}}</strong> for "
            "{{studio_name}} is ready.</p>"
            "<p>Amount due: <strong>{{amount}}</strong><br>"
            "Billing period: {{period}}<br>"
            "Due date: {{due_date}}</p>"
            "<p>{{payment_instructions}}</p>"
            "<p>Reply to this email with any billing question.</p>"
        ),
        "variables": {
            "owner_name": "Studio owner / billing contact",
            "studio_name": "Studio / tenant name",
            "invoice_number": "Invoice reference",
            "amount": "Amount due, pre-formatted with currency",
            "period": "Billing period covered",
            "due_date": "Payment due date",
            "payment_instructions": "How to pay — set per invoice while billing is manual",
            "email": "Recipient address — required for the EMAIL channel",
        },
    },
    {
        "event_name": events.SUBSCRIPTION_PAYMENT_FAILED,
        "name": "Platform — Subscription Payment Failed",
        "subject": "Payment could not be processed for {{studio_name}}",
        "content": (
            "<p>Hi {{owner_name}},</p>"
            "<p>The payment of <strong>{{amount}}</strong> for {{studio_name}} "
            "could not be processed.</p>"
            "<p>{{reason}}</p>"
            "<p>Your workspace is unaffected for now. To avoid interruption, "
            "please settle it by {{grace_until}}.</p>"
            "<p>Reply to this email if you would like help.</p>"
        ),
        "variables": {
            "owner_name": "Studio owner / billing contact",
            "studio_name": "Studio / tenant name",
            "amount": "Amount that failed, pre-formatted with currency",
            "reason": "Plain-language reason from the payment provider",
            "grace_until": "Date access is affected if unpaid",
            "email": "Recipient address — required for the EMAIL channel",
        },
    },
    {
        "event_name": events.SERVICE_NOTICE,
        "name": "Platform — Service Notice",
        "subject": "{{notice_title}}",
        "content": (
            "<p>Hi {{owner_name}},</p>"
            "<p>{{notice_body}}</p>"
            "<p>{{notice_action}}</p>"
        ),
        "variables": {
            "owner_name": "Studio owner / primary admin",
            "notice_title": "Used as the subject line — keep it short and specific",
            "notice_body": "Body of the notice",
            "notice_action": "What the recipient should do, if anything",
            "email": "Recipient address — required for the EMAIL channel",
        },
    },
]


class Command(BaseCommand):
    help = "Seed ANJASI's own MessageTemplates and TriggerRules on the platform tenant."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be created without writing anything.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        try:
            tenant = get_platform_tenant()
        except PlatformTenantMissing as exc:
            raise CommandError(f"{exc}")

        self.stdout.write(
            f"Platform tenant: {tenant.name} ({tenant.subdomain})"
        )

        created_templates = 0
        created_rules = 0
        existing = 0

        for defn in PLATFORM_TEMPLATES:
            if dry_run:
                already = MessageTemplate.base_objects.filter(
                    tenant=tenant, name=defn["name"]
                ).exists()
                verb = "exists, would skip" if already else "would create"
                self.stdout.write(f"  [dry-run] {defn['name']}: {verb}")
                continue

            tpl, tpl_created = MessageTemplate.base_objects.get_or_create(
                tenant=tenant,
                name=defn["name"],
                defaults={
                    "channel": Channel.EMAIL,
                    "subject": defn["subject"],
                    "content": defn["content"],
                    "variables": defn["variables"],
                    "is_active": True,
                },
            )
            if tpl_created:
                created_templates += 1
                self.stdout.write(f"  + template: {defn['name']}")
            else:
                existing += 1

            _, rule_created = TriggerRule.base_objects.get_or_create(
                tenant=tenant,
                event_name=defn["event_name"],
                template=tpl,
                defaults={"conditions": {}, "is_active": True},
            )
            if rule_created:
                created_rules += 1
                self.stdout.write(f"  + rule:     {defn['event_name']}")

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run — nothing written."))
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. {created_templates} templates and {created_rules} rules "
                f"created; {existing} already present."
            )
        )
