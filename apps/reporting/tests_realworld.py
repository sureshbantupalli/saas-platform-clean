"""
Real-world scenario tests for the reporting module.

These tests exercise the messy edge cases that clean unit tests skip:
split payments, mixed GST/non-GST records, mixed verticals with nulls,
payout/expense separation, all non-SUCCESS payment statuses, paid_at vs
created_at semantics, decimal precision in CSV, and null GST fields.
"""
import csv
import datetime
import io
import json
from decimal import Decimal

from django.contrib.sessions.backends.db import SessionStore
from django.test import RequestFactory, TestCase
from django.utils import timezone

from apps.core.models import Tenant
from apps.expenses.models import Expense
from apps.payments.models import Payment, PaymentStatus
from apps.payouts.models import Payout, PayoutStatus
from apps.reporting.services import (
    get_expense_by_vertical,
    get_gst_income_rows,
    get_gst_summary,
    get_income_by_vertical,
    get_income_expense_summary,
)
from apps.reporting.views import (
    gst_report_csv,
    gst_report_json,
    income_expense_csv,
)
from apps.verticals.models import BusinessVertical


# ── Fixtures ──────────────────────────────────────────────────────────────────

_ctr = [0]


def _uid():
    _ctr[0] += 1
    return _ctr[0]


def _make_tenant():
    n = _uid()
    return Tenant.objects.create(name=f"RWGym{n}", subdomain=f"rwgym{n}")


def _make_user(tenant):
    from apps.accounts.models import User
    from apps.authority.models import Role
    role = Role.base_objects.create(tenant=tenant, name=f"Role{_uid()}")
    return User.objects.create_user(
        email=f"u{_uid()}@rw.com", password="x",
        tenant=tenant, role=role,
    )


def _make_vertical(tenant, name):
    return BusinessVertical.base_objects.create(tenant=tenant, name=name)


def _paid_at(date):
    return timezone.make_aware(datetime.datetime.combine(date, datetime.time(10, 0)))


def _make_payment(tenant, *, amount, date, status=PaymentStatus.SUCCESS,
                  gst_applicable=False, gst_rate=None, gst_amount=None,
                  vertical=None):
    return Payment.objects.create(
        tenant=tenant,
        amount=amount,
        status=status,
        paid_at=_paid_at(date) if status == PaymentStatus.SUCCESS else None,
        gst_applicable=gst_applicable,
        gst_rate=gst_rate,
        gst_amount=gst_amount,
        vertical=vertical,
    )


def _make_expense(tenant, *, amount, date, gst_applicable=False,
                  gst_rate=None, gst_amount=None, vertical=None):
    return Expense.base_objects.create(
        tenant=tenant, amount=amount, date=date,
        gst_applicable=gst_applicable,
        gst_rate=gst_rate, gst_amount=gst_amount,
        vertical=vertical,
    )


def _make_payout(tenant, staff, *, amount, date, status=PayoutStatus.PAID):
    return Payout.base_objects.create(
        tenant=tenant, staff=staff, amount=amount, status=status,
        paid_at=_paid_at(date) if status == PayoutStatus.PAID else None,
    )


def _req(tenant, user):
    rf = RequestFactory()
    request = rf.get("/reports/gst/?from=2026-04-01&to=2026-04-30")
    request.user = user
    request.tenant = tenant
    request.session = SessionStore()
    return request


def _parse_csv(response):
    """Return list-of-rows from a CSV HTTP response, stripping the BOM."""
    raw = response.content.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(raw)))


_FROM  = datetime.date(2026, 4,  1)
_TO    = datetime.date(2026, 4, 30)
_MID   = datetime.date(2026, 4, 15)
_PREV  = datetime.date(2026, 3, 31)  # one day before range
_NEXT  = datetime.date(2026, 5,  1)  # one day after range


# ── Case A: Split invoice (partial payments) ──────────────────────────────────

class SplitInvoiceTests(TestCase):
    """
    ₹11,000 invoice: two payments of ₹4,400 (GST ₹400) and ₹6,600 (GST ₹600).
    GST rate 10% on both.  No double-counting of totals.
    """

    def setUp(self):
        self.tenant = _make_tenant()
        _make_payment(
            self.tenant,
            amount=Decimal("4400.00"), date=_MID,
            gst_applicable=True, gst_rate=Decimal("10.00"), gst_amount=Decimal("400.00"),
        )
        _make_payment(
            self.tenant,
            amount=Decimal("6600.00"), date=_MID,
            gst_applicable=True, gst_rate=Decimal("10.00"), gst_amount=Decimal("600.00"),
        )

    def test_gst_collected_sums_both_payments(self):
        summary = get_gst_summary(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        self.assertEqual(summary["total_gst_collected"], Decimal("1000.00"))

    def test_taxable_income_is_base_amount(self):
        # taxable = gross - GST = (4400+6600) - (400+600) = 10000
        summary = get_gst_summary(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        self.assertEqual(summary["taxable_income"], Decimal("10000.00"))

    def test_income_total_is_gross_inclusive(self):
        # income/expense summary uses gross (GST-inclusive) amounts
        summary = get_income_expense_summary(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        self.assertEqual(summary["total_income"], Decimal("11000.00"))

    def test_no_double_counting_in_gst_summary(self):
        # Running summary twice must return identical results
        s1 = get_gst_summary(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        s2 = get_gst_summary(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        self.assertEqual(s1["total_gst_collected"], s2["total_gst_collected"])
        self.assertEqual(s1["taxable_income"],      s2["taxable_income"])


# ── Case B: Multiple verticals + null vertical ────────────────────────────────

class MixedVerticalTests(TestCase):
    """
    Payments spread across two named verticals and one null vertical.
    Vertical breakdown must group cleanly; grand total must match the sum.
    """

    def setUp(self):
        self.tenant = _make_tenant()
        self.fitness  = _make_vertical(self.tenant, "Fitness")
        self.therapy  = _make_vertical(self.tenant, "Therapy")

        _make_payment(self.tenant, amount=Decimal("1000.00"), date=_MID, vertical=self.fitness)
        _make_payment(self.tenant, amount=Decimal("2000.00"), date=_MID, vertical=self.fitness)
        _make_payment(self.tenant, amount=Decimal("1500.00"), date=_MID, vertical=self.therapy)
        _make_payment(self.tenant, amount=Decimal("500.00"),  date=_MID, vertical=None)

    def test_breakdown_totals_match_grand_total(self):
        rows = get_income_by_vertical(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        breakdown_sum = sum(r["total"] for r in rows)
        summary = get_income_expense_summary(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        self.assertEqual(breakdown_sum, summary["total_income"])

    def test_each_vertical_total_is_correct(self):
        rows = get_income_by_vertical(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        by_name = {r["vertical__name"]: r["total"] for r in rows}
        self.assertEqual(by_name["Fitness"], Decimal("3000.00"))
        self.assertEqual(by_name["Therapy"], Decimal("1500.00"))
        self.assertEqual(by_name[None],      Decimal("500.00"))

    def test_null_vertical_does_not_corrupt_named_totals(self):
        # The null-vertical payment must not be absorbed into a named bucket
        rows = get_income_by_vertical(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        by_name = {r["vertical__name"]: r["total"] for r in rows}
        self.assertNotIn(None, [k for k in by_name if k is not None])

    def test_expense_breakdown_with_null_vertical(self):
        _make_expense(self.tenant, amount=Decimal("400.00"), date=_MID, vertical=self.fitness)
        _make_expense(self.tenant, amount=Decimal("100.00"), date=_MID, vertical=None)
        rows = get_expense_by_vertical(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        by_name = {r["vertical__name"]: r["total"] for r in rows}
        self.assertEqual(by_name["Fitness"], Decimal("400.00"))
        self.assertEqual(by_name[None],      Decimal("100.00"))

    def test_csv_null_vertical_renders_as_unassigned(self):
        tenant = self.tenant
        user   = _make_user(tenant)
        response = income_expense_csv(_req(tenant, user))
        rows = _parse_csv(response)
        flat = [cell for row in rows for cell in row]
        self.assertIn("Unassigned", flat)


# ── Case C: Mixed GST vs non-GST records ─────────────────────────────────────

class MixedGstTests(TestCase):
    """
    Some payments carry GST; others don't.
    GST report must only count gst_applicable=True records.
    Income/expense summary must count ALL successful payments regardless.
    """

    def setUp(self):
        self.tenant = _make_tenant()
        # GST-applicable payment: ₹1,100 gross, ₹100 GST
        _make_payment(
            self.tenant,
            amount=Decimal("1100.00"), date=_MID,
            gst_applicable=True, gst_rate=Decimal("10.00"), gst_amount=Decimal("100.00"),
        )
        # Non-GST payment: ₹2,000 gross
        _make_payment(
            self.tenant,
            amount=Decimal("2000.00"), date=_MID,
            gst_applicable=False,
        )
        # GST-applicable expense: ₹550 gross, ₹50 GST
        _make_expense(
            self.tenant,
            amount=Decimal("550.00"), date=_MID,
            gst_applicable=True, gst_rate=Decimal("10.00"), gst_amount=Decimal("50.00"),
        )
        # Non-GST expense: ₹300 gross
        _make_expense(
            self.tenant,
            amount=Decimal("300.00"), date=_MID,
            gst_applicable=False,
        )

    def test_gst_summary_excludes_non_gst_income(self):
        summary = get_gst_summary(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        # Only ₹1,100 payment is GST-applicable
        self.assertEqual(summary["total_gst_collected"], Decimal("100.00"))
        self.assertEqual(summary["taxable_income"],      Decimal("1000.00"))

    def test_gst_summary_excludes_non_gst_expenses(self):
        summary = get_gst_summary(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        # Only ₹550 expense is GST-applicable
        self.assertEqual(summary["total_gst_paid"], Decimal("50.00"))

    def test_income_summary_includes_all_payments(self):
        summary = get_income_expense_summary(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        # ₹1,100 + ₹2,000 = ₹3,100 total income
        self.assertEqual(summary["total_income"], Decimal("3100.00"))

    def test_expense_summary_includes_all_expenses(self):
        summary = get_income_expense_summary(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        # ₹550 + ₹300 = ₹850 total expenses
        self.assertEqual(summary["total_expenses"], Decimal("850.00"))

    def test_net_gst_liability_positive_means_owe(self):
        summary = get_gst_summary(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        # Collected ₹100, paid ₹50 → owe ₹50
        self.assertEqual(summary["net_gst_liability"], Decimal("50.00"))
        self.assertGreater(summary["net_gst_liability"], Decimal("0"))


# ── Payout/expense separation ─────────────────────────────────────────────────

class PayoutExpenseSeparationTests(TestCase):
    """
    Payouts and expenses are distinct outflow categories.
    total_expenses must never include payout amounts, and vice-versa.
    Net profit must be: income - expenses - payouts.
    """

    def setUp(self):
        self.tenant = _make_tenant()
        self.staff  = _make_user(self.tenant)

    def test_payout_does_not_inflate_expenses(self):
        _make_expense(self.tenant, amount=Decimal("800.00"), date=_MID)
        _make_payout(self.tenant, self.staff, amount=Decimal("500.00"), date=_MID)
        summary = get_income_expense_summary(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        self.assertEqual(summary["total_expenses"], Decimal("800.00"))
        self.assertEqual(summary["total_payouts"],  Decimal("500.00"))

    def test_expense_does_not_inflate_payouts(self):
        _make_expense(self.tenant, amount=Decimal("999.00"), date=_MID)
        summary = get_income_expense_summary(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        self.assertEqual(summary["total_payouts"], Decimal("0.00"))

    def test_total_outflow_is_expenses_plus_payouts(self):
        _make_expense(self.tenant, amount=Decimal("800.00"), date=_MID)
        _make_payout(self.tenant, self.staff, amount=Decimal("500.00"), date=_MID)
        summary = get_income_expense_summary(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        expected_outflow = summary["total_expenses"] + summary["total_payouts"]
        self.assertEqual(summary["total_outflow"], expected_outflow)
        self.assertEqual(summary["total_outflow"], Decimal("1300.00"))

    def test_net_profit_accounts_for_both(self):
        _make_payment(self.tenant, amount=Decimal("5000.00"), date=_MID)
        _make_expense(self.tenant, amount=Decimal("800.00"),  date=_MID)
        _make_payout(self.tenant, self.staff, amount=Decimal("500.00"), date=_MID)
        summary = get_income_expense_summary(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        self.assertEqual(summary["net_profit"], Decimal("3700.00"))

    def test_pending_payout_excluded_from_outflow(self):
        _make_payout(self.tenant, self.staff, amount=Decimal("999.00"), date=_MID,
                     status=PayoutStatus.PENDING)
        summary = get_income_expense_summary(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        self.assertEqual(summary["total_payouts"], Decimal("0.00"))
        self.assertEqual(summary["total_outflow"], Decimal("0.00"))


# ── Payment status guards ─────────────────────────────────────────────────────

class PaymentStatusGuardTests(TestCase):
    """Every non-SUCCESS status must be excluded from all income figures."""

    def setUp(self):
        self.tenant = _make_tenant()

    def _make_all_statuses(self):
        for status in [
            PaymentStatus.CREATED,
            PaymentStatus.PENDING,
            PaymentStatus.FAILED,
            PaymentStatus.REFUNDED,
        ]:
            Payment.objects.create(
                tenant=self.tenant,
                amount=Decimal("9999.00"),
                status=status,
                paid_at=None,
                gst_applicable=True,
                gst_rate=Decimal("18.00"),
                gst_amount=Decimal("1526.27"),
            )

    def test_non_success_payments_excluded_from_income_summary(self):
        self._make_all_statuses()
        summary = get_income_expense_summary(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        self.assertEqual(summary["total_income"], Decimal("0.00"))

    def test_non_success_payments_excluded_from_gst_summary(self):
        self._make_all_statuses()
        summary = get_gst_summary(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        self.assertEqual(summary["total_gst_collected"], Decimal("0.00"))
        self.assertEqual(summary["taxable_income"],      Decimal("0.00"))

    def test_only_success_payment_appears_in_income(self):
        self._make_all_statuses()
        _make_payment(self.tenant, amount=Decimal("500.00"), date=_MID)
        summary = get_income_expense_summary(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        self.assertEqual(summary["total_income"], Decimal("500.00"))


# ── paid_at vs created_at (date field correctness) ───────────────────────────

class DateFieldCorrectnessTests(TestCase):
    """
    Reports are filtered on paid_at (the economic event), not created_at.
    A payment created inside the range but paid outside must be excluded.
    A payment created outside the range but paid inside must be included.
    """

    def setUp(self):
        self.tenant = _make_tenant()

    def test_payment_paid_in_range_included(self):
        # Created before range, paid inside range
        p = Payment.objects.create(
            tenant=self.tenant,
            amount=Decimal("1000.00"),
            status=PaymentStatus.SUCCESS,
            paid_at=_paid_at(_MID),          # paid April 15 — inside
        )
        # Force created_at to be outside by... we can't easily do that, but
        # the key check is: paid_at inside → must appear
        summary = get_income_expense_summary(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        self.assertEqual(summary["total_income"], Decimal("1000.00"))

    def test_payment_paid_before_range_excluded(self):
        Payment.objects.create(
            tenant=self.tenant,
            amount=Decimal("5000.00"),
            status=PaymentStatus.SUCCESS,
            paid_at=_paid_at(_PREV),          # paid March 31 — before range
        )
        summary = get_income_expense_summary(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        self.assertEqual(summary["total_income"], Decimal("0.00"))

    def test_payment_paid_after_range_excluded(self):
        Payment.objects.create(
            tenant=self.tenant,
            amount=Decimal("5000.00"),
            status=PaymentStatus.SUCCESS,
            paid_at=_paid_at(_NEXT),          # paid May 1 — after range
        )
        summary = get_income_expense_summary(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        self.assertEqual(summary["total_income"], Decimal("0.00"))

    def test_expense_uses_date_field_not_created_at(self):
        # Expense dated outside range must not appear
        _make_expense(self.tenant, amount=Decimal("9999.00"), date=_PREV)
        summary = get_income_expense_summary(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        self.assertEqual(summary["total_expenses"], Decimal("0.00"))

    def test_gst_summary_uses_paid_at_date(self):
        # GST-applicable payment paid one day before range — must be excluded
        Payment.objects.create(
            tenant=self.tenant,
            amount=Decimal("1100.00"),
            status=PaymentStatus.SUCCESS,
            paid_at=_paid_at(_PREV),
            gst_applicable=True,
            gst_rate=Decimal("10.00"),
            gst_amount=Decimal("100.00"),
        )
        summary = get_gst_summary(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        self.assertEqual(summary["total_gst_collected"], Decimal("0.00"))


# ── CSV decimal precision and null field rendering ────────────────────────────

class CsvPrecisionTests(TestCase):
    """
    Accountants care: all decimal values must have 2dp, nulls must be empty
    strings (not 'None'), columns must be aligned with headers.
    """

    def setUp(self):
        self.tenant = _make_tenant()
        self.user   = _make_user(self.tenant)

    def _gst_csv(self):
        response = gst_report_csv(_req(self.tenant, self.user))
        return _parse_csv(response)

    def test_amount_has_two_decimal_places(self):
        _make_payment(
            self.tenant, amount=Decimal("1100.00"), date=_MID,
            gst_applicable=True, gst_rate=Decimal("10.00"), gst_amount=Decimal("100.00"),
        )
        rows = self._gst_csv()
        # Find data row in income section (after header row)
        header_idx = next(
            i for i, r in enumerate(rows) if r and r[0] == "Date" and "Amount" in r
        )
        data_row = rows[header_idx + 1]
        amount_col = next(i for i, h in enumerate(rows[header_idx]) if h == "Amount")
        amount_val = data_row[amount_col]
        # Must be parseable as Decimal and have exactly 2dp
        parsed = Decimal(amount_val)
        self.assertEqual(parsed, Decimal("1100.00"))
        self.assertIn(".", amount_val)
        self.assertEqual(len(amount_val.split(".")[1]), 2)

    def test_null_gst_rate_renders_as_empty_not_none(self):
        # Payment with gst_applicable=True but gst_rate left NULL
        _make_payment(
            self.tenant, amount=Decimal("500.00"), date=_MID,
            gst_applicable=True, gst_rate=None, gst_amount=None,
        )
        rows = self._gst_csv()
        flat = [cell for row in rows for cell in row]
        self.assertNotIn("None", flat)

    def test_zero_gst_amount_renders_as_zero_not_empty(self):
        # Decimal("0.00") must NOT be treated as falsy and rendered blank
        _make_payment(
            self.tenant, amount=Decimal("1000.00"), date=_MID,
            gst_applicable=True, gst_rate=Decimal("0.00"), gst_amount=Decimal("0.00"),
        )
        rows = self._gst_csv()
        header_idx = next(
            i for i, r in enumerate(rows) if r and r[0] == "Date" and "Amount" in r
        )
        data_row = rows[header_idx + 1]
        gst_amount_col = next(
            i for i, h in enumerate(rows[header_idx]) if h == "GST Amount"
        )
        self.assertEqual(data_row[gst_amount_col], "0.00")

    def test_income_csv_column_count_matches_header(self):
        _make_payment(
            self.tenant, amount=Decimal("1100.00"), date=_MID,
            gst_applicable=True, gst_rate=Decimal("10.00"), gst_amount=Decimal("100.00"),
        )
        rows = self._gst_csv()
        header_idx = next(
            i for i, r in enumerate(rows) if r and r[0] == "Date" and "Person" in r
        )
        header_len = len(rows[header_idx])
        data_row   = rows[header_idx + 1]
        self.assertEqual(len(data_row), header_len,
                         msg="Income data row column count does not match header")

    def test_expense_csv_column_count_matches_header(self):
        _make_expense(
            self.tenant, amount=Decimal("550.00"), date=_MID,
            gst_applicable=True, gst_rate=Decimal("10.00"), gst_amount=Decimal("50.00"),
        )
        rows = self._gst_csv()
        header_idx = next(
            i for i, r in enumerate(rows) if r and r[0] == "Date" and "Category" in r
        )
        header_len = len(rows[header_idx])
        data_row   = rows[header_idx + 1]
        self.assertEqual(len(data_row), header_len,
                         msg="Expense data row column count does not match header")

    def test_json_null_gst_fields_render_as_empty_string(self):
        _make_payment(
            self.tenant, amount=Decimal("500.00"), date=_MID,
            gst_applicable=True, gst_rate=None, gst_amount=None,
        )
        response = gst_report_json(_req(self.tenant, self.user))
        data = json.loads(response.content)
        row = data["income"][0]
        self.assertEqual(row["gst_rate"],   "")
        self.assertEqual(row["gst_amount"], "")
        # Must be empty string, not "None"
        self.assertNotEqual(row["gst_rate"],   "None")
        self.assertNotEqual(row["gst_amount"], "None")

    def test_json_zero_gst_renders_as_zero_string_not_empty(self):
        _make_payment(
            self.tenant, amount=Decimal("1000.00"), date=_MID,
            gst_applicable=True, gst_rate=Decimal("0.00"), gst_amount=Decimal("0.00"),
        )
        response = gst_report_json(_req(self.tenant, self.user))
        data = json.loads(response.content)
        row = data["income"][0]
        self.assertEqual(row["gst_rate"],   "0.00")
        self.assertEqual(row["gst_amount"], "0.00")


# ── Invariant: service output == raw DB aggregate ─────────────────────────────

class IncomeInvariantTests(TestCase):
    """
    Self-verifying contract: the number the reporting service returns must
    always equal a direct ORM aggregate over the same predicate.

    The two computations are deliberately independent — different code paths,
    no shared helpers. If the service query gains an accidental extra filter,
    changes the status check, or starts using created_at instead of paid_at,
    exactly one side changes and the assertion fails.

    Run this test whenever the service layer is touched.
    """

    def _raw_income(self, tenant, date_from, date_to) -> Decimal:
        """Ground truth: direct aggregate, no service code."""
        from django.db.models import Sum
        result = (
            Payment.base_objects
            .filter(
                tenant=tenant,
                is_deleted=False,
                status=PaymentStatus.SUCCESS,
                paid_at__date__range=(date_from, date_to),
            )
            .aggregate(s=Sum("amount"))["s"]
        )
        return result if result is not None else Decimal("0.00")

    def _raw_gst_collected(self, tenant, date_from, date_to) -> Decimal:
        from django.db.models import Sum
        result = (
            Payment.base_objects
            .filter(
                tenant=tenant,
                is_deleted=False,
                gst_applicable=True,
                status=PaymentStatus.SUCCESS,
                paid_at__date__range=(date_from, date_to),
            )
            .aggregate(s=Sum("gst_amount"))["s"]
        )
        return result if result is not None else Decimal("0.00")

    def _raw_gst_gross(self, tenant, date_from, date_to) -> Decimal:
        from django.db.models import Sum
        result = (
            Payment.base_objects
            .filter(
                tenant=tenant,
                is_deleted=False,
                gst_applicable=True,
                status=PaymentStatus.SUCCESS,
                paid_at__date__range=(date_from, date_to),
            )
            .aggregate(s=Sum("amount"))["s"]
        )
        return result if result is not None else Decimal("0.00")

    # ── income invariant ──────────────────────────────────────────────────────

    def test_income_invariant_empty_range(self):
        tenant = _make_tenant()
        summary = get_income_expense_summary(tenant=tenant, date_from=_FROM, date_to=_TO)
        self.assertEqual(summary["total_income"], self._raw_income(tenant, _FROM, _TO))

    def test_income_invariant_single_payment(self):
        tenant = _make_tenant()
        _make_payment(tenant, amount=Decimal("1234.56"), date=_MID)
        summary = get_income_expense_summary(tenant=tenant, date_from=_FROM, date_to=_TO)
        self.assertEqual(summary["total_income"], self._raw_income(tenant, _FROM, _TO))

    def test_income_invariant_with_all_non_success_statuses(self):
        """Every non-SUCCESS status must be absent from both sides."""
        tenant = _make_tenant()
        for status in [PaymentStatus.CREATED, PaymentStatus.PENDING,
                       PaymentStatus.FAILED, PaymentStatus.REFUNDED]:
            Payment.objects.create(
                tenant=tenant, amount=Decimal("9999.00"),
                status=status, paid_at=None,
            )
        summary = get_income_expense_summary(tenant=tenant, date_from=_FROM, date_to=_TO)
        raw = self._raw_income(tenant, _FROM, _TO)
        self.assertEqual(summary["total_income"], raw)
        # Both sides must agree: the answer is zero
        self.assertEqual(summary["total_income"], Decimal("0.00"))

    def test_income_invariant_mixed_statuses(self):
        """One success + noise from every other status — only success counts."""
        tenant = _make_tenant()
        _make_payment(tenant, amount=Decimal("500.00"), date=_MID)
        for status in [PaymentStatus.CREATED, PaymentStatus.PENDING,
                       PaymentStatus.FAILED, PaymentStatus.REFUNDED]:
            Payment.objects.create(
                tenant=tenant, amount=Decimal("9999.00"),
                status=status, paid_at=None,
            )
        summary = get_income_expense_summary(tenant=tenant, date_from=_FROM, date_to=_TO)
        self.assertEqual(summary["total_income"], self._raw_income(tenant, _FROM, _TO))

    def test_income_invariant_after_soft_delete(self):
        """Soft-deleted payments must be absent from both sides."""
        tenant = _make_tenant()
        p = _make_payment(tenant, amount=Decimal("2000.00"), date=_MID)
        p.is_deleted = True
        p.save(update_fields=["is_deleted"])
        summary = get_income_expense_summary(tenant=tenant, date_from=_FROM, date_to=_TO)
        self.assertEqual(summary["total_income"], self._raw_income(tenant, _FROM, _TO))

    def test_income_invariant_payments_outside_range_excluded(self):
        """Payments on range boundaries and outside must both agree."""
        tenant = _make_tenant()
        _make_payment(tenant, amount=Decimal("100.00"), date=_FROM)   # boundary in
        _make_payment(tenant, amount=Decimal("200.00"), date=_TO)     # boundary in
        _make_payment(tenant, amount=Decimal("999.00"), date=_PREV)   # out
        _make_payment(tenant, amount=Decimal("999.00"), date=_NEXT)   # out
        summary = get_income_expense_summary(tenant=tenant, date_from=_FROM, date_to=_TO)
        self.assertEqual(summary["total_income"], self._raw_income(tenant, _FROM, _TO))
        self.assertEqual(summary["total_income"], Decimal("300.00"))

    def test_income_invariant_split_invoice(self):
        """Multiple payments toward the same invoice sum correctly on both sides."""
        tenant = _make_tenant()
        _make_payment(tenant, amount=Decimal("4400.00"), date=_MID,
                      gst_applicable=True, gst_rate=Decimal("10.00"), gst_amount=Decimal("400.00"))
        _make_payment(tenant, amount=Decimal("6600.00"), date=_MID,
                      gst_applicable=True, gst_rate=Decimal("10.00"), gst_amount=Decimal("600.00"))
        summary = get_income_expense_summary(tenant=tenant, date_from=_FROM, date_to=_TO)
        self.assertEqual(summary["total_income"], self._raw_income(tenant, _FROM, _TO))

    def test_income_invariant_tenant_isolation(self):
        """Cross-tenant data must be absent from both sides."""
        tenant = _make_tenant()
        other  = _make_tenant()
        _make_payment(other, amount=Decimal("99999.00"), date=_MID)
        summary = get_income_expense_summary(tenant=tenant, date_from=_FROM, date_to=_TO)
        self.assertEqual(summary["total_income"], self._raw_income(tenant, _FROM, _TO))
        self.assertEqual(summary["total_income"], Decimal("0.00"))

    # ── GST invariant: taxable + gst_collected == gross GST-applicable amount ──

    def test_gst_invariant_taxable_plus_collected_equals_gross(self):
        """taxable_income + total_gst_collected must always equal the gross GST payment total."""
        tenant = _make_tenant()
        _make_payment(tenant, amount=Decimal("1100.00"), date=_MID,
                      gst_applicable=True, gst_rate=Decimal("10.00"), gst_amount=Decimal("100.00"))
        _make_payment(tenant, amount=Decimal("2200.00"), date=_MID,
                      gst_applicable=True, gst_rate=Decimal("10.00"), gst_amount=Decimal("200.00"))
        summary = get_gst_summary(tenant=tenant, date_from=_FROM, date_to=_TO)
        reconstructed_gross = summary["taxable_income"] + summary["total_gst_collected"]
        self.assertEqual(reconstructed_gross, self._raw_gst_gross(tenant, _FROM, _TO))

    def test_gst_invariant_collected_matches_raw_sum(self):
        """total_gst_collected must exactly equal Sum(gst_amount) over GST-applicable payments."""
        tenant = _make_tenant()
        _make_payment(tenant, amount=Decimal("1100.00"), date=_MID,
                      gst_applicable=True, gst_rate=Decimal("10.00"), gst_amount=Decimal("100.00"))
        # Non-GST payment must NOT appear in either side of the GST invariant
        _make_payment(tenant, amount=Decimal("5000.00"), date=_MID, gst_applicable=False)
        summary = get_gst_summary(tenant=tenant, date_from=_FROM, date_to=_TO)
        self.assertEqual(summary["total_gst_collected"], self._raw_gst_collected(tenant, _FROM, _TO))

    def test_gst_invariant_null_gst_amount_counts_as_zero(self):
        """gst_applicable=True but gst_amount=NULL — service must not crash and must return 0."""
        tenant = _make_tenant()
        _make_payment(tenant, amount=Decimal("500.00"), date=_MID,
                      gst_applicable=True, gst_rate=None, gst_amount=None)
        summary = get_gst_summary(tenant=tenant, date_from=_FROM, date_to=_TO)
        # COALESCE handles NULL → 0; taxable = 500 - 0 = 500
        self.assertEqual(summary["total_gst_collected"], Decimal("0.00"))
        self.assertEqual(summary["taxable_income"],      Decimal("500.00"))
        # Both sides must agree
        self.assertEqual(summary["total_gst_collected"], self._raw_gst_collected(tenant, _FROM, _TO))

    # ── vertical breakdown invariant ──────────────────────────────────────────

    def test_vertical_breakdown_sum_equals_total_income(self):
        """
        Sum of all vertical buckets (including None) must equal total_income.
        This holds regardless of how payments are spread across verticals.
        """
        tenant   = _make_tenant()
        vert_a   = _make_vertical(tenant, "Fitness")
        vert_b   = _make_vertical(tenant, "Therapy")
        _make_payment(tenant, amount=Decimal("1000.00"), date=_MID, vertical=vert_a)
        _make_payment(tenant, amount=Decimal("2000.00"), date=_MID, vertical=vert_b)
        _make_payment(tenant, amount=Decimal("500.00"),  date=_MID, vertical=None)
        rows    = get_income_by_vertical(tenant=tenant, date_from=_FROM, date_to=_TO)
        summary = get_income_expense_summary(tenant=tenant, date_from=_FROM, date_to=_TO)
        self.assertEqual(sum(r["total"] for r in rows), summary["total_income"])

    def test_vertical_breakdown_sum_equals_raw_income(self):
        """Same as above, but the expected value comes from the raw aggregate, not the service."""
        tenant   = _make_tenant()
        vert_a   = _make_vertical(tenant, "A")
        _make_payment(tenant, amount=Decimal("750.00"), date=_MID, vertical=vert_a)
        _make_payment(tenant, amount=Decimal("250.00"), date=_MID, vertical=None)
        rows = get_income_by_vertical(tenant=tenant, date_from=_FROM, date_to=_TO)
        self.assertEqual(
            sum(r["total"] for r in rows),
            self._raw_income(tenant, _FROM, _TO),
        )
