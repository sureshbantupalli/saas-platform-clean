from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, render

from .explain_service import explain_member, explain_nudge, explain_payment
from .timeline_service import get_timeline
from .timeline_serializer import serialize


def _require_tenant(request):
    if not getattr(request, "tenant", None):
        return HttpResponseForbidden("Platform admins cannot access tenant timelines.")
    return None


def _render(request, logs):
    return render(request, "audit/timeline.html", {
        "timeline": [serialize(log) for log in logs],
    })


def _limit(request):
    try:
        return max(1, min(200, int(request.GET.get("limit", 50))))
    except (TypeError, ValueError):
        return 50


@login_required
def tenant_timeline(request):
    guard = _require_tenant(request)
    if guard:
        return guard
    logs = get_timeline(
        tenant=request.tenant,
        module=request.GET.get("module") or None,
        user_id=request.GET.get("user") or None,
        limit=_limit(request),
        before=request.GET.get("before") or None,
    )
    return _render(request, logs)


@login_required
def member_timeline(request, member_id):
    guard = _require_tenant(request)
    if guard:
        return guard
    logs = get_timeline(
        tenant=request.tenant,
        member_id=str(member_id),
        limit=_limit(request),
        before=request.GET.get("before") or None,
    )
    return _render(request, logs)


@login_required
def payment_timeline(request, payment_id):
    guard = _require_tenant(request)
    if guard:
        return guard
    logs = get_timeline(
        tenant=request.tenant,
        payment_id=str(payment_id),
        limit=_limit(request),
        before=request.GET.get("before") or None,
    )
    return _render(request, logs)


@login_required
def user_timeline(request, user_id):
    guard = _require_tenant(request)
    if guard:
        return guard
    logs = get_timeline(
        tenant=request.tenant,
        user_id=str(user_id),
        limit=_limit(request),
        before=request.GET.get("before") or None,
    )
    return _render(request, logs)


# ── Explain views (JSON) ──────────────────────────────────────────────────────

@login_required
def member_explain_view(request, member_id):
    guard = _require_tenant(request)
    if guard:
        return guard
    from members.models import Member
    member = get_object_or_404(Member, id=member_id, tenant=request.tenant)
    data = explain_member(member, tenant=request.tenant)
    return JsonResponse(data, json_dumps_params={"default": str})


@login_required
def payment_explain_view(request, payment_id):
    guard = _require_tenant(request)
    if guard:
        return guard
    from apps.payments.models import Payment
    payment = get_object_or_404(Payment, id=payment_id, tenant=request.tenant)
    data = explain_payment(payment, tenant=request.tenant)
    return JsonResponse(data, json_dumps_params={"default": str})


@login_required
def nudge_explain_view(request, member_id):
    guard = _require_tenant(request)
    if guard:
        return guard
    from members.models import Member
    member = get_object_or_404(Member, id=member_id, tenant=request.tenant)
    data = explain_nudge(member, tenant=request.tenant)
    return JsonResponse(data, json_dumps_params={"default": str})
