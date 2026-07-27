"""
Reporting views — CSV download + JSON API.

All date parsing is defensive: bad/missing dates fall back to sensible defaults.
All queries are delegated to services.py — views contain zero business logic.
"""
import csv
import datetime
import json
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.utils.dateparse import parse_date

from .services import (
    get_expense_by_vertical,
    get_gst_expense_rows,
    get_gst_income_rows,
    get_gst_summary,
    get_income_by_vertical,
    get_income_expense_summary,
)


# ── Shared helpers ────────────────────────────────────────────────────────────

def _require_tenant(request):
    if not getattr(request, "tenant", None):
        return HttpResponseForbidden("Platform admins cannot access tenant reports.")
    return None


def _parse_range(request):
    today = datetime.date.today()
    first_of_month = today.replace(day=1)
    date_from = parse_date(request.GET.get("from", "")) or first_of_month
    date_to   = parse_date(request.GET.get("to",   "")) or today
    return date_from, date_to


def _csv_response(filename: str) -> HttpResponse:
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("﻿")   # BOM — makes Excel open UTF-8 correctly
    return response


class _DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        if isinstance(obj, datetime.date):
            return obj.isoformat()
        return super().default(obj)


def _json(data) -> JsonResponse:
    return HttpResponse(
        json.dumps(data, cls=_DecimalEncoder),
        content_type="application/json",
    )


# ── GST report ────────────────────────────────────────────────────────────────

@login_required
def gst_report_json(request):
    guard = _require_tenant(request)
    if guard:
        return guard
    date_from, date_to = _parse_range(request)
    tenant = request.tenant

    summary     = get_gst_summary(tenant=tenant, date_from=date_from, date_to=date_to)
    income_rows = [
        {
            "date":           p.paid_at.date().isoformat(),
            "person":         str(p.person) if p.person_id else "",
            "amount":         str(p.amount),
            "gst_rate":       "" if p.gst_rate   is None else str(p.gst_rate),
            "gst_amount":     "" if p.gst_amount is None else str(p.gst_amount),
            "vertical":       p.vertical.name if p.vertical_id else "",
            "reference_type": p.reference_type,
        }
        for p in get_gst_income_rows(tenant=tenant, date_from=date_from, date_to=date_to)
    ]
    expense_rows = [
        {
            "date":         e.date.isoformat(),
            "category":     e.category.name if e.category_id else "",
            "vendor":       e.vendor_name,
            "amount":       str(e.amount),
            "gst_rate":     "" if e.gst_rate   is None else str(e.gst_rate),
            "gst_amount":   "" if e.gst_amount is None else str(e.gst_amount),
            "vertical":     e.vertical.name if e.vertical_id else "",
        }
        for e in get_gst_expense_rows(tenant=tenant, date_from=date_from, date_to=date_to)
    ]

    return _json({"summary": summary, "income": income_rows, "expenses": expense_rows})


@login_required
def gst_report_csv(request):
    guard = _require_tenant(request)
    if guard:
        return guard
    date_from, date_to = _parse_range(request)
    tenant = request.tenant

    summary      = get_gst_summary(tenant=tenant, date_from=date_from, date_to=date_to)
    income_rows  = get_gst_income_rows(tenant=tenant, date_from=date_from, date_to=date_to)
    expense_rows = get_gst_expense_rows(tenant=tenant, date_from=date_from, date_to=date_to)

    response = _csv_response(f"gst_report_{date_from}_{date_to}.csv")
    w = csv.writer(response)

    # Summary block
    w.writerow(["GST SUMMARY", f"{date_from} to {date_to}"])
    w.writerow(["Taxable Income",      summary["taxable_income"]])
    w.writerow(["GST Collected",       summary["total_gst_collected"]])
    w.writerow(["GST Paid (Expenses)", summary["total_gst_paid"]])
    w.writerow(["Net GST Liability",   summary["net_gst_liability"]])
    w.writerow([])

    # Income section
    w.writerow(["INCOME (GST-applicable payments)"])
    w.writerow(["Date", "Person", "Amount", "GST Rate %", "GST Amount", "Vertical", "Reference Type"])
    for p in income_rows:
        w.writerow([
            p.paid_at.date(),
            str(p.person) if p.person_id else "",
            p.amount,
            "" if p.gst_rate   is None else p.gst_rate,
            "" if p.gst_amount is None else p.gst_amount,
            p.vertical.name if p.vertical_id else "",
            p.reference_type,
        ])
    w.writerow([])

    # Expense section
    w.writerow(["EXPENSES (GST-applicable)"])
    w.writerow(["Date", "Category", "Vendor", "Amount", "GST Rate %", "GST Amount", "Vertical"])
    for e in expense_rows:
        w.writerow([
            e.date,
            e.category.name if e.category_id else "",
            e.vendor_name,
            e.amount,
            "" if e.gst_rate   is None else e.gst_rate,
            "" if e.gst_amount is None else e.gst_amount,
            e.vertical.name if e.vertical_id else "",
        ])

    return response


# ── Income vs Expense report ──────────────────────────────────────────────────

@login_required
def income_expense_json(request):
    guard = _require_tenant(request)
    if guard:
        return guard
    date_from, date_to = _parse_range(request)
    tenant = request.tenant

    return _json({
        "summary":            get_income_expense_summary(tenant=tenant, date_from=date_from, date_to=date_to),
        "income_by_vertical": get_income_by_vertical(tenant=tenant, date_from=date_from, date_to=date_to),
        "expense_by_vertical":get_expense_by_vertical(tenant=tenant, date_from=date_from, date_to=date_to),
    })


@login_required
def income_expense_csv(request):
    guard = _require_tenant(request)
    if guard:
        return guard
    date_from, date_to = _parse_range(request)
    tenant = request.tenant

    summary   = get_income_expense_summary(tenant=tenant, date_from=date_from, date_to=date_to)
    by_income = get_income_by_vertical(tenant=tenant, date_from=date_from, date_to=date_to)
    by_expense = get_expense_by_vertical(tenant=tenant, date_from=date_from, date_to=date_to)

    response = _csv_response(f"income_expense_{date_from}_{date_to}.csv")
    w = csv.writer(response)

    # Summary block
    w.writerow(["INCOME VS EXPENSE SUMMARY", f"{date_from} to {date_to}"])
    w.writerow(["Total Income",   summary["total_income"]])
    w.writerow(["Total Expenses", summary["total_expenses"]])
    w.writerow(["Total Payouts",  summary["total_payouts"]])
    w.writerow(["Total Outflow",  summary["total_outflow"]])
    w.writerow(["Net Profit",     summary["net_profit"]])
    w.writerow([])

    # By vertical — income
    w.writerow(["INCOME BY VERTICAL"])
    w.writerow(["Vertical", "Total Income"])
    for row in by_income:
        w.writerow([row["vertical__name"] or "Unassigned", row["total"]])
    w.writerow([])

    # By vertical — expense
    w.writerow(["EXPENSES BY VERTICAL"])
    w.writerow(["Vertical", "Total Expense"])
    for row in by_expense:
        w.writerow([row["vertical__name"] or "Unassigned", row["total"]])

    return response
