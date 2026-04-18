"""
management command: seed_comms_defaults

Creates default MessageTemplates and TriggerRules for every active tenant.
Safe to run multiple times — uses get_or_create so existing records are preserved.

Usage:
    python manage.py seed_comms_defaults
    python manage.py seed_comms_defaults --tenant <subdomain>   # single tenant
"""
from django.core.management.base import BaseCommand

from apps.communications.models import Channel, MessageTemplate, TriggerRule


# ── Default event → template definitions ──────────────────────────────────────
#
# Each entry describes one (event, channel, template) triple.
# These are the minimum set to make the system feel alive out of the box.
# Tenants can edit content or disable rules anytime via the UI.

DEFAULTS = [
    {
        "event_name": "payment_success",
        "channel":    Channel.SMS,
        "name":       "Payment Success — SMS",
        "content":    (
            "Hi {{member_name}}, your payment of ₹{{amount}} has been received. "
            "Thank you for your payment!"
        ),
        "conditions": {},
    },
    {
        "event_name": "payment_failed",
        "channel":    Channel.SMS,
        "name":       "Payment Failed — SMS",
        "content":    (
            "Hi {{member_name}}, your payment of ₹{{amount}} could not be processed. "
            "Please retry or contact us for help."
        ),
        "conditions": {},
    },
    {
        "event_name": "booking_confirmed",
        "channel":    Channel.SMS,
        "name":       "Booking Confirmed — SMS",
        "content":    (
            "Hi {{member_name}}, your {{session_type}} session is confirmed for "
            "{{session_date}} at {{session_time}}. See you there!"
        ),
        "conditions": {},
    },
    {
        "event_name": "attendance_marked",
        "channel":    Channel.SMS,
        "name":       "Attendance Marked — SMS",
        "content":    (
            "Hi {{member_name}}, your attendance for {{session_date}} has been recorded. "
            "Keep up the great work!"
        ),
        "conditions": {},
    },
    {
        "event_name": "session_missed",
        "channel":    Channel.SMS,
        "name":       "Session Missed — SMS",
        "content":    (
            "Hi {{member_name}}, we missed you at your {{session_type}} session on "
            "{{session_date}}. Book your next session to stay on track!"
        ),
        "conditions": {},
    },
    {
        "event_name": "session_reminder",
        "channel":    Channel.SMS,
        "name":       "Session Reminder — SMS",
        "content":    (
            "Reminder: Hi {{member_name}}, you have a {{session_type}} session today "
            "at {{session_time}}. Don't miss it!"
        ),
        "conditions": {},
    },
    {
        "event_name": "membership_expiring",
        "channel":    Channel.SMS,
        "name":       "Membership Expiry Reminder — SMS",
        "content":    (
            "Hi {{member_name}}, your {{plan_name}} membership expires on {{expiry_date}} "
            "({{days_remaining}} days left). Renew now to keep your access!"
        ),
        "conditions": {},
    },
]


class Command(BaseCommand):
    help = "Seed default communication templates and trigger rules for all tenants."

    def add_arguments(self, parser):
        parser.add_argument(
            "--tenant",
            type=str,
            default=None,
            help="Subdomain of a specific tenant to seed (default: all tenants).",
        )

    def handle(self, *args, **options):
        from apps.core.models import Tenant

        target_subdomain = options.get("tenant")

        qs = Tenant.objects.filter(is_active=True)
        if target_subdomain:
            qs = qs.filter(subdomain=target_subdomain)
            if not qs.exists():
                self.stderr.write(self.style.ERROR(f"Tenant '{target_subdomain}' not found."))
                return

        created_templates  = 0
        created_rules      = 0

        for tenant in qs:
            self.stdout.write(f"  Seeding tenant: {tenant.name} ({tenant.subdomain})")
            for defn in DEFAULTS:
                tpl, tpl_created = MessageTemplate.base_objects.get_or_create(
                    tenant   = tenant,
                    name     = defn["name"],
                    defaults = {
                        "channel":   defn["channel"],
                        "content":   defn["content"],
                        "is_active": True,
                    },
                )
                if tpl_created:
                    created_templates += 1

                rule, rule_created = TriggerRule.base_objects.get_or_create(
                    tenant     = tenant,
                    event_name = defn["event_name"],
                    template   = tpl,
                    defaults   = {
                        "conditions": defn.get("conditions", {}),
                        "is_active":  True,
                    },
                )
                if rule_created:
                    created_rules += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Created {created_templates} templates, {created_rules} trigger rules."
            )
        )
