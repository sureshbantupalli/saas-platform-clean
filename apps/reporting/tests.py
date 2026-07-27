"""
Tests for Phase 6 reporting services and view layer.

Covers:
  - GST summary (2 queries), income/expense summary (3 queries)
  - Vertical breakdown queries (1 query each)
  - Date range filtering
  - Tenant isolation (data from other tenants never leaks)
  - Soft-delete exclusion
  - CSV/JSON response headers (RequestFactory view smoke tests)
"""
import datetime
from decimal import Decimal

from django.test import RequestFactory, TestCase
from django.utils import timezone

from apps.core.models import Tenant
from apps.expenses.models import Expense, ExpenseCategory
from apps.payments.models import Payment, PaymentStatus
from apps.payouts.models import Payout, PayoutStatus
from apps.reporting.services import (
    get_expense_by_vertical,
    get_gst_expense_rows,
    get_gst_income_rows,
    get_gst_summary,
    get_income_by_vertical,
    get_income_expense_summary,
)
from apps.reporting.views import (
    gst_report_csv,
    gst_report_json,
    income_expense_csv,
    income_expense_json,
)
from apps.verticals.models import BusinessVertical


# ── Fixtures ──────────────────────────────────────────────────────────────────

_ctr = [0]


def _uid():
    _ctr[0] += 1
    return _ctr[0]


def _make_tenant():
    n = _uid()
    return Tenant.objects.create(name=f"ReportGym{n}", subdomain=f"reportgym{n}")


def _make_user(tenant):
    from apps.accounts.models import User
    from apps.authority.models import Role
    role = Role.base_objects.create(tenant=tenant, name=f"Role{_uid()}")
    return User.objects.create_user(
        email=f"u{_uid()}@report.com", password="x",
        tenant=tenant, role=role,
    )


def _make_vertical(tenant, name=None):
    n = _uid()
    return BusinessVertical.base_objects.create(
        tenant=tenant,
        name=name or f"Vertical{n}",
    )


def _make_payment(tenant, *, amount, date, status=PaymentStatus.SUCCESS,
                  gst_applicable=False, gst_amount=None, gst_rate=None, vertical=None):
    paid_at = timezone.make_aware(
        datetime.datetime.combine(date, datetime.time(10, 0))
    )
    return Payment.objects.create(
        tenant=tenant,
        amount=amount,
        status=status,
        paid_at=paid_at if status == PaymentStatus.SUCCESS else None,
        gst_applicable=gst_applicable,
        gst_rate=gst_rate,
        gst_amount=gst_amount,
        vertical=vertical,
    )


def _make_expense(tenant, *, amount, date, gst_applicable=False,
                  gst_amount=None, gst_rate=None, vertical=None, category=None):
    return Expense.base_objects.create(
        tenant=tenant,
        amount=amount,
        date=date,
        gst_applicable=gst_applicable,
        gst_rate=gst_rate,
        gst_amount=gst_amount,
        vertical=vertical,
        category=category,
    )


def _make_payout(tenant, staff, *, amount, date, status=PayoutStatus.PAID):
    paid_at = timezone.make_aware(
        datetime.datetime.combine(date, datetime.time(11, 0))
    )
    return Payout.base_objects.create(
        tenant=tenant,
        staff=staff,
        amount=amount,
        status=status,
        paid_at=paid_at if status == PayoutStatus.PAID else None,
    )


_D = datetime.date
_TODAY = _D(2026, 4, 15)
_FROM  = _D(2026, 4,  1)
_TO    = _D(2026, 4, 30)
_BEFORE = _D(2026, 3, 31)
_AFTER  = _D(2026, 5,  1)


# ── GST income rows ───────────────────────────────────────────────────────────

class GstIncomeRowsTests(TestCase):

    def setUp(self):
        self.tenant = _make_tenant()

    def test_returns_only_success_payments(self):
        _make_payment(self.tenant, amount=Decimal("100"), date=_TODAY,
                      status=PaymentStatus.SUCCESS, gst_applicable=True, gst_amount=Decimal("9"))
        _make_payment(self.tenant, amount=Decimal("100"), date=_TODAY,
                      status=PaymentStatus.CREATED, gst_applicable=True, gst_amount=Decimal("9"))
        rows = get_gst_income_rows(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        self.assertEqual(rows.count(), 1)

    def test_returns_only_gst_applicable(self):
        _make_payment(self.tenant, amount=Decimal("200"), date=_TODAY,
                      gst_applicable=True, gst_amount=Decimal("18"))
        _make_payment(self.tenant, amount=Decimal("100"), date=_TODAY,
                      gst_applicable=False)
        rows = get_gst_income_rows(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        self.assertEqual(rows.count(), 1)

    def test_date_range_boundary(self):
        _make_payment(self.tenant, amount=Decimal("100"), date=_FROM,
                      gst_applicable=True, gst_amount=Decimal("9"))
        _make_payment(self.tenant, amount=Decimal("100"), date=_TO,
                      gst_applicable=True, gst_amount=Decimal("9"))
        _make_payment(self.tenant, amount=Decimal("100"), date=_BEFORE,
                      gst_applicable=True, gst_amount=Decimal("9"))
        _make_payment(self.tenant, amount=Decimal("100"), date=_AFTER,
                      gst_applicable=True, gst_amount=Decimal("9"))
        rows = get_gst_income_rows(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        self.assertEqual(rows.count(), 2)

    def test_tenant_isolation(self):
        other = _make_tenant()
        _make_payment(other, amount=Decimal("500"), date=_TODAY,
                      gst_applicable=True, gst_amount=Decimal("45"))
        rows = get_gst_income_rows(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        self.assertEqual(rows.count(), 0)

    def test_excludes_soft_deleted(self):
        p = _make_payment(self.tenant, amount=Decimal("100"), date=_TODAY,
                          gst_applicable=True, gst_amount=Decimal("9"))
        p.is_deleted = True
        p.save(update_fields=["is_deleted"])
        rows = get_gst_income_rows(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        self.assertEqual(rows.count(), 0)


# ── GST expense rows ──────────────────────────────────────────────────────────

class GstExpenseRowsTests(TestCase):

    def setUp(self):
        self.tenant = _make_tenant()

    def test_returns_only_gst_applicable(self):
        _make_expense(self.tenant, amount=Decimal("500"), date=_TODAY,
                      gst_applicable=True, gst_amount=Decimal("45"))
        _make_expense(self.tenant, amount=Decimal("200"), date=_TODAY,
                      gst_applicable=False)
        rows = get_gst_expense_rows(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        self.assertEqual(rows.count(), 1)

    def test_tenant_isolation(self):
        other = _make_tenant()
        _make_expense(other, amount=Decimal("1000"), date=_TODAY,
                      gst_applicable=True, gst_amount=Decimal("90"))
        rows = get_gst_expense_rows(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        self.assertEqual(rows.count(), 0)

    def test_date_range_excludes_outside(self):
        _make_expense(self.tenant, amount=Decimal("100"), date=_BEFORE,
                      gst_applicable=True, gst_amount=Decimal("9"))
        _make_expense(self.tenant, amount=Decimal("100"), date=_AFTER,
                      gst_applicable=True, gst_amount=Decimal("9"))
        rows = get_gst_expense_rows(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        self.assertEqual(rows.count(), 0)


# ── GST summary ───────────────────────────────────────────────────────────────

class GstSummaryTests(TestCase):

    def setUp(self):
        self.tenant = _make_tenant()

    def test_correct_totals(self):
        _make_payment(self.tenant, amount=Decimal("1100"), date=_TODAY,
                      gst_applicable=True, gst_amount=Decimal("100"))
        _make_expense(self.tenant, amount=Decimal("550"), date=_TODAY,
                      gst_applicable=True, gst_amount=Decimal("50"))
        summary = get_gst_summary(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        self.assertEqual(summary["total_gst_collected"], Decimal("100"))
        self.assertEqual(summary["total_gst_paid"],      Decimal("50"))
        self.assertEqual(summary["taxable_income"],      Decimal("1000"))
        self.assertEqual(summary["net_gst_liability"],   Decimal("50"))

    def test_zero_when_no_data(self):
        summary = get_gst_summary(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        self.assertEqual(summary["total_gst_collected"], Decimal("0.00"))
        self.assertEqual(summary["total_gst_paid"],      Decimal("0.00"))
        self.assertEqual(summary["net_gst_liability"],   Decimal("0.00"))

    def test_uses_exactly_two_queries(self):
        _make_payment(self.tenant, amount=Decimal("550"), date=_TODAY,
                      gst_applicable=True, gst_amount=Decimal("50"))
        with self.assertNumQueries(2):
            get_gst_summary(tenant=self.tenant, date_from=_FROM, date_to=_TO)

    def test_tenant_isolation(self):
        other = _make_tenant()
        _make_payment(other, amount=Decimal("10000"), date=_TODAY,
                      gst_applicable=True, gst_amount=Decimal("900"))
        summary = get_gst_summary(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        self.assertEqual(summary["total_gst_collected"], Decimal("0.00"))

    def test_date_from_to_in_response(self):
        summary = get_gst_summary(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        self.assertEqual(summary["date_from"], _FROM)
        self.assertEqual(summary["date_to"],   _TO)


# ── Income vs expense summary ──────────────────────────────────────────────────

class IncomeExpenseSummaryTests(TestCase):

    def setUp(self):
        self.tenant = _make_tenant()
        self.staff = _make_user(self.tenant)

    def test_correct_totals(self):
        _make_payment(self.tenant, amount=Decimal("3000"), date=_TODAY)
        _make_expense(self.tenant, amount=Decimal("800"),  date=_TODAY)
        _make_payout(self.tenant, self.staff, amount=Decimal("500"), date=_TODAY)
        summary = get_income_expense_summary(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        self.assertEqual(summary["total_income"],   Decimal("3000"))
        self.assertEqual(summary["total_expenses"], Decimal("800"))
        self.assertEqual(summary["total_payouts"],  Decimal("500"))
        self.assertEqual(summary["total_outflow"],  Decimal("1300"))
        self.assertEqual(summary["net_profit"],     Decimal("1700"))

    def test_excludes_non_paid_payouts(self):
        _make_payout(self.tenant, self.staff, amount=Decimal("999"), date=_TODAY,
                     status=PayoutStatus.PENDING)
        summary = get_income_expense_summary(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        self.assertEqual(summary["total_payouts"], Decimal("0.00"))

    def test_excludes_non_success_payments(self):
        _make_payment(self.tenant, amount=Decimal("5000"), date=_TODAY,
                      status=PaymentStatus.CREATED)
        summary = get_income_expense_summary(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        self.assertEqual(summary["total_income"], Decimal("0.00"))

    def test_uses_exactly_three_queries(self):
        with self.assertNumQueries(3):
            get_income_expense_summary(tenant=self.tenant, date_from=_FROM, date_to=_TO)

    def test_tenant_isolation(self):
        other = _make_tenant()
        other_staff = _make_user(other)
        _make_payment(other, amount=Decimal("9999"), date=_TODAY)
        _make_expense(other, amount=Decimal("9999"), date=_TODAY)
        _make_payout(other, other_staff, amount=Decimal("9999"), date=_TODAY)
        summary = get_income_expense_summary(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        self.assertEqual(summary["total_income"],   Decimal("0.00"))
        self.assertEqual(summary["total_expenses"], Decimal("0.00"))
        self.assertEqual(summary["total_payouts"],  Decimal("0.00"))


# ── Vertical breakdown ────────────────────────────────────────────────────────

class VerticalBreakdownTests(TestCase):

    def setUp(self):
        self.tenant  = _make_tenant()
        self.vert_a  = _make_vertical(self.tenant, "Fitness")
        self.vert_b  = _make_vertical(self.tenant, "Therapy")

    def test_income_by_vertical(self):
        _make_payment(self.tenant, amount=Decimal("1000"), date=_TODAY, vertical=self.vert_a)
        _make_payment(self.tenant, amount=Decimal("2000"), date=_TODAY, vertical=self.vert_a)
        _make_payment(self.tenant, amount=Decimal("500"),  date=_TODAY, vertical=self.vert_b)
        rows = get_income_by_vertical(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        totals = {r["vertical__name"]: r["total"] for r in rows}
        self.assertEqual(totals["Fitness"], Decimal("3000"))
        self.assertEqual(totals["Therapy"], Decimal("500"))

    def test_expense_by_vertical(self):
        _make_expense(self.tenant, amount=Decimal("400"), date=_TODAY, vertical=self.vert_a)
        _make_expense(self.tenant, amount=Decimal("100"), date=_TODAY, vertical=self.vert_b)
        rows = get_expense_by_vertical(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        totals = {r["vertical__name"]: r["total"] for r in rows}
        self.assertEqual(totals["Fitness"], Decimal("400"))
        self.assertEqual(totals["Therapy"], Decimal("100"))

    def test_no_vertical_appears_as_none(self):
        _make_payment(self.tenant, amount=Decimal("750"), date=_TODAY, vertical=None)
        rows = get_income_by_vertical(tenant=self.tenant, date_from=_FROM, date_to=_TO)
        keys = [r["vertical__name"] for r in rows]
        self.assertIn(None, keys)

    def test_income_by_vertical_single_query(self):
        _make_payment(self.tenant, amount=Decimal("100"), date=_TODAY)
        with self.assertNumQueries(1):
            get_income_by_vertical(tenant=self.tenant, date_from=_FROM, date_to=_TO)

    def test_expense_by_vertical_single_query(self):
        _make_expense(self.tenant, amount=Decimal("100"), date=_TODAY)
        with self.assertNumQueries(1):
            get_expense_by_vertical(tenant=self.tenant, date_from=_FROM, date_to=_TO)


# ── View smoke tests ──────────────────────────────────────────────────────────

class _ViewBase(TestCase):
    """Sets up a logged-in user + tenant attached to request."""

    def setUp(self):
        self.tenant = _make_tenant()
        self.user   = _make_user(self.tenant)
        self.rf     = RequestFactory()

    def _req(self, url, params=""):
        from django.contrib.sessions.backends.db import SessionStore
        request = self.rf.get(f"{url}?{params}")
        request.user   = self.user
        request.tenant = self.tenant
        request.session = SessionStore()
        return request


class GstJsonViewTests(_ViewBase):

    def test_returns_200_json(self):
        response = gst_report_json(self._req("/reports/gst/"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/json", response["Content-Type"])

    def test_response_has_expected_keys(self):
        import json
        response = gst_report_json(self._req("/reports/gst/"))
        data = json.loads(response.content)
        self.assertIn("summary",  data)
        self.assertIn("income",   data)
        self.assertIn("expenses", data)


class GstCsvViewTests(_ViewBase):

    def test_returns_csv_attachment(self):
        response = gst_report_csv(self._req("/reports/gst/csv/"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertIn("gst_report_", response["Content-Disposition"])

    def test_csv_has_summary_header(self):
        response = gst_report_csv(self._req("/reports/gst/csv/"))
        content = response.content.decode("utf-8-sig")
        self.assertIn("GST SUMMARY", content)
        self.assertIn("INCOME", content)
        self.assertIn("EXPENSES", content)


class IncomeExpenseJsonViewTests(_ViewBase):

    def test_returns_200_json(self):
        response = income_expense_json(self._req("/reports/income-expense/"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/json", response["Content-Type"])

    def test_response_has_expected_keys(self):
        import json
        response = income_expense_json(self._req("/reports/income-expense/"))
        data = json.loads(response.content)
        self.assertIn("summary",             data)
        self.assertIn("income_by_vertical",  data)
        self.assertIn("expense_by_vertical", data)


class IncomeExpenseCsvViewTests(_ViewBase):

    def test_returns_csv_attachment(self):
        response = income_expense_csv(self._req("/reports/income-expense/csv/"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        self.assertIn("attachment", response["Content-Disposition"])

    def test_csv_has_section_headers(self):
        response = income_expense_csv(self._req("/reports/income-expense/csv/"))
        content = response.content.decode("utf-8-sig")
        self.assertIn("INCOME VS EXPENSE SUMMARY", content)
        self.assertIn("INCOME BY VERTICAL",  content)
        self.assertIn("EXPENSES BY VERTICAL", content)


class PlatformAdminBlockedTests(_ViewBase):
    """When request.tenant is None the views must return 403."""

    def _req_no_tenant(self, url):
        request = self.rf.get(url)
        request.user   = self.user
        request.tenant = None
        from django.contrib.sessions.backends.db import SessionStore
        request.session = SessionStore()
        return request

    def test_gst_json_blocked(self):
        response = gst_report_json(self._req_no_tenant("/reports/gst/"))
        self.assertEqual(response.status_code, 403)

    def test_income_expense_csv_blocked(self):
        response = income_expense_csv(self._req_no_tenant("/reports/income-expense/csv/"))
        self.assertEqual(response.status_code, 403)
