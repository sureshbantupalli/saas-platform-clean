from datetime import date, timedelta

from django.shortcuts import render, redirect
from django.http import HttpResponseForbidden, Http404
from django.core.paginator import Paginator
from django.views.decorators.csrf import ensure_csrf_cookie
from django.middleware.csrf import get_token

from .forms import MemberForm
from apps.core.permissions import require_permission
from members.services.member_service import MemberService


# ==============================
# ✅ NEW: Member Create UI (API-based)
# ==============================

@ensure_csrf_cookie   # 🔥 CRITICAL FIX (CSRF cookie will be set)
def member_create_ui(request):
    get_token(request)   # 🔥 FORCE GENERATE TOKEN
    return render(request, "members/add_member.html")

# ==============================
# Member List
# ==============================

@require_permission("members", "view")
def member_list(request):

    search_query   = request.GET.get("q", "").strip()
    status_filter  = request.GET.get("status", "").strip()
    expiring_param = request.GET.get("expiring")
    filter_param   = request.GET.get("filter", "").strip()

    expiring_filter = expiring_param == "1"

    members_queryset = MemberService.get_queryset(
        request.user,
        search_query=search_query,
        status_filter=status_filter,
        expiring_filter=expiring_filter,
    )

    # At-risk drilldown: active members with no attendance in the last 7 days
    at_risk_filter = filter_param == "at_risk"
    if at_risk_filter:
        from apps.attendance.models import Attendance
        seven_days_ago = date.today() - timedelta(days=7)
        recent_ids = set(
            Attendance.base_objects.filter(
                tenant=request.user.tenant,
                status="present",
                session_date__gte=seven_days_ago,
                is_deleted=False,
            ).values_list("member_id", flat=True).distinct()
        )
        members_queryset = [m for m in members_queryset if m.id not in recent_ids]

    # Pagination
    paginator = Paginator(members_queryset, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    kpis = MemberService.get_kpis(members_queryset)
    expiring_soon = MemberService.get_expiring_soon_count(members_queryset, days=7)

    context = {
        "members":        page_obj,
        "page_obj":       page_obj,
        "search_query":   search_query,
        "status_filter":  status_filter,
        "kpis":           kpis,
        "expiring_soon":  expiring_soon,
        "expiring_filter": expiring_filter,
        "at_risk_filter": at_risk_filter,
    }

    return render(
        request,
        "members/member_list.html",
        context
    )


# ==============================
# Member Detail
# ==============================

@require_permission("members", "view_member")
def member_detail(request, pk):

    member = MemberService.get_by_id(request.user, pk)

    if not member:
        raise Http404("Member not found")

    tenant = request.user.tenant

    from apps.payments.models import Payment
    member_payments = Payment.base_objects.filter(
        tenant=tenant,
        reference_type="membership",
        reference_id__in=member.memberships.values_list("id", flat=True),
        is_deleted=False,
    ).order_by("-created_at")

    from members.services.timeline_service import get_member_timeline
    timeline = get_member_timeline(member, tenant)

    return render(
        request,
        "members/member_detail.html",
        {
            "member":         member,
            "member_payments": member_payments,
            "timeline":       timeline,
        }
    )


# ==============================
# Member Create (Form-based CRM)
# ==============================

@require_permission("members", "create")
def member_create(request):

    if request.method == "POST":
        form = MemberForm(
            request.POST,
            tenant=request.user.tenant
        )

        if form.is_valid():
            member = form.save(commit=False)
            member.tenant = request.user.tenant
            member.created_by = request.user
            member.save()
            form.save_m2m()

            return redirect("members:member_list")

    else:
        form = MemberForm(
            tenant=request.user.tenant
        )

    return render(
        request,
        "members/member_form.html",
        {"form": form}
    )


# ==============================
# Member Update
# ==============================

@require_permission("members", "update")
def member_update(request, pk):

    member = MemberService.get_by_id(request.user, pk)

    if not member:
        raise Http404("Member not found")

    if request.method == "POST":
        form = MemberForm(
            request.POST,
            instance=member,
            tenant=request.user.tenant
        )

        if form.is_valid():
            member = form.save(commit=False)
            member.save()
            form.save_m2m()

            return redirect("members:member_detail", pk=member.pk)

    else:
        form = MemberForm(
            instance=member,
            tenant=request.user.tenant
        )

    return render(
        request,
        "members/member_form.html",
        {"form": form}
    )


# ==============================
# Member Delete (Soft Delete)
# ==============================

@require_permission("members", "delete")
def member_delete(request, pk):

    member = MemberService.get_by_id(request.user, pk)

    if not member:
        raise Http404("Member not found")

    if request.method == "POST":
        MemberService.soft_delete(member)
        return redirect("members:member_list")

    return render(
        request,
        "members/member_confirm_delete.html",
        {"member": member}
    )

# ─── Member Payment History ───────────────────────────────────────────────────

@require_permission("members", "view")
def member_payments(request, pk):
    """
    GET /members/<pk>/payments/
    Shows all payments linked to any of this member's memberships.
    Accessible to staff only (same permission gate as member_detail).
    """
    from apps.payments.models import Payment, PaymentStatus
    from apps.memberships.models import Membership

    member = MemberService.get_by_id(request.user, pk)
    if not member:
        raise Http404("Member not found")

    # All memberships for this member (any status)
    memberships = list(
        Membership.base_objects
        .filter(member=member, is_deleted=False)
        .select_related("plan")
        .order_by("-created_at")
    )
    mem_ids = [m.pk for m in memberships]

    # Build membership lookup by pk for display in payment rows
    membership_map = {m.pk: m for m in memberships}

    # All payments referencing any of their memberships
    payments = (
        Payment.base_objects
        .filter(
            tenant=request.user.tenant,
            reference_type="membership",
            reference_id__in=mem_ids,
            is_deleted=False,
        )
        .order_by("-created_at")
    )

    # Attach membership to each payment for template display
    payment_rows = []
    for p in payments:
        payment_rows.append({
            "payment":    p,
            "membership": membership_map.get(p.reference_id),
        })

    # Totals
    from django.db.models import Sum, Q
    totals = payments.aggregate(
        total_paid=Sum("amount", filter=Q(status=PaymentStatus.SUCCESS)),
        total_pending=Sum("amount", filter=Q(status__in=[PaymentStatus.CREATED, PaymentStatus.PENDING])),
    )

    return render(request, "members/member_payments.html", {
        "member":       member,
        "payment_rows": payment_rows,
        "memberships":  memberships,
        "total_paid":   totals["total_paid"] or 0,
        "total_pending": totals["total_pending"] or 0,
    })
