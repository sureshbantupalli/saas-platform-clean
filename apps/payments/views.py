from decimal import Decimal

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST, require_GET

from .models import Payment, PaymentStatus, PaymentMethod, PaymentGateway, TenantPaymentConfig
from .services.payment_service import PaymentService, PaymentError


def _get_membership_context(reference_type, reference_id, tenant):
    """Fetch the linked membership for display if reference_type is 'membership'."""
    if reference_type != "membership" or not reference_id:
        return None
    try:
        from apps.memberships.models import Membership
        return Membership.base_objects.get(pk=reference_id, tenant=tenant)
    except Exception:
        return None


# ─── Payment List ────────────────────────────────────────────────────────────

@login_required
def payment_list(request):
    from members.models import Member

    qs = (
        Payment.base_objects
        .filter(tenant=request.user.tenant, is_deleted=False)
        .select_related("created_by")
        .order_by("-created_at")
    )

    # Filters
    ref_type      = request.GET.get("ref_type", "")
    ref_id        = request.GET.get("ref_id", "")
    status_filter = request.GET.get("status", "")
    member_id     = request.GET.get("member_id", "")
    date_from     = request.GET.get("date_from", "")
    date_to       = request.GET.get("date_to", "")

    if ref_type and ref_id:
        qs = qs.filter(reference_type=ref_type, reference_id=ref_id)
    if status_filter:
        qs = qs.filter(status=status_filter)
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)

    # Filter by member: find their membership IDs then filter payments
    selected_member = None
    if member_id:
        try:
            selected_member = Member.objects.get(pk=member_id, tenant=request.user.tenant)
            from apps.memberships.models import Membership
            mem_ids = list(
                Membership.base_objects
                .filter(member=selected_member, is_deleted=False)
                .values_list("pk", flat=True)
            )
            qs = qs.filter(reference_type="membership", reference_id__in=mem_ids)
        except Member.DoesNotExist:
            pass

    # Annotate with member name via membership lookup (done in template via payment context)
    paginator = Paginator(qs, 30)
    page      = paginator.get_page(request.GET.get("page"))

    all_members = (
        Member.objects
        .filter(tenant=request.user.tenant, is_deleted=False)
        .order_by("first_name", "last_name")
    )

    return render(request, "payments/payment_list.html", {
        "page":             page,
        "payments":         page.object_list,
        "status_choices":   PaymentStatus.choices,
        "all_members":      all_members,
        "selected_member":  selected_member,
        "ref_type":         ref_type,
        "ref_id":           ref_id,
        "status_filter":    status_filter,
        "member_id":        member_id,
        "date_from":        date_from,
        "date_to":          date_to,
    })


# ─── Payment Detail ──────────────────────────────────────────────────────────

@login_required
def payment_detail(request, pk):
    payment = get_object_or_404(
        Payment.base_objects, pk=pk, tenant=request.user.tenant, is_deleted=False
    )
    events     = payment.events.order_by("created_at")
    membership = _get_membership_context(
        payment.reference_type, payment.reference_id, request.user.tenant
    )
    member = None
    if membership:
        try:
            from members.models import Member
            member = Member.objects.get(pk=membership.member_id, is_deleted=False)
        except Exception:
            pass

    return render(request, "payments/payment_detail.html", {
        "payment":    payment,
        "events":     events,
        "membership": membership,
        "member":     member,
    })


# ─── Create Payment ──────────────────────────────────────────────────────────

@login_required
def payment_create(request):
    """
    GET  — render form pre-filled from query params; shows membership financial
           summary when reference_type=membership.
    POST — validate amount (no overpayment), create record, redirect to detail.
    """
    reference_type = request.GET.get("reference_type", "")
    reference_id   = request.GET.get("reference_id",   "")
    amount_hint    = request.GET.get("amount", "")
    purpose        = request.GET.get("purpose", "membership")
    member_id      = request.GET.get("member_id", "")

    membership = _get_membership_context(reference_type, reference_id, request.user.tenant)
    if membership and not amount_hint:
        amount_hint = str(membership.balance_amount)

    if request.method == "POST":
        reference_type = request.POST.get("reference_type", "")
        reference_id   = request.POST.get("reference_id",   "") or None
        amount_str     = request.POST.get("amount",         "0")
        purpose        = request.POST.get("purpose",        "membership")
        gateway        = request.POST.get("gateway",        PaymentGateway.OFFLINE)
        method         = request.POST.get("payment_method") or None
        ref_no         = request.POST.get("payment_reference", "")
        notes          = request.POST.get("notes",          "")
        member_id      = request.POST.get("member_id",      "")

        try:
            amount = Decimal(amount_str)
        except Exception:
            amount = Decimal("0")

        # Overpayment guard
        if membership and amount > membership.balance_amount:
            messages.error(
                request,
                f"Amount ₹{amount} exceeds outstanding balance of ₹{membership.balance_amount}."
            )
            return render(request, "payments/payment_create.html", {
                "reference_type": reference_type,
                "reference_id":   reference_id,
                "amount_hint":    amount_str,
                "purpose":        purpose,
                "member_id":      member_id,
                "membership":     membership,
                "method_choices": PaymentMethod.choices,
                "gateway_choices": PaymentGateway.choices,
            })

        try:
            payment = PaymentService.create_payment(
                tenant=request.user.tenant,
                amount=amount,
                purpose=purpose,
                reference_type=reference_type,
                reference_id=reference_id if reference_id else None,
                gateway=gateway,
                payment_method=method,
                payment_reference=ref_no,
                notes=notes,
                created_by=request.user,
            )
            messages.success(request, f"Payment of ₹{payment.amount} created.")
            return redirect("payments:payment_detail", pk=payment.pk)

        except Exception as e:
            messages.error(request, f"Could not create payment: {e}")

    return render(request, "payments/payment_create.html", {
        "reference_type":  reference_type,
        "reference_id":    reference_id,
        "amount_hint":     amount_hint,
        "purpose":         purpose,
        "member_id":       member_id,
        "membership":      membership,
        "method_choices":  PaymentMethod.choices,
        "gateway_choices": PaymentGateway.choices,
    })


# ─── Mark Success ────────────────────────────────────────────────────────────

@login_required
@require_POST
def payment_mark_success(request, pk):
    payment = get_object_or_404(
        Payment.base_objects, pk=pk, tenant=request.user.tenant, is_deleted=False
    )
    method = request.POST.get("payment_method") or payment.payment_method
    ref    = request.POST.get("payment_reference", payment.payment_reference)

    PaymentService.mark_payment_success(
        payment,
        payment_method=method,
        payment_reference=ref,
    )
    messages.success(request, "Payment recorded successfully.")
    return redirect("payments:payment_detail", pk=payment.pk)


# ─── Mark Failed ─────────────────────────────────────────────────────────────

@login_required
@require_POST
def payment_mark_failed(request, pk):
    payment = get_object_or_404(
        Payment.base_objects, pk=pk, tenant=request.user.tenant, is_deleted=False
    )
    try:
        PaymentService.mark_payment_failed(payment, reason=request.POST.get("reason", ""))
        messages.warning(request, "Payment marked as failed.")
    except PaymentError as e:
        messages.error(request, str(e))
    return redirect("payments:payment_detail", pk=payment.pk)


# ─── Payment Settings ─────────────────────────────────────────────────────────

class _PaymentSettingsForm(forms.Form):
    key_id         = forms.CharField(label="Razorpay Key ID", max_length=200)
    key_secret     = forms.CharField(
        label="Razorpay Key Secret",
        max_length=200,
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Leave blank to keep existing secret.",
    )
    webhook_secret = forms.CharField(
        label="Webhook Secret",
        max_length=200,
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Leave blank to keep existing secret.",
    )
    is_active = forms.BooleanField(label="Enable Razorpay", required=False)


@login_required
def payment_settings(request):
    """
    GET  — show current Razorpay config (secrets never pre-filled).
    POST — create or update TenantPaymentConfig for the current tenant.
    """
    tenant = request.user.tenant
    config = TenantPaymentConfig.objects.filter(
        tenant=tenant, provider="razorpay"
    ).first()

    if request.method == "POST":
        form = _PaymentSettingsForm(request.POST)
        if form.is_valid():
            d = form.cleaned_data
            if config is None:
                config = TenantPaymentConfig(tenant=tenant, provider="razorpay")

            config.key_id    = d["key_id"]
            config.is_active = d["is_active"]

            # Only update secrets when a new value is supplied
            if d["key_secret"]:
                config.key_secret = d["key_secret"]
            if d["webhook_secret"]:
                config.webhook_secret = d["webhook_secret"]

            config.save()
            messages.success(request, "Razorpay settings saved.")
            return redirect("payments:payment_settings")
    else:
        initial = {}
        if config:
            initial = {"key_id": config.key_id, "is_active": config.is_active}
        form = _PaymentSettingsForm(initial=initial)

    return render(request, "payments/payment_settings.html", {
        "form":   form,
        "config": config,
    })


# ─── Record Offline Payment (Staff) ──────────────────────────────────────────

@login_required
def payment_record(request):
    """
    Staff-facing form: choose a member, pick their membership, enter amount and
    method, and immediately record the payment as SUCCESS in one step.
    """
    from members.models import Member
    from apps.memberships.models import Membership

    tenant = request.user.tenant

    # Pre-fill from query params (e.g., when arriving from member detail page)
    pre_member_id = request.GET.get("member_id", "")
    pre_ref_id    = request.GET.get("reference_id", "")

    if request.method == "POST":
        member_id      = request.POST.get("member_id", "").strip()
        reference_id   = request.POST.get("reference_id", "").strip() or None
        amount_str     = request.POST.get("amount", "0")
        method         = request.POST.get("payment_method", "")
        ref_no         = request.POST.get("payment_reference", "")
        notes          = request.POST.get("notes", "")

        try:
            amount = Decimal(amount_str)
        except Exception:
            amount = Decimal("0")

        if amount <= 0:
            messages.error(request, "Amount must be greater than zero.")
        else:
            membership = None
            if reference_id:
                try:
                    membership = Membership.base_objects.get(pk=reference_id, tenant=tenant)
                    if amount > membership.balance_amount:
                        messages.error(
                            request,
                            f"Amount ₹{amount} exceeds outstanding balance of ₹{membership.balance_amount}."
                        )
                        membership = None  # force re-render with error
                except Membership.DoesNotExist:
                    pass

            if amount > 0 and (membership is not None or not reference_id):
                try:
                    payment = PaymentService.record_offline_payment(
                        tenant=tenant,
                        amount=amount,
                        purpose="membership" if reference_id else "other",
                        reference_type="membership" if reference_id else "",
                        reference_id=reference_id,
                        payment_method=method or None,
                        payment_reference=ref_no,
                        notes=notes,
                        created_by=request.user,
                    )
                    messages.success(request, f"Payment of ₹{payment.amount} recorded successfully.")
                    return redirect("payments:payment_detail", pk=payment.pk)
                except Exception as e:
                    messages.error(request, f"Could not record payment: {e}")

    all_members = (
        Member.objects
        .filter(tenant=tenant, is_deleted=False)
        .order_by("first_name", "last_name")
    )

    pre_member     = None
    pre_membership = None
    memberships    = []

    if pre_member_id:
        try:
            pre_member  = Member.objects.get(pk=pre_member_id, tenant=tenant)
            memberships = list(
                Membership.base_objects
                .filter(member=pre_member, is_deleted=False, status__in=["pending", "active", "expired"])
                .select_related("plan")
                .order_by("-created_at")
            )
        except Member.DoesNotExist:
            pass

    if pre_ref_id and not pre_membership:
        try:
            pre_membership = Membership.base_objects.get(pk=pre_ref_id, tenant=tenant)
        except Membership.DoesNotExist:
            pass

    return render(request, "payments/payment_record.html", {
        "all_members":   all_members,
        "method_choices": PaymentMethod.choices,
        "pre_member":    pre_member,
        "pre_membership": pre_membership,
        "memberships":   memberships,
        "pre_member_id": pre_member_id,
        "pre_ref_id":    pre_ref_id,
    })


# ─── Member Memberships JSON (for payment_record member selector) ─────────────

@login_required
@require_GET
def member_memberships_json(request):
    """
    GET /payments/member-memberships/?member_id=<uuid>
    Returns JSON list of active/pending/expired memberships for the given member.
    Used by the payment_record form to populate the membership dropdown without a page reload.
    """
    from apps.memberships.models import Membership

    tenant    = request.user.tenant
    member_id = request.GET.get("member_id", "")
    if not member_id:
        return JsonResponse({"memberships": []})

    try:
        from members.models import Member
        member = Member.objects.get(pk=member_id, tenant=tenant)
    except Exception:
        return JsonResponse({"memberships": []})

    items = (
        Membership.base_objects
        .filter(member=member, is_deleted=False, status__in=["pending", "active", "expired"])
        .select_related("plan")
        .order_by("-created_at")
    )
    data = [
        {
            "id":              str(m.pk),
            "label":           f"{m.plan_name} ({m.get_status_display()}) — ₹{m.balance_amount} due",
            "balance_amount":  str(m.balance_amount),
            "fee_amount":      str(m.fee_amount),
            "amount_paid":     str(m.amount_paid),
            "status":          m.status,
        }
        for m in items
    ]
    return JsonResponse({"memberships": data})


# ─── Razorpay Checkout Page ───────────────────────────────────────────────────

@login_required
def payment_checkout(request, pk):
    """
    Render the Razorpay JS checkout page for a PENDING payment.
    On Razorpay success, posts to /payments/<pk>/verify/ to confirm.
    """
    payment = get_object_or_404(
        Payment.base_objects, pk=pk, tenant=request.user.tenant, is_deleted=False
    )

    if payment.status == PaymentStatus.SUCCESS:
        messages.success(request, "Payment already completed.")
        return redirect("payments:payment_detail", pk=payment.pk)

    if payment.status not in (PaymentStatus.CREATED, PaymentStatus.PENDING):
        messages.error(request, f"Cannot checkout a {payment.get_status_display()} payment.")
        return redirect("payments:payment_detail", pk=payment.pk)

    # Idempotent order creation — select_for_update prevents duplicate Razorpay orders
    # if the same checkout page is loaded twice in rapid succession.
    from django.db import transaction as _tx
    from apps.payments.gateways.razorpay_adapter import RazorpayAdapter, RazorpayError
    from apps.payments.services.config_service import get_active_payment_config, PaymentConfigError

    order_id  = ""
    rzp_key   = ""
    rzp_error = None

    try:
        config = get_active_payment_config(request.user.tenant, "razorpay")
        with _tx.atomic():
            locked = Payment.base_objects.select_for_update().get(pk=payment.pk)
            if locked.gateway_order_id:
                order_id = locked.gateway_order_id
            else:
                order_data = RazorpayAdapter(config).create_order(locked)
                PaymentService.mark_pending(locked, gateway_order_id=order_data["order_id"])
                order_id = order_data["order_id"]
        rzp_key = config.key_id
    except PaymentConfigError as exc:
        rzp_error = str(exc)
    except RazorpayError as exc:
        rzp_error = str(exc)
    except Exception as exc:
        rzp_error = "Unexpected error setting up checkout. Please try again."

    membership = _get_membership_context(payment.reference_type, payment.reference_id, request.user.tenant)

    return render(request, "payments/payment_checkout.html", {
        "payment":    payment,
        "order_id":   order_id,
        "rzp_key":    rzp_key,
        "rzp_error":  rzp_error,
        "membership": membership,
        "amount_paise": int(payment.amount * 100),
    })


@login_required
def payment_intelligence(request):
    from .services.payment_intelligence_service import get_payment_intelligence
    data = get_payment_intelligence(request.tenant)
    return render(request, 'payments/payment_intelligence.html', {
        'rows':           data['rows'],
        'metrics':        data['metrics'],
        'last_evaluated': data['last_evaluated'],
    })
