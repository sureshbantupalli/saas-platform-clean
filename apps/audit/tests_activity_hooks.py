"""
Tests proving deterministic activity hooks for memberships, bookings, and attendance.

Each important write must always produce an audit log entry — "sometimes yes,
sometimes no" is exactly the consistency failure we're guarding against.

Checklist of covered scenarios:
  Membership:  enrollment → log with membership_id + member_id + plan_name
  Booking:     confirmed create → log; waitlisted create → log
  Booking:     cancellation → log; waitlist promotion → separate log
  Attendance:  bulk mark (booking_service) → log per record
  Attendance:  bulk mark (attendance_service) → log per record

Nothing financial is allowed in any metadata — the guard in log_change catches it.
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.audit.models import AuditModule, SettingsAuditLog
from apps.core.models import Branch, Tenant
from apps.memberships.services import MembershipService


# ── Shared fixtures ───────────────────────────────────────────────────────────

_ctr = [0]


def _uid():
    _ctr[0] += 1
    return _ctr[0]


def _make_tenant():
    n = _uid()
    return Tenant.objects.create(name=f"HookGym{n}", subdomain=f"hookgym{n}")


def _make_branch(tenant):
    return Branch.objects.create(tenant=tenant, name=f"Branch{_uid()}", is_active=True)


def _make_user(tenant):
    from apps.accounts.models import User
    from apps.authority.models import Role
    role = Role.base_objects.create(tenant=tenant, name=f"Role{_uid()}")
    return User.objects.create_user(
        email=f"u{_uid()}@hook.com", password="x",
        tenant=tenant, role=role,
    )


def _make_member(tenant, user):
    from members.models import Member
    return Member.objects.create(
        tenant=tenant, created_by=user,
        first_name="Hook", last_name="Member",
        email=f"m{_uid()}@hook.com",
    )


def _make_active_membership(tenant, member, branch, user):
    today = timezone.now().date()
    member.branches.add(branch)
    return MembershipService.create_membership(
        member=member, branch=branch,
        plan_name="TestPlan", start_date=today - timedelta(days=30),
        end_date=today + timedelta(days=365),
        fee_amount=Decimal("0"), created_by=user, status="active",
    )


def _make_session(tenant, capacity=10):
    from apps.platform_sessions.models import SessionType, SessionInstance
    st = SessionType.objects.create(tenant=tenant, name=f"ST{_uid()}")
    now = timezone.now()
    return SessionInstance.objects.create(
        tenant=tenant, session_type=st,
        start_time=now, end_time=now + timedelta(hours=1),
        capacity=capacity,
    )


def _audit_logs(tenant, module):
    return list(SettingsAuditLog.objects.filter(tenant=tenant, module=module).order_by("timestamp"))


# ── Membership enrollment ─────────────────────────────────────────────────────

class MembershipEnrollmentAuditTests(TestCase):

    def setUp(self):
        self.tenant = _make_tenant()
        self.branch = _make_branch(self.tenant)
        self.user   = _make_user(self.tenant)
        self.member = _make_member(self.tenant, self.user)

    def test_enrollment_creates_audit_log(self):
        with self.captureOnCommitCallbacks(execute=True):
            _make_active_membership(self.tenant, self.member, self.branch, self.user)
        logs = _audit_logs(self.tenant, AuditModule.MEMBERSHIPS)
        self.assertEqual(len(logs), 1)

    def test_log_module_and_action(self):
        with self.captureOnCommitCallbacks(execute=True):
            _make_active_membership(self.tenant, self.member, self.branch, self.user)
        log = _audit_logs(self.tenant, AuditModule.MEMBERSHIPS)[0]
        self.assertEqual(log.module, AuditModule.MEMBERSHIPS)
        self.assertEqual(log.action, 'create')

    def test_log_has_membership_reference(self):
        with self.captureOnCommitCallbacks(execute=True):
            membership = _make_active_membership(self.tenant, self.member, self.branch, self.user)
        log = _audit_logs(self.tenant, AuditModule.MEMBERSHIPS)[0]
        self.assertEqual(log.metadata['membership_id'], str(membership.id))
        self.assertEqual(log.metadata['member_id'],     str(self.member.id))
        self.assertIn('plan_name', log.metadata)

    def test_log_has_status_as_new_value(self):
        with self.captureOnCommitCallbacks(execute=True):
            _make_active_membership(self.tenant, self.member, self.branch, self.user)
        log = _audit_logs(self.tenant, AuditModule.MEMBERSHIPS)[0]
        self.assertEqual(log.new_value, 'active')

    def test_log_does_not_contain_fee_amount(self):
        with self.captureOnCommitCallbacks(execute=True):
            _make_active_membership(self.tenant, self.member, self.branch, self.user)
        log = _audit_logs(self.tenant, AuditModule.MEMBERSHIPS)[0]
        self.assertNotIn('fee_amount', log.metadata)
        self.assertNotIn('amount',     log.metadata)

    def test_created_by_is_logged_as_user(self):
        with self.captureOnCommitCallbacks(execute=True):
            _make_active_membership(self.tenant, self.member, self.branch, self.user)
        log = _audit_logs(self.tenant, AuditModule.MEMBERSHIPS)[0]
        self.assertEqual(log.user_id, self.user.id)


# ── Booking creation ──────────────────────────────────────────────────────────

class BookingCreationAuditTests(TestCase):

    def setUp(self):
        self.tenant = _make_tenant()
        self.branch = _make_branch(self.tenant)
        self.user   = _make_user(self.tenant)
        self.member = _make_member(self.tenant, self.user)
        with self.captureOnCommitCallbacks(execute=True):
            self.membership = _make_active_membership(
                self.tenant, self.member, self.branch, self.user,
            )
        self.session = _make_session(self.tenant, capacity=10)

    def _create_booking(self, member=None):
        from apps.bookings.services.booking_service import create_booking
        m = member or self.member
        return create_booking(
            tenant=self.tenant,
            data={'member_id': str(m.id), 'schedule_id': str(self.session.id)},
        )

    def test_confirmed_booking_creates_audit_log(self):
        with self.captureOnCommitCallbacks(execute=True):
            self._create_booking()
        logs = _audit_logs(self.tenant, AuditModule.BOOKINGS)
        self.assertEqual(len(logs), 1)

    def test_log_action_is_create(self):
        with self.captureOnCommitCallbacks(execute=True):
            self._create_booking()
        log = _audit_logs(self.tenant, AuditModule.BOOKINGS)[0]
        self.assertEqual(log.action, 'create')

    def test_log_has_booking_reference(self):
        with self.captureOnCommitCallbacks(execute=True):
            booking = self._create_booking()
        log = _audit_logs(self.tenant, AuditModule.BOOKINGS)[0]
        self.assertEqual(log.metadata['booking_id'], str(booking.id))
        self.assertEqual(log.metadata['member_id'],  str(self.member.id))
        self.assertEqual(log.metadata['session_id'], str(self.session.id))

    def test_confirmed_status_recorded(self):
        with self.captureOnCommitCallbacks(execute=True):
            self._create_booking()
        log = _audit_logs(self.tenant, AuditModule.BOOKINGS)[0]
        self.assertIn('CONFIRMED', log.new_value)

    def test_waitlisted_booking_also_creates_audit_log(self):
        """Waitlisted bookings are real events — they must be logged too."""
        # Fill the session to capacity first
        for _ in range(self.session.capacity):
            extra_user   = _make_user(self.tenant)
            extra_member = _make_member(self.tenant, extra_user)
            extra_member.branches.add(self.branch)
            with self.captureOnCommitCallbacks(execute=True):
                _make_active_membership(
                    self.tenant, extra_member, self.branch, extra_user,
                )
            with self.captureOnCommitCallbacks(execute=True):
                self._create_booking(member=extra_member)

        # Now our member gets waitlisted
        with self.captureOnCommitCallbacks(execute=True):
            self._create_booking()

        our_log = (
            SettingsAuditLog.objects
            .filter(tenant=self.tenant, module=AuditModule.BOOKINGS,
                    metadata__icontains=str(self.member.id))
            .first()
        )
        self.assertIsNotNone(our_log)
        self.assertIn('WAITLISTED', our_log.new_value)


# ── Booking cancellation and waitlist promotion ───────────────────────────────

class BookingCancellationAuditTests(TestCase):

    def setUp(self):
        self.tenant  = _make_tenant()
        self.branch  = _make_branch(self.tenant)
        self.user    = _make_user(self.tenant)
        self.member  = _make_member(self.tenant, self.user)
        self.session = _make_session(self.tenant, capacity=1)

        with self.captureOnCommitCallbacks(execute=True):
            _make_active_membership(self.tenant, self.member, self.branch, self.user)
        with self.captureOnCommitCallbacks(execute=True):
            from apps.bookings.services.booking_service import create_booking
            self.booking = create_booking(
                tenant=self.tenant,
                data={'member_id': str(self.member.id), 'schedule_id': str(self.session.id)},
            )

    def test_cancellation_creates_audit_log(self):
        from apps.bookings.services.booking_service import cancel_booking
        with self.captureOnCommitCallbacks(execute=True):
            cancel_booking(self.booking)
        cancel_logs = SettingsAuditLog.objects.filter(
            tenant=self.tenant, module=AuditModule.BOOKINGS, action='update',
        )
        self.assertGreaterEqual(cancel_logs.count(), 1)

    def test_cancellation_log_records_status_transition(self):
        from apps.bookings.services.booking_service import cancel_booking
        with self.captureOnCommitCallbacks(execute=True):
            cancel_booking(self.booking)
        log = SettingsAuditLog.objects.filter(
            tenant=self.tenant, module=AuditModule.BOOKINGS, action='update',
            metadata__icontains=str(self.booking.id),
        ).first()
        self.assertIsNotNone(log)
        self.assertIn('CANCELLED', log.new_value)
        self.assertEqual(log.metadata['booking_id'], str(self.booking.id))

    def test_waitlist_promotion_creates_separate_log(self):
        """When a cancellation triggers a waitlist promotion, two update logs are written."""
        # Create a second member who will be waitlisted (capacity=1, already taken)
        user2   = _make_user(self.tenant)
        member2 = _make_member(self.tenant, user2)
        with self.captureOnCommitCallbacks(execute=True):
            _make_active_membership(self.tenant, member2, self.branch, user2)
        with self.captureOnCommitCallbacks(execute=True):
            from apps.bookings.services.booking_service import create_booking
            waitlisted = create_booking(
                tenant=self.tenant,
                data={'member_id': str(member2.id), 'schedule_id': str(self.session.id)},
            )

        # Cancel the confirmed booking → should promote waitlisted → 2 update logs
        from apps.bookings.services.booking_service import cancel_booking
        with self.captureOnCommitCallbacks(execute=True):
            cancel_booking(self.booking)

        update_logs = list(SettingsAuditLog.objects.filter(
            tenant=self.tenant, module=AuditModule.BOOKINGS, action='update',
        ))
        self.assertEqual(len(update_logs), 2)

        new_values = {log.new_value for log in update_logs}
        self.assertIn('CANCELLED',  new_values)
        self.assertIn('CONFIRMED',  new_values)

        promotion_log = next(l for l in update_logs if 'CONFIRMED' in l.new_value)
        self.assertIn('WAITLISTED', promotion_log.old_value)
        self.assertEqual(promotion_log.metadata['booking_id'], str(waitlisted.id))


# ── Attendance marking ────────────────────────────────────────────────────────

class AttendanceAuditTests(TestCase):
    """
    Two separate attendance code paths: booking_service.mark_bulk_attendance
    and attendance_service.bulk_mark_attendance.  Both must produce audit logs.
    """

    def setUp(self):
        self.tenant  = _make_tenant()
        self.branch  = _make_branch(self.tenant)
        self.user    = _make_user(self.tenant)
        self.member  = _make_member(self.tenant, self.user)
        self.session = _make_session(self.tenant)

        with self.captureOnCommitCallbacks(execute=True):
            _make_active_membership(self.tenant, self.member, self.branch, self.user)
        with self.captureOnCommitCallbacks(execute=True):
            from apps.bookings.services.booking_service import create_booking
            self.booking = create_booking(
                tenant=self.tenant,
                data={'member_id': str(self.member.id), 'schedule_id': str(self.session.id)},
            )

    def test_booking_service_attendance_creates_audit_log(self):
        from apps.bookings.services.booking_service import mark_bulk_attendance
        mark_bulk_attendance(
            tenant=self.tenant,
            booking_ids=[str(self.booking.id)],
            status='present',
        )
        logs = _audit_logs(self.tenant, AuditModule.ATTENDANCE)
        self.assertEqual(len(logs), 1)

    def test_booking_service_attendance_log_has_references(self):
        from apps.bookings.services.booking_service import mark_bulk_attendance
        mark_bulk_attendance(
            tenant=self.tenant,
            booking_ids=[str(self.booking.id)],
            status='present',
        )
        log = _audit_logs(self.tenant, AuditModule.ATTENDANCE)[0]
        self.assertIn('attendance_id', log.metadata)
        self.assertEqual(log.metadata['booking_id'], str(self.booking.id))
        self.assertEqual(log.metadata['member_id'],  str(self.member.id))
        self.assertEqual(log.new_value, 'present')

    def test_booking_service_no_show_also_logged(self):
        from apps.bookings.services.booking_service import mark_bulk_attendance
        mark_bulk_attendance(
            tenant=self.tenant,
            booking_ids=[str(self.booking.id)],
            status='no_show',
        )
        log = _audit_logs(self.tenant, AuditModule.ATTENDANCE)[0]
        self.assertEqual(log.new_value, 'no_show')

    def test_attendance_service_bulk_mark_creates_audit_log(self):
        from apps.attendance.services.attendance_service import bulk_mark_attendance
        bulk_mark_attendance(
            session=self.session,
            member_ids=[str(self.member.id)],
            tenant=self.tenant,
            marked_by=self.user,
        )
        logs = _audit_logs(self.tenant, AuditModule.ATTENDANCE)
        self.assertEqual(len(logs), 1)

    def test_attendance_service_log_has_references(self):
        from apps.attendance.services.attendance_service import bulk_mark_attendance
        bulk_mark_attendance(
            session=self.session,
            member_ids=[str(self.member.id)],
            tenant=self.tenant,
            marked_by=self.user,
        )
        log = _audit_logs(self.tenant, AuditModule.ATTENDANCE)[0]
        self.assertIn('attendance_id', log.metadata)
        self.assertEqual(log.metadata['member_id'],  str(self.member.id))
        self.assertEqual(log.metadata['session_id'], str(self.session.id))

    def test_attendance_log_records_marker_as_user(self):
        from apps.attendance.services.attendance_service import bulk_mark_attendance
        bulk_mark_attendance(
            session=self.session,
            member_ids=[str(self.member.id)],
            tenant=self.tenant,
            marked_by=self.user,
        )
        log = _audit_logs(self.tenant, AuditModule.ATTENDANCE)[0]
        self.assertEqual(log.user_id, self.user.id)
        self.assertEqual(log.source, 'user')

    def test_audit_log_contains_no_financial_data(self):
        """Attendance logs must never contain prices or amounts."""
        from apps.bookings.services.booking_service import mark_bulk_attendance
        mark_bulk_attendance(
            tenant=self.tenant,
            booking_ids=[str(self.booking.id)],
            status='present',
        )
        log = _audit_logs(self.tenant, AuditModule.ATTENDANCE)[0]
        for bad_key in ('amount', 'gst_amount', 'gst_rate', 'price', 'fee'):
            self.assertNotIn(bad_key, log.metadata, msg=f"Found financial key '{bad_key}' in metadata")


# ── Membership status updates ─────────────────────────────────────────────────

class MembershipUpdateAuditTests(TestCase):
    """
    Every membership status transition must emit exactly one update audit entry.
    Three paths: payment_success signal, payment_failed signal, lifecycle command.
    """

    def setUp(self):
        self.tenant = _make_tenant()
        self.branch = _make_branch(self.tenant)
        self.user   = _make_user(self.tenant)
        self.member = _make_member(self.tenant, self.user)

    def _make_pending_membership(self):
        """Non-zero fee membership so payment_status stays unpaid → status=pending."""
        from apps.memberships.models import Membership
        today = timezone.now().date()
        self.member.branches.add(self.branch)
        return Membership.base_objects.create(
            tenant=self.tenant,
            member=self.member,
            branch=self.branch,
            plan_name="Test Plan",
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=30),
            fee_amount=Decimal("1000"),
            created_by=self.user,
        )

    def _update_logs(self):
        return [l for l in _audit_logs(self.tenant, AuditModule.MEMBERSHIPS)
                if l.action == 'update']

    def test_payment_success_pending_to_active_emits_audit(self):
        from apps.payments.models import Payment, PaymentStatus
        from apps.payments.signals import payment_success
        membership = self._make_pending_membership()
        payment = Payment.base_objects.create(
            tenant=self.tenant,
            amount=Decimal("1000"),
            status=PaymentStatus.SUCCESS,
            reference_type="membership",
            reference_id=membership.pk,
        )
        with self.captureOnCommitCallbacks(execute=True):
            payment_success.send(sender=Payment, payment=payment)
        logs = self._update_logs()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].old_value, 'pending')
        self.assertEqual(logs[0].new_value, 'active')
        self.assertEqual(logs[0].metadata['membership_id'], str(membership.pk))

    def test_payment_failed_pending_to_cancelled_emits_audit(self):
        from apps.payments.models import Payment, PaymentStatus
        from apps.payments.signals import payment_failed
        membership = self._make_pending_membership()
        payment = Payment.base_objects.create(
            tenant=self.tenant,
            amount=Decimal("1000"),
            status=PaymentStatus.FAILED,
            reference_type="membership",
            reference_id=membership.pk,
        )
        with self.captureOnCommitCallbacks(execute=True):
            payment_failed.send(sender=Payment, payment=payment)
        logs = self._update_logs()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].old_value, 'pending')
        self.assertEqual(logs[0].new_value, 'cancelled')
        self.assertEqual(logs[0].metadata['membership_id'], str(membership.pk))

    def test_lifecycle_active_to_expired_emits_audit(self):
        from django.core.management import call_command
        from apps.memberships.models import Membership
        with self.captureOnCommitCallbacks(execute=True):
            membership = _make_active_membership(
                self.tenant, self.member, self.branch, self.user,
            )
        # Force end_date into the past — use .update() to bypass save hooks
        Membership.base_objects.filter(pk=membership.pk).update(
            end_date=timezone.now().date() - timedelta(days=1),
        )
        with self.captureOnCommitCallbacks(execute=True):
            call_command("run_lifecycle_updates", verbosity=0)
        logs = self._update_logs()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].old_value, 'active')
        self.assertEqual(logs[0].new_value, 'expired')

    def test_no_audit_when_status_unchanged(self):
        """Re-firing payment_success on an already-active membership must not double-log."""
        from apps.payments.models import Payment, PaymentStatus
        from apps.payments.signals import payment_success
        with self.captureOnCommitCallbacks(execute=True):
            membership = _make_active_membership(
                self.tenant, self.member, self.branch, self.user,
            )
        # membership is already active; a second payment_success must not add an update log
        payment = Payment.base_objects.create(
            tenant=self.tenant,
            amount=Decimal("0"),
            status=PaymentStatus.SUCCESS,
            reference_type="membership",
            reference_id=membership.pk,
        )
        with self.captureOnCommitCallbacks(execute=True):
            payment_success.send(sender=Payment, payment=payment)
        self.assertEqual(len(self._update_logs()), 0)
