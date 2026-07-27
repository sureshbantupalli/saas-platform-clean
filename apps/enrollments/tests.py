"""
Tests for the generic enrollment system.

Checklist:
  Enrollment:  person can enroll in one or many services simultaneously
  Enrollment:  therapy + yoga at the same time — no collision, no data duplication
  Enrollment:  source lineage stored correctly (analytics, not business logic)
  Enrollment:  duplicate active enrollment for same person+service raises
  Activity:    created exactly once per successful enrollment (after commit)
  Activity:    NOT created when enrollment creation rolls back
  Activity:    two separate enrollments → two separate activity entries
  Activity:    reference_type/reference_id point to the enrollment row
"""
import uuid
from datetime import date

from django.db import transaction
from django.test import TestCase

from apps.activity.models import Activity, ActivityType
from apps.enrollments.models import Enrollment
from apps.enrollments.services import enroll_person_in_service


# ── Shared fixtures ───────────────────────────────────────────────────────────

_ctr = [0]


def _uid():
    _ctr[0] += 1
    return _ctr[0]


def _make_tenant():
    from apps.core.models import Tenant
    return Tenant.objects.create(name=f"EnrollGym{_uid()}", subdomain=f"enrollgym{_uid()}")


def _make_branch(tenant):
    from apps.core.models import Branch
    return Branch.objects.create(tenant=tenant, name=f"Branch{_uid()}", is_active=True)


def _make_user(tenant):
    from apps.accounts.models import User
    from apps.authority.models import Role
    role = Role.base_objects.create(tenant=tenant, name=f"Role{_uid()}")
    return User.objects.create_user(
        email=f"u{_uid()}@enroll.com", password="x",
        tenant=tenant, role=role,
    )


def _make_member(tenant, user):
    from members.models import Member
    return Member.objects.create(
        tenant=tenant, created_by=user,
        first_name="Enroll", last_name="Person",
        email=f"m{_uid()}@enroll.com",
    )


def _make_vertical(tenant, name=None):
    from apps.verticals.models import BusinessVertical
    return BusinessVertical.base_objects.create(
        tenant=tenant, name=name or f"Vertical{_uid()}",
    )


def _make_service(tenant, vertical, name=None):
    from apps.catalog.models import Service
    return Service.base_objects.create(
        tenant=tenant, vertical=vertical, name=name or f"Service{_uid()}",
    )


# ── Core enrollment behavior ──────────────────────────────────────────────────

class EnrollmentServiceTests(TestCase):

    def setUp(self):
        self.tenant   = _make_tenant()
        self.branch   = _make_branch(self.tenant)
        self.user     = _make_user(self.tenant)
        self.person   = _make_member(self.tenant, self.user)
        self.vertical = _make_vertical(self.tenant, "Yoga Training")
        self.service  = _make_service(self.tenant, self.vertical, "Monthly Yoga")

    def test_person_can_enroll_in_service(self):
        with self.captureOnCommitCallbacks(execute=True):
            enrollment = enroll_person_in_service(
                person=self.person,
                service=self.service,
                vertical=self.vertical,
                created_by=self.user,
            )
        self.assertEqual(enrollment.status, Enrollment.STATUS_ACTIVE)
        self.assertEqual(enrollment.person,   self.person)
        self.assertEqual(enrollment.service,  self.service)
        self.assertEqual(enrollment.vertical, self.vertical)
        self.assertEqual(enrollment.tenant,   self.tenant)

    def test_therapy_and_yoga_simultaneously(self):
        """Same person can be active in therapy AND yoga — no conversion, no collision."""
        therapy_v = _make_vertical(self.tenant, "Therapy")
        therapy_s = _make_service(self.tenant, therapy_v, "Back Pain Therapy")

        with self.captureOnCommitCallbacks(execute=True):
            yoga    = enroll_person_in_service(
                person=self.person, service=self.service, vertical=self.vertical,
            )
            therapy = enroll_person_in_service(
                person=self.person, service=therapy_s, vertical=therapy_v,
            )

        active = Enrollment.base_objects.filter(person=self.person, status="active")
        self.assertEqual(active.count(), 2)
        self.assertEqual(yoga.vertical.name,    "Yoga Training")
        self.assertEqual(therapy.vertical.name, "Therapy")

    def test_multiple_enrollments_different_services_allowed(self):
        service2 = _make_service(self.tenant, self.vertical, "Private Coaching")

        with self.captureOnCommitCallbacks(execute=True):
            enroll_person_in_service(
                person=self.person, service=self.service, vertical=self.vertical,
            )
            enroll_person_in_service(
                person=self.person, service=service2, vertical=self.vertical,
            )

        self.assertEqual(
            Enrollment.base_objects.filter(person=self.person, status="active").count(), 2,
        )

    def test_no_data_duplication_across_verticals(self):
        """Person row is never modified or duplicated — only Enrollment rows accumulate."""
        from members.models import Member
        therapy_v = _make_vertical(self.tenant, "Therapy2")
        therapy_s = _make_service(self.tenant, therapy_v, "Therapy Plan")

        with self.captureOnCommitCallbacks(execute=True):
            enroll_person_in_service(
                person=self.person, service=self.service, vertical=self.vertical,
            )
            enroll_person_in_service(
                person=self.person, service=therapy_s, vertical=therapy_v,
            )

        self.assertEqual(Member.objects.filter(pk=self.person.pk).count(), 1)
        self.assertEqual(Enrollment.base_objects.filter(person=self.person).count(), 2)

    def test_source_type_and_source_id_stored(self):
        consultation_id = uuid.uuid4()

        with self.captureOnCommitCallbacks(execute=True):
            enrollment = enroll_person_in_service(
                person=self.person,
                service=self.service,
                vertical=self.vertical,
                source={"type": "consultation", "id": consultation_id},
            )

        self.assertEqual(enrollment.source_type, "consultation")
        self.assertEqual(enrollment.source_id,   consultation_id)

    def test_no_source_defaults_to_empty(self):
        with self.captureOnCommitCallbacks(execute=True):
            enrollment = enroll_person_in_service(
                person=self.person, service=self.service, vertical=self.vertical,
            )
        self.assertEqual(enrollment.source_type, "")
        self.assertIsNone(enrollment.source_id)

    def test_start_date_defaults_to_today(self):
        with self.captureOnCommitCallbacks(execute=True):
            enrollment = enroll_person_in_service(
                person=self.person, service=self.service, vertical=self.vertical,
            )
        self.assertEqual(enrollment.start_date, date.today())

    def test_explicit_start_date_honoured(self):
        custom = date(2025, 1, 1)
        with self.captureOnCommitCallbacks(execute=True):
            enrollment = enroll_person_in_service(
                person=self.person, service=self.service, vertical=self.vertical,
                start_date=custom,
            )
        self.assertEqual(enrollment.start_date, custom)

    def test_duplicate_active_enrollment_raises(self):
        with self.captureOnCommitCallbacks(execute=True):
            enroll_person_in_service(
                person=self.person, service=self.service, vertical=self.vertical,
            )
        with self.assertRaises(Exception):
            with transaction.atomic():
                enroll_person_in_service(
                    person=self.person, service=self.service, vertical=self.vertical,
                )

    def test_service_tenant_mismatch_raises(self):
        other_tenant  = _make_tenant()
        other_vertical = _make_vertical(other_tenant, "Other")
        foreign_service = _make_service(other_tenant, other_vertical, "Foreign")
        with self.assertRaises(ValueError):
            enroll_person_in_service(
                person=self.person, service=foreign_service, vertical=self.vertical,
            )

    def test_vertical_tenant_mismatch_raises(self):
        other_tenant   = _make_tenant()
        foreign_vertical = _make_vertical(other_tenant, "Foreign")
        with self.assertRaises(ValueError):
            enroll_person_in_service(
                person=self.person, service=self.service, vertical=foreign_vertical,
            )


# ── Activity timeline integration ─────────────────────────────────────────────

class EnrollmentActivityTests(TestCase):

    def setUp(self):
        self.tenant   = _make_tenant()
        self.branch   = _make_branch(self.tenant)
        self.user     = _make_user(self.tenant)
        self.person   = _make_member(self.tenant, self.user)
        self.vertical = _make_vertical(self.tenant, "Yoga")
        self.service  = _make_service(self.tenant, self.vertical, "Yoga Class")

    def test_activity_created_after_enrollment(self):
        with self.captureOnCommitCallbacks(execute=True):
            enroll_person_in_service(
                person=self.person,
                service=self.service,
                vertical=self.vertical,
                created_by=self.user,
            )
        activities = Activity.base_objects.filter(
            person=self.person, activity_type=ActivityType.ENROLLMENT,
        )
        self.assertEqual(activities.count(), 1)

    def test_activity_has_correct_reference(self):
        with self.captureOnCommitCallbacks(execute=True):
            enrollment = enroll_person_in_service(
                person=self.person, service=self.service, vertical=self.vertical,
            )
        activity = Activity.base_objects.get(
            person=self.person, activity_type=ActivityType.ENROLLMENT,
        )
        self.assertEqual(activity.reference_type, "enrollment")
        self.assertEqual(activity.reference_id,   enrollment.id)
        self.assertIn("Yoga Class", activity.title)
        self.assertEqual(activity.vertical, self.vertical)
        self.assertEqual(activity.tenant,   self.tenant)

    def test_no_activity_on_rollback(self):
        """If the enrollment transaction rolls back, no activity must be created."""
        count_before = Activity.base_objects.filter(person=self.person).count()

        with self.captureOnCommitCallbacks(execute=True):
            try:
                with transaction.atomic():
                    enroll_person_in_service(
                        person=self.person, service=self.service, vertical=self.vertical,
                    )
                    raise ValueError("simulated failure")
            except ValueError:
                pass

        self.assertEqual(
            Activity.base_objects.filter(person=self.person).count(), count_before,
        )
        self.assertEqual(
            Enrollment.base_objects.filter(person=self.person).count(), 0,
        )

    def test_one_activity_per_enrollment(self):
        """Two separate successful enrollments produce exactly two activity entries."""
        service2 = _make_service(self.tenant, self.vertical, "Private Coaching")

        with self.captureOnCommitCallbacks(execute=True):
            enroll_person_in_service(
                person=self.person, service=self.service, vertical=self.vertical,
            )
            enroll_person_in_service(
                person=self.person, service=service2, vertical=self.vertical,
            )

        self.assertEqual(
            Activity.base_objects.filter(
                person=self.person, activity_type=ActivityType.ENROLLMENT,
            ).count(),
            2,
        )

    def test_activity_not_source_of_truth(self):
        """Deleting all activity rows must not affect enrollment count or state."""
        with self.captureOnCommitCallbacks(execute=True):
            enroll_person_in_service(
                person=self.person, service=self.service, vertical=self.vertical,
            )

        enrollment_count = Enrollment.base_objects.filter(person=self.person).count()
        Activity.base_objects.filter(person=self.person).delete()

        self.assertEqual(
            Enrollment.base_objects.filter(person=self.person).count(),
            enrollment_count,
        )
