"""
Phase 5.1 — Payment Intelligence tests.

Pure unit tests: no DB, no Django test fixtures.
Payment objects are SimpleNamespace stubs so the suite runs fast and
in full isolation from the rest of the payment tests.
"""

import unittest
import zoneinfo
from datetime import date, datetime, timezone as dt_tz
from types import SimpleNamespace

from apps.payments.services.payment_service import PaymentService, PaymentTimingStatus


# ── Stubs ─────────────────────────────────────────────────────────────────────

def _paid(paid_date: date, *, hour: int = 12, tz=dt_tz.utc):
    """Stub for a paid payment at the given time (default noon UTC)."""
    return SimpleNamespace(
        paid_at=datetime(paid_date.year, paid_date.month, paid_date.day,
                         hour, 0, tzinfo=tz),
    )


def _unpaid():
    """Stub for a payment that has not been paid."""
    return SimpleNamespace(paid_at=None)


# ── get_payment_status ────────────────────────────────────────────────────────

class TestGetPaymentStatus(unittest.TestCase):

    def setUp(self):
        self.due = date(2026, 4, 15)

    def test_on_time_payment(self):
        self.assertEqual(
            PaymentService.get_payment_status(_paid(date(2026, 4, 15)), due_date=self.due),
            PaymentTimingStatus.ON_TIME,
        )

    def test_on_time_payment_early(self):
        self.assertEqual(
            PaymentService.get_payment_status(_paid(date(2026, 4, 13)), due_date=self.due),
            PaymentTimingStatus.ON_TIME,
        )

    def test_late_payment(self):
        self.assertEqual(
            PaymentService.get_payment_status(_paid(date(2026, 4, 20)), due_date=self.due),
            PaymentTimingStatus.LATE,
        )

    def test_pending_payment(self):
        future_due = date(2099, 12, 31)
        self.assertEqual(
            PaymentService.get_payment_status(_unpaid(), due_date=future_due),
            PaymentTimingStatus.PENDING,
        )

    def test_overdue_payment(self):
        past_due = date(2000, 1, 1)
        self.assertEqual(
            PaymentService.get_payment_status(_unpaid(), due_date=past_due),
            PaymentTimingStatus.OVERDUE,
        )

    def test_none_due_date_raises(self):
        with self.assertRaises(ValueError):
            PaymentService.get_payment_status(_paid(date(2026, 4, 15)), due_date=None)

    def test_timezone_normalization_near_midnight(self):
        """
        11:30 PM UTC on Apr 15 is Apr 16 in IST (UTC+5:30).
        The same instant must classify as ON_TIME in UTC and LATE in IST.
        """
        ist = zoneinfo.ZoneInfo('Asia/Kolkata')
        # 23:30 UTC Apr 15 = 05:00 IST Apr 16
        paid_utc = datetime(2026, 4, 15, 23, 30, tzinfo=dt_tz.utc)
        p = SimpleNamespace(paid_at=paid_utc)

        self.assertEqual(
            PaymentService.get_payment_status(p, due_date=date(2026, 4, 15), tz=dt_tz.utc),
            PaymentTimingStatus.ON_TIME,
        )
        self.assertEqual(
            PaymentService.get_payment_status(p, due_date=date(2026, 4, 15), tz=ist),
            PaymentTimingStatus.LATE,
        )


# ── get_days_to_pay ───────────────────────────────────────────────────────────

class TestGetDaysToPay(unittest.TestCase):

    def setUp(self):
        self.due = date(2026, 4, 15)

    def test_days_to_pay_early(self):
        self.assertEqual(
            PaymentService.get_days_to_pay(_paid(date(2026, 4, 12)), due_date=self.due),
            -3,
        )

    def test_days_to_pay_on_due_date(self):
        self.assertEqual(
            PaymentService.get_days_to_pay(_paid(date(2026, 4, 15)), due_date=self.due),
            0,
        )

    def test_days_to_pay_late(self):
        self.assertEqual(
            PaymentService.get_days_to_pay(_paid(date(2026, 4, 20)), due_date=self.due),
            5,
        )

    def test_days_to_pay_unpaid_returns_none(self):
        self.assertIsNone(
            PaymentService.get_days_to_pay(_unpaid(), due_date=self.due),
        )

    def test_none_due_date_raises(self):
        with self.assertRaises(ValueError):
            PaymentService.get_days_to_pay(_paid(date(2026, 4, 15)), due_date=None)


# ── is_late ───────────────────────────────────────────────────────────────────

class TestIsLate(unittest.TestCase):

    def setUp(self):
        self.due = date(2026, 4, 15)

    def test_is_late_true(self):
        self.assertTrue(
            PaymentService.is_late(_paid(date(2026, 4, 16)), due_date=self.due),
        )

    def test_is_late_false_on_time(self):
        self.assertFalse(
            PaymentService.is_late(_paid(date(2026, 4, 15)), due_date=self.due),
        )

    def test_is_late_false_early(self):
        self.assertFalse(
            PaymentService.is_late(_paid(date(2026, 4, 10)), due_date=self.due),
        )

    def test_is_late_false_unpaid(self):
        # Unpaid ≠ late — use get_payment_status for the OVERDUE distinction
        self.assertFalse(
            PaymentService.is_late(_unpaid(), due_date=self.due),
        )

    def test_none_due_date_raises(self):
        with self.assertRaises(ValueError):
            PaymentService.is_late(_paid(date(2026, 4, 15)), due_date=None)

    def test_timezone_normalization_is_late(self):
        """Same UTC instant should flip is_late across timezone boundary."""
        ist = zoneinfo.ZoneInfo('Asia/Kolkata')
        paid_utc = datetime(2026, 4, 15, 23, 30, tzinfo=dt_tz.utc)
        p = SimpleNamespace(paid_at=paid_utc)

        self.assertFalse(PaymentService.is_late(p, due_date=date(2026, 4, 15), tz=dt_tz.utc))
        self.assertTrue(PaymentService.is_late(p, due_date=date(2026, 4, 15), tz=ist))
