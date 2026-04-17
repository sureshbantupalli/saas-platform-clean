from django.shortcuts import render, redirect
from django.http import HttpResponseForbidden, Http404
from django.core.paginator import Paginator
from django.views.decorators.csrf import ensure_csrf_cookie  # ✅ NEW
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

    search_query = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "").strip()
    expiring_param = request.GET.get("expiring")

    # 🔥 Detect Expiring Drilldown Mode
    expiring_filter = expiring_param == "1"

    members_queryset = MemberService.get_queryset(
        request.user,
        search_query=search_query,
        status_filter=status_filter,
        expiring_filter=expiring_filter
    )

    # 🔢 Pagination
    paginator = Paginator(members_queryset, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # 📊 KPI Summary
    kpis = MemberService.get_kpis(members_queryset)

    # 🔥 Expiring Soon KPI Count
    expiring_soon = MemberService.get_expiring_soon_count(
        members_queryset,
        days=7
    )

    context = {
        "members": page_obj,
        "page_obj": page_obj,
        "search_query": search_query,
        "status_filter": status_filter,
        "kpis": kpis,
        "expiring_soon": expiring_soon,
        "expiring_filter": expiring_filter,
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

    return render(
        request,
        "members/member_detail.html",
        {"member": member}
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