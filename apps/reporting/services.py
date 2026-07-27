"""
Phase 6 reporting service.

Read-only. All aggregation at DB level — no N+1, no Python-side math.
Uses base_objects throughout so queries are tenant-explicit and
independent of request middleware state.

Convention:
  - Payment income = status SUCCESS + paid_at in range
  - Payout outflow = status PAID + paid_at in range
  - Expense outflow = date in range
  - taxable_value (GST) = amount - gst_amount  (amount is GST-inclusive)
"""
from decimal import Decimal

from django.db.models import DecimalField, Sum, Value
from django.db.models.functions import Coalesce

from apps.expenses.models import Expense
from apps.payments.models import Payment, PaymentStatus
from apps.payouts.models import Payout, PayoutStatus


_ZERO = Decimal("0.00")
_COALESCE = lambda f: Coalesce(Sum(f), Value(_ZERO), output_field=DecimalField())


# ── GST report ────────────────────────────────────────────────────────────────

def get_gst_income_rows(*, tenant, date_from, date_to):
    """
    Returns queryset of GST-applicable successful payments in range.
    Ordered chronologically. select_related prevents N+1 on person + vertical.
    """
    return (
        Payment.base_objects
        .filter(
            tenant=tenant,
            is_deleted=False,
            gst_applicable=True,
            status=PaymentStatus.SUCCESS,
            paid_at__date__range=(date_from, date_to),
        )
        .select_related("person", "vertical")
        .order_by("paid_at")
    )


def get_gst_expense_rows(*, tenant, date_from, date_to):
    """
    Returns queryset of GST-applicable expenses in range.
    Ordered chronologically. select_related prevents N+1 on category + vertical.
    """
    return (
        Expense.base_objects
        .filter(
            tenant=tenant,
            is_deleted=False,
            gst_applicable=True,
            date__range=(date_from, date_to),
        )
        .select_related("category", "vertical")
        .order_by("date")
    )


def get_gst_summary(*, tenant, date_from, date_to) -> dict:
    """
    Returns aggregate GST totals for the date range. Exactly 2 DB queries.

    taxable_value = amount - gst_amount  (amount is GST-inclusive).
    net_liability = gst_collected - gst_paid  (positive = you owe; negative = refund due).
    """
    income_agg = (
        Payment.base_objects
        .filter(
            tenant=tenant,
            is_deleted=False,
            gst_applicable=True,
            status=PaymentStatus.SUCCESS,
            paid_at__date__range=(date_from, date_to),
        )
        .aggregate(
            total_amount=_COALESCE("amount"),
            total_gst_collected=_COALESCE("gst_amount"),
        )
    )
    expense_agg = (
        Expense.base_objects
        .filter(
            tenant=tenant,
            is_deleted=False,
            gst_applicable=True,
            date__range=(date_from, date_to),
        )
        .aggregate(
            total_expense_amount=_COALESCE("amount"),
            total_gst_paid=_COALESCE("gst_amount"),
        )
    )

    total_gst_collected = income_agg["total_gst_collected"]
    total_gst_paid      = expense_agg["total_gst_paid"]
    taxable_income      = income_agg["total_amount"] - total_gst_collected

    return {
        "date_from":           date_from,
        "date_to":             date_to,
        "taxable_income":      taxable_income,
        "total_gst_collected": total_gst_collected,
        "total_gst_paid":      total_gst_paid,
        "net_gst_liability":   total_gst_collected - total_gst_paid,
    }


# ── Income vs Expense report ──────────────────────────────────────────────────

def get_income_expense_summary(*, tenant, date_from, date_to) -> dict:
    """
    Returns top-level P&L summary. Exactly 3 DB queries.

    Income  = successful payments in range.
    Expenses = recorded expenses in range.
    Payouts  = paid staff payouts in range.
    Total outflow = expenses + payouts.
    Net profit = income - outflow.
    """
    income = (
        Payment.base_objects
        .filter(
            tenant=tenant,
            is_deleted=False,
            status=PaymentStatus.SUCCESS,
            paid_at__date__range=(date_from, date_to),
        )
        .aggregate(total=_COALESCE("amount"))["total"]
    )
    expenses = (
        Expense.base_objects
        .filter(
            tenant=tenant,
            is_deleted=False,
            date__range=(date_from, date_to),
        )
        .aggregate(total=_COALESCE("amount"))["total"]
    )
    payouts = (
        Payout.base_objects
        .filter(
            tenant=tenant,
            is_deleted=False,
            status=PayoutStatus.PAID,
            paid_at__date__range=(date_from, date_to),
        )
        .aggregate(total=_COALESCE("amount"))["total"]
    )

    outflow = expenses + payouts
    return {
        "date_from":      date_from,
        "date_to":        date_to,
        "total_income":   income,
        "total_expenses": expenses,
        "total_payouts":  payouts,
        "total_outflow":  outflow,
        "net_profit":     income - outflow,
    }


def get_income_by_vertical(*, tenant, date_from, date_to) -> list:
    """
    Returns income grouped by vertical. Single DB query.
    Rows with no vertical appear under vertical__name=None.
    """
    return list(
        Payment.base_objects
        .filter(
            tenant=tenant,
            is_deleted=False,
            status=PaymentStatus.SUCCESS,
            paid_at__date__range=(date_from, date_to),
        )
        .values("vertical__name")
        .annotate(total=_COALESCE("amount"))
        .order_by("vertical__name")
    )


def get_expense_by_vertical(*, tenant, date_from, date_to) -> list:
    """
    Returns expenses grouped by vertical. Single DB query.
    """
    return list(
        Expense.base_objects
        .filter(
            tenant=tenant,
            is_deleted=False,
            date__range=(date_from, date_to),
        )
        .values("vertical__name")
        .annotate(total=_COALESCE("amount"))
        .order_by("vertical__name")
    )
