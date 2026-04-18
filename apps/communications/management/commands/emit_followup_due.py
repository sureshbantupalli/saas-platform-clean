"""
management command: emit_followup_due

Finds all pending CRM follow-ups that are due today or overdue and emits
a `followup_due` event for each one so the communications module can send
the configured WhatsApp/SMS/email message.

Designed to run as a scheduled job (cron, Celery beat, etc.):
    python manage.py emit_followup_due          # all tenants
    python manage.py emit_followup_due --dry-run
"""
import logging
from datetime import date

from django.core.management.base import BaseCommand

from apps.communications.services.communication_service import handle_event

logger = logging.getLogger("apps.communications")


class Command(BaseCommand):
    help = "Emit followup_due events for pending CRM follow-ups due today or overdue."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be emitted without actually sending.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        try:
            from crm.models import FollowUp
        except ImportError:
            self.stderr.write(self.style.ERROR("CRM app not available — nothing to emit."))
            return

        today = date.today()
        due = (
            FollowUp.objects
            .filter(status=FollowUp.STATUS_PENDING, due_date__lte=today)
            .select_related("tenant", "enquiry", "member")
        )

        emitted = 0
        for followup in due:
            payload = _build_payload(followup)
            if dry_run:
                self.stdout.write(
                    f"[dry-run] followup_due tenant={followup.tenant} "
                    f"name={payload.get('name')} phone={payload.get('phone')} "
                    f"due={followup.due_date}"
                )
            else:
                try:
                    handle_event("followup_due", payload, followup.tenant)
                    emitted += 1
                except Exception as exc:
                    logger.exception("emit_followup_due: error for followup=%s: %s", followup.pk, exc)
                    self.stderr.write(f"Error on followup {followup.pk}: {exc}")

        if not dry_run:
            self.stdout.write(self.style.SUCCESS(f"Emitted {emitted} followup_due event(s)."))


def _build_payload(followup) -> dict:
    """Generic payload — Communications module must not need to know about CRM internals."""
    name  = followup.display_name
    phone = followup.phone or ""
    email = ""

    if followup.enquiry:
        email = followup.enquiry.email or ""
    elif followup.member:
        email = getattr(followup.member, "email", "") or ""

    return {
        "reference_type": "followup",
        "reference_id":   str(followup.pk),
        "name":           name,
        "phone":          phone,
        "email":          email,
        "due_date":       str(followup.due_date),
        "followup_type":  followup.get_followup_type_display(),
        "notes":          followup.notes or "",
        "is_overdue":     "yes" if followup.due_date < date.today() else "no",
    }
