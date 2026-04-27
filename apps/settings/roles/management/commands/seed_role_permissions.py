from django.core.management.base import BaseCommand

from apps.settings.roles.models import Permission

# ── Permission registry ────────────────────────────────────────────────────────
# Format: {code, label, module, description, depends_on: [codes]}
# depends_on is resolved in a second pass so order does not matter.

PERMISSIONS = [
    # ── CRM ───────────────────────────────────────────────────────
    {
        'code': 'crm.view_enquiries',
        'label': 'View Enquiries',
        'module': 'crm',
        'description': 'View the enquiry list and individual enquiry details.',
        'depends_on': [],
    },
    {
        'code': 'crm.edit_enquiries',
        'label': 'Edit Enquiries',
        'module': 'crm',
        'description': 'Create and update enquiry records.',
        'depends_on': ['crm.view_enquiries'],
    },
    {
        'code': 'crm.delete_enquiries',
        'label': 'Delete Enquiries',
        'module': 'crm',
        'description': 'Permanently delete enquiries from the system.',
        'depends_on': ['crm.edit_enquiries'],
    },
    {
        'code': 'crm.convert_lead',
        'label': 'Convert Lead to Member',
        'module': 'crm',
        'description': 'Mark an enquiry as converted and create a member record.',
        'depends_on': ['crm.edit_enquiries'],
    },
    {
        'code': 'crm.manage_stages',
        'label': 'Manage Pipeline Stages',
        'module': 'crm',
        'description': 'Create, reorder, and delete CRM pipeline stages.',
        'depends_on': ['crm.view_enquiries'],
    },
    # ── Payments ──────────────────────────────────────────────────
    {
        'code': 'payments.view',
        'label': 'View Payments',
        'module': 'payments',
        'description': 'View payment records and transaction history.',
        'depends_on': [],
    },
    {
        'code': 'payments.collect',
        'label': 'Collect Payments',
        'module': 'payments',
        'description': 'Record and process new payments.',
        'depends_on': ['payments.view'],
    },
    {
        'code': 'payments.refund',
        'label': 'Issue Refunds',
        'module': 'payments',
        'description': 'Process full or partial payment refunds.',
        'depends_on': ['payments.collect'],
    },
    # ── Members ───────────────────────────────────────────────────
    {
        'code': 'members.view',
        'label': 'View Members',
        'module': 'members',
        'description': 'View member list and individual profiles.',
        'depends_on': [],
    },
    {
        'code': 'members.edit',
        'label': 'Edit Members',
        'module': 'members',
        'description': 'Create and update member profiles.',
        'depends_on': ['members.view'],
    },
    {
        'code': 'members.delete',
        'label': 'Delete Members',
        'module': 'members',
        'description': 'Remove members from the system.',
        'depends_on': ['members.edit'],
    },
    # ── Memberships ───────────────────────────────────────────────
    {
        'code': 'memberships.view',
        'label': 'View Memberships',
        'module': 'memberships',
        'description': 'View active memberships and plan details.',
        'depends_on': [],
    },
    {
        'code': 'memberships.assign',
        'label': 'Assign Memberships',
        'module': 'memberships',
        'description': 'Assign membership plans to members.',
        'depends_on': ['memberships.view'],
    },
    {
        'code': 'memberships.manage_plans',
        'label': 'Manage Plans',
        'module': 'memberships',
        'description': 'Create and edit membership plan templates.',
        'depends_on': ['memberships.view'],
    },
    # ── Sessions ──────────────────────────────────────────────────
    {
        'code': 'sessions.view',
        'label': 'View Sessions',
        'module': 'sessions',
        'description': 'View the session calendar and schedules.',
        'depends_on': [],
    },
    {
        'code': 'sessions.manage',
        'label': 'Manage Sessions',
        'module': 'sessions',
        'description': 'Create and edit session templates, schedules, and instances.',
        'depends_on': ['sessions.view'],
    },
    # ── Attendance ────────────────────────────────────────────────
    {
        'code': 'attendance.view',
        'label': 'View Attendance',
        'module': 'attendance',
        'description': 'View attendance records across all sessions.',
        'depends_on': [],
    },
    {
        'code': 'attendance.mark',
        'label': 'Mark Attendance',
        'module': 'attendance',
        'description': 'Record attendance for session participants.',
        'depends_on': ['attendance.view'],
    },
    # ── Bookings ──────────────────────────────────────────────────
    {
        'code': 'bookings.view',
        'label': 'View Bookings',
        'module': 'bookings',
        'description': 'View all booking records.',
        'depends_on': [],
    },
    {
        'code': 'bookings.manage',
        'label': 'Manage Bookings',
        'module': 'bookings',
        'description': 'Create, cancel, and update bookings.',
        'depends_on': ['bookings.view'],
    },
    # ── Settings / RBAC ───────────────────────────────────────────
    {
        'code': 'settings.view_roles',
        'label': 'View Roles',
        'module': 'settings',
        'description': 'View role definitions and their permission assignments.',
        'depends_on': [],
    },
    {
        'code': 'settings.manage_roles',
        'label': 'Manage Roles',
        'module': 'settings',
        'description': 'Create, edit, and assign roles and permissions.',
        'depends_on': ['settings.view_roles'],
    },
]


class Command(BaseCommand):
    help = 'Seed the permission catalogue from the built-in registry.'

    def handle(self, *args, **options):
        created = updated = 0

        # Pass 1: upsert each permission (without dependencies)
        perm_map: dict[str, Permission] = {}
        for entry in PERMISSIONS:
            perm, was_created = Permission.objects.update_or_create(
                code=entry['code'],
                defaults={
                    'label':       entry['label'],
                    'module':      entry['module'],
                    'description': entry['description'],
                },
            )
            perm_map[perm.code] = perm
            if was_created:
                created += 1
            else:
                updated += 1

        # Pass 2: wire up depends_on relationships
        for entry in PERMISSIONS:
            perm = perm_map[entry['code']]
            deps = [perm_map[c] for c in entry['depends_on'] if c in perm_map]
            perm.depends_on.set(deps)

        self.stdout.write(
            self.style.SUCCESS(
                f'Permissions seeded: {created} created, {updated} updated '
                f'({len(PERMISSIONS)} total).'
            )
        )
