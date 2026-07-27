from datetime import date, time, timedelta
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.core.models import Tenant, Branch
from apps.authority.models import Role
from members.models import Member
from apps.bookings.models import Booking
from apps.bookings.services.booking_service import create_booking, cancel_booking, confirm_booking
from apps.memberships.models import Membership
from apps.platform_sessions.models import SessionType, SessionInstance


# ============================================================
# Fixtures
# ============================================================

def make_tenant(name="BookingGym"):
    return Tenant.objects.create(name=name, subdomain=name.lower().replace(" ", "-"))


def make_branch(tenant, name="Branch"):
    return Branch.objects.create(tenant=tenant, name=name, is_active=True)


def make_role(tenant, name="Staff"):
    return Role.objects.create(tenant=tenant, name=name)


def make_user(tenant, role, email="user@test.com"):
    return User.objects.create_user(email=email, password="testpass", tenant=tenant, role=role)


def make_member(tenant, user, email="member@test.com"):
    return Member.objects.create(
        tenant=tenant, created_by=user,
        first_name="Test", last_name="Member", email=email,
    )


def make_membership(member, branch, user):
    """Create an active paid membership covering today so create_booking passes."""
    member.branches.add(branch)
    today = timezone.now().date()
    return Membership.objects.create(
        tenant=branch.tenant,
        member=member,
        branch=branch,
        plan_name="Test Plan",
        start_date=today - timedelta(days=30),
        end_date=today + timedelta(days=365),
        payment_status="paid",
        created_by=user,
    )


def make_session(tenant, capacity=10):
    session_type = SessionType.objects.create(
        tenant=tenant, name="Yoga"
    )
    now = timezone.now()
    return SessionInstance.objects.create(
        tenant=tenant,
        session_type=session_type,
        start_time=now,
        end_time=now + timezone.timedelta(hours=1),
        capacity=capacity,
    )


# ============================================================
# Booking Service Tests
# ============================================================

class CreateBookingTest(TestCase):

    def setUp(self):
        self.tenant = make_tenant("BookGym1")
        self.branch = make_branch(self.tenant)
        self.role = make_role(self.tenant)
        self.user = make_user(self.tenant, self.role, "staff@book.com")
        self.member = make_member(self.tenant, self.user, "m1@book.com")
        make_membership(self.member, self.branch, self.user)
        self.session = make_session(self.tenant, capacity=5)

    def test_create_booking_confirmed_when_capacity_available(self):
        booking = create_booking(tenant=self.tenant, data={
            "member_id": str(self.member.pk),
            "schedule_id": str(self.session.pk),
        })
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)
        self.assertEqual(booking.member, self.member)
        self.assertEqual(booking.session, self.session)
        self.assertEqual(booking.tenant, self.tenant)

    def test_create_booking_waitlisted_when_full(self):
        session = make_session(self.tenant, capacity=1)
        # Fill the session
        first_member = make_member(self.tenant, self.user, "first@book.com")
        make_membership(first_member, self.branch, self.user)
        create_booking(tenant=self.tenant, data={
            "member_id": str(first_member.pk),
            "schedule_id": str(session.pk),
        })
        # Second booking should be waitlisted
        second_member = make_member(self.tenant, self.user, "second@book.com")
        make_membership(second_member, self.branch, self.user)
        booking = create_booking(tenant=self.tenant, data={
            "member_id": str(second_member.pk),
            "schedule_id": str(session.pk),
        })
        self.assertEqual(booking.status, Booking.Status.WAITLISTED)

    def test_duplicate_booking_raises_error(self):
        create_booking(tenant=self.tenant, data={
            "member_id": str(self.member.pk),
            "schedule_id": str(self.session.pk),
        })
        with self.assertRaises(ValueError, msg="Booking already exists"):
            create_booking(tenant=self.tenant, data={
                "member_id": str(self.member.pk),
                "schedule_id": str(self.session.pk),
            })

    def test_cross_tenant_member_raises_404(self):
        from django.http import Http404
        tenant2 = make_tenant("OtherGym")
        role2 = make_role(tenant2, "Staff2")
        user2 = make_user(tenant2, role2, "other@book.com")
        other_member = make_member(tenant2, user2, "cross@book.com")

        with self.assertRaises(Exception):
            create_booking(tenant=self.tenant, data={
                "member_id": str(other_member.pk),
                "schedule_id": str(self.session.pk),
            })


class CancelBookingTest(TestCase):

    def setUp(self):
        self.tenant = make_tenant("CancelGym")
        self.branch = make_branch(self.tenant)
        self.role = make_role(self.tenant)
        self.user = make_user(self.tenant, self.role, "cancel_staff@book.com")
        self.session = make_session(self.tenant, capacity=1)

    def test_cancel_booking_changes_status(self):
        member = make_member(self.tenant, self.user, "c1@book.com")
        make_membership(member, self.branch, self.user)
        booking = create_booking(tenant=self.tenant, data={
            "member_id": str(member.pk),
            "schedule_id": str(self.session.pk),
        })
        cancel_booking(booking)
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CANCELLED)

    def test_cancel_promotes_waitlisted_member(self):
        """Cancelling a confirmed booking should auto-confirm the next waitlisted one."""
        session = make_session(self.tenant, capacity=1)

        m1 = make_member(self.tenant, self.user, "promo1@book.com")
        m2 = make_member(self.tenant, self.user, "promo2@book.com")
        make_membership(m1, self.branch, self.user)
        make_membership(m2, self.branch, self.user)

        b1 = create_booking(tenant=self.tenant, data={
            "member_id": str(m1.pk),
            "schedule_id": str(session.pk),
        })
        b2 = create_booking(tenant=self.tenant, data={
            "member_id": str(m2.pk),
            "schedule_id": str(session.pk),
        })

        self.assertEqual(b1.status, Booking.Status.CONFIRMED)
        self.assertEqual(b2.status, Booking.Status.WAITLISTED)

        cancel_booking(b1)
        b2.refresh_from_db()
        self.assertEqual(b2.status, Booking.Status.CONFIRMED)

    def test_no_promotion_when_no_waitlist(self):
        member = make_member(self.tenant, self.user, "nw@book.com")
        make_membership(member, self.branch, self.user)
        booking = create_booking(tenant=self.tenant, data={
            "member_id": str(member.pk),
            "schedule_id": str(self.session.pk),
        })
        cancel_booking(booking)
        # No other bookings — should not raise any error
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CANCELLED)


class ConfirmBookingTest(TestCase):

    def setUp(self):
        self.tenant = make_tenant("ConfirmGym")
        self.branch = make_branch(self.tenant)
        self.role = make_role(self.tenant)
        self.user = make_user(self.tenant, self.role, "conf_staff@book.com")
        self.session = make_session(self.tenant, capacity=5)

    def test_confirm_booking_sets_status(self):
        member = make_member(self.tenant, self.user, "conf@book.com")
        make_membership(member, self.branch, self.user)
        booking = create_booking(tenant=self.tenant, data={
            "member_id": str(member.pk),
            "schedule_id": str(self.session.pk),
        })
        booking.status = Booking.Status.PENDING
        booking.save()
        confirm_booking(booking)
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)
