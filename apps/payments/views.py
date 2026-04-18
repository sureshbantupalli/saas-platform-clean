from decimal import Decimal

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

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
    qs = Payment.base_objects.filter(
        tenant=request.user.tenant, is_deleted=False
    ).select_related("created_by").order_by("-created_at")

    ref_type = request.GET.get("ref_type")
    ref_id   = request.GET.get("ref_id")
    if ref_type and ref_id:
        qs = qs.filter(reference_type=ref_type, reference_id=ref_id)

    status_filter = request.GET.get("status")
    if status_filter:
        qs = qs.filter(status=status_filter)

    return render(request, "payments/payment_list.html", {
        "payments":       qs,
        "status_choices": PaymentStatus.choices,
        "ref_type":       ref_type,
        "ref_id":         ref_id,
    })


# ─── Payment Detail ──────────────────────────────────────────────────────────

@login_required
def payment_detail(request, pk):
    payment = get_object_or_404(
        Payment.base_objects, pk=pk, tenant=request.user.tenant, is_deleted=False
    )
    events = payment.events.order_by("created_at")
    membership = _get_membership_context(
        payment.reference_type, payment.reference_id, request.user.tenant
    )
    return render(request, "payments/payment_detail.html", {
        "payment":    payment,
        "events":     events,
        "membership": membership,
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
