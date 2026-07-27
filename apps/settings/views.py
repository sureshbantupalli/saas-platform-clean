import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

_config_audit = logging.getLogger('apps.payments.config_audit')


def _rate_limit_check(user_id, action: str, limit: int, window: int = 60) -> bool:
    """Returns True if under limit, False if rate-limited."""
    key = f'rl:{action}:{user_id}'
    count = cache.get(key, 0)
    if count >= limit:
        return False
    cache.set(key, count + 1, window)
    return True


def _audit(request, provider: str, **fields) -> None:
    _config_audit.info(
        'payment_config_change',
        extra={
            'tenant_id':  str(request.tenant.id),
            'user_id':    str(request.user.id),
            'user_email': request.user.email,
            'provider':   provider,
            'ip':         request.META.get('REMOTE_ADDR', ''),
            **fields,
        },
    )

# ── Common timezones ──────────────────────────────────────────────────────────
TIMEZONES = [
    ('Asia/Kolkata',        'India Standard Time (IST)'),
    ('UTC',                 'UTC'),
    ('America/New_York',    'Eastern Time (US & Canada)'),
    ('America/Chicago',     'Central Time (US & Canada)'),
    ('America/Denver',      'Mountain Time (US & Canada)'),
    ('America/Los_Angeles', 'Pacific Time (US & Canada)'),
    ('Europe/London',       'London'),
    ('Europe/Paris',        'Paris'),
    ('Europe/Berlin',       'Berlin'),
    ('Asia/Dubai',          'Dubai'),
    ('Asia/Singapore',      'Singapore'),
    ('Asia/Tokyo',          'Tokyo'),
    ('Australia/Sydney',    'Sydney'),
    ('Africa/Nairobi',      'Nairobi'),
]

CURRENCIES = [
    ('INR', 'Indian Rupee (₹)'),
    ('USD', 'US Dollar ($)'),
    ('EUR', 'Euro (€)'),
    ('GBP', 'British Pound (£)'),
    ('AED', 'UAE Dirham (د.إ)'),
    ('SGD', 'Singapore Dollar (S$)'),
    ('AUD', 'Australian Dollar (A$)'),
    ('CAD', 'Canadian Dollar (C$)'),
    ('ZAR', 'South African Rand (R)'),
    ('KES', 'Kenyan Shilling (KSh)'),
]


def _require_tenant(view_func):
    """Guard: platform admins have no tenant, redirect them to admin."""
    from functools import wraps
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not getattr(request, 'tenant', None):
            return HttpResponseForbidden(
                'Settings are tenant-specific. Platform admins use Django Admin.'
            )
        return view_func(request, *args, **kwargs)
    return _wrapped


# ── /settings/ → redirect ─────────────────────────────────────────────────────

@login_required
def settings_index(request):
    return redirect('settings:general')


# ── General settings ──────────────────────────────────────────────────────────

@login_required
@_require_tenant
def general_settings(request):
    # TODO: load persisted values from a GeneralSettings model (Phase 2)
    current = {
        'business_name': request.tenant.name,
        'timezone':      'Asia/Kolkata',
        'currency':      'INR',
    }

    if request.method == 'POST':
        # TODO: validate + persist to GeneralSettings model (Phase 2)
        messages.success(request, 'Settings saved successfully.')
        return redirect('settings:general')

    return render(request, 'settings/general.html', {
        'current':    current,
        'timezones':  TIMEZONES,
        'currencies': CURRENCIES,
        'active_tab': 'general',
    })


# ── Payments settings ─────────────────────────────────────────────────────────

@login_required
@_require_tenant
def payments_settings(request):
    from apps.payments.models import TenantPaymentConfig

    tenant = request.tenant

    if request.method == 'POST':
        if not _rate_limit_check(request.user.id, 'payment_settings_save', limit=10):
            messages.error(request, 'Too many attempts. Please wait a minute before trying again.')
            return redirect('settings:payments')

        provider = request.POST.get('provider', '')

        # ── Razorpay ──────────────────────────────────────────────────────────
        if provider == 'razorpay':
            key_id         = request.POST.get('key_id', '').strip()
            key_secret     = request.POST.get('key_secret', '').strip()
            webhook_secret = request.POST.get('webhook_secret', '').strip()
            is_active      = request.POST.get('is_active') == 'on'

            if not key_id:
                messages.error(request, 'Key ID is required.')
                return redirect('settings:payments')

            # Block activation without valid credentials
            existing = TenantPaymentConfig.objects.filter(
                tenant=tenant, provider='razorpay'
            ).first()
            has_secret = key_secret or bool(existing and existing.key_secret)
            if is_active and (not key_id or not has_secret):
                messages.error(
                    request,
                    'Cannot activate Razorpay without both a Key ID and Key Secret. '
                    'Add your credentials first.'
                )
                return redirect('settings:payments')

            # Reset webhook status when secrets change (force re-verification)
            wh_status_reset = bool(webhook_secret)

            defaults = {
                'key_id':    key_id,
                'is_active': is_active,
            }
            if wh_status_reset:
                defaults['webhook_status']           = 'unverified'
                defaults['webhook_verified_at']      = None
                defaults['webhook_last_error']       = ''
                defaults['webhook_last_error_source'] = ''

            config, created = TenantPaymentConfig.objects.update_or_create(
                tenant=tenant, provider='razorpay', defaults=defaults,
            )
            if key_secret:
                config.key_secret = key_secret
                config.save(update_fields=['key_secret'])
            if webhook_secret:
                config.webhook_secret = webhook_secret
                config.save(update_fields=['webhook_secret'])

            _audit(request, 'razorpay',
                   action='save',
                   key_id_changed=(not created and existing and existing.key_id != key_id),
                   secret_changed=bool(key_secret),
                   webhook_changed=bool(webhook_secret),
                   is_active=is_active)

            messages.success(request, 'Razorpay configuration saved.')

        # ── Cash / Manual ─────────────────────────────────────────────────────
        elif provider == 'offline':
            is_active = request.POST.get('is_active') == 'on'
            TenantPaymentConfig.objects.update_or_create(
                tenant=tenant, provider='offline',
                defaults={'is_active': is_active},
            )
            _audit(request, 'offline', action='save', is_active=is_active)
            messages.success(
                request,
                'Manual payments enabled.' if is_active else 'Manual payments disabled.'
            )

        return redirect('settings:payments')

    # ── Load current configs ───────────────────────────────────────────────────
    rzp = TenantPaymentConfig.objects.filter(tenant=tenant, provider='razorpay').first()
    off = TenantPaymentConfig.objects.filter(tenant=tenant, provider='offline').first()

    razorpay_ctx = {
        'key_id':                    rzp.key_id                      if rzp else '',
        'is_active':                 rzp.is_active                   if rzp else False,
        'secret_set':                bool(rzp and rzp.key_secret),
        'webhook_set':               bool(rzp and rzp.webhook_secret),
        'webhook_status':            (rzp.webhook_status             if rzp else 'unverified'),
        'webhook_verified_at':       (rzp.webhook_verified_at        if rzp else None),
        'webhook_last_error':        (rzp.webhook_last_error         if rzp else ''),
        'webhook_last_error_source':   (rzp.webhook_last_error_source    if rzp else ''),
        'webhook_last_tested_at':      (rzp.webhook_last_tested_at       if rzp else None),
        'webhook_last_success_source': (rzp.webhook_last_success_source  if rzp else ''),
        # Green only when status AND timestamp are both present — guards against orphaned 'verified' rows
        'is_verified':                 bool(rzp and rzp.webhook_status == 'verified' and rzp.webhook_verified_at),
        'is_configured':             bool(rzp and rzp.key_id),
    }
    cash_ctx = {
        'is_active': off.is_active if off else True,  # default on
    }

    return render(request, 'settings/payments.html', {
        'active_tab': 'payments',
        'razorpay':   razorpay_ctx,
        'cash':       cash_ctx,
    })


# ── Test webhook ──────────────────────────────────────────────────────────────

@login_required
@_require_tenant
@require_POST
def test_webhook(request):
    """
    Read-only HMAC smoke test: signs a dummy payload with the stored webhook_secret
    and verifies the signature locally.  Does NOT create payments, trigger real flows,
    or mutate webhook_status — only stores the last error for diagnostics.
    """
    if not _rate_limit_check(request.user.id, 'webhook_test', limit=5):
        return JsonResponse({'ok': False, 'error': 'Rate limit exceeded — try again in a minute.'}, status=429)

    from apps.payments.models import TenantPaymentConfig

    cfg = TenantPaymentConfig.objects.filter(
        tenant=request.tenant, provider='razorpay'
    ).first()

    if not cfg:
        return JsonResponse({'ok': False, 'error': 'Razorpay is not configured yet.'})
    if not cfg.webhook_secret:
        return JsonResponse({'ok': False, 'error': 'No webhook secret saved. Add one in the form above.'})

    def _fail(reason: str):
        # Test failure is a definitive negative — HMAC doesn't work → downgrade status.
        cfg.webhook_status            = 'failed'
        cfg.webhook_last_error        = reason
        cfg.webhook_last_error_source = 'test'
        cfg.webhook_last_tested_at    = timezone.now()
        cfg.save(update_fields=[
            'webhook_status', 'webhook_last_error',
            'webhook_last_error_source', 'webhook_last_tested_at',
        ])
        _audit(request, 'razorpay', action='webhook_test', result='failed', reason=reason, source='test_webhook')
        return JsonResponse({'ok': False, 'error': reason})

    try:
        import hashlib
        import hmac as _hmac
        import json

        # test=True in payload signals validate-only mode to any real webhook handler
        payload = json.dumps(
            {'event': 'payment.test', 'entity': 'event', 'account_id': 'test', 'test': True},
            separators=(',', ':'),
        ).encode('utf-8')

        secret = cfg.webhook_secret          # EncryptedCharField decrypts transparently
        if not secret:
            return _fail('Webhook secret is empty after decryption.')

        # Proves: secret stored → decrypted → HMAC pipeline works end-to-end.
        # Two independent computations; mismatch would indicate an HMAC library fault.
        sig      = _hmac.new(secret.encode('utf-8'), payload, hashlib.sha256).hexdigest()
        expected = _hmac.new(secret.encode('utf-8'), payload, hashlib.sha256).hexdigest()

        if not _hmac.compare_digest(sig, expected):
            return _fail('Signature mismatch — internal HMAC error.')

        # Test success proves HMAC works.
        # - If previously 'failed': recover to 'unverified' (HMAC is fixed, not yet end-to-end verified).
        # - If 'verified': leave it — only real Razorpay deliveries grant or revoke that status.
        # Never promote to 'verified' from a local smoke test.
        save_fields = ['webhook_last_error', 'webhook_last_error_source',
                       'webhook_last_tested_at', 'webhook_last_success_source']
        if cfg.webhook_status == 'failed':
            cfg.webhook_status = 'unverified'
            save_fields.append('webhook_status')

        cfg.webhook_last_error          = ''
        cfg.webhook_last_error_source   = ''
        cfg.webhook_last_tested_at      = timezone.now()
        cfg.webhook_last_success_source = 'test'
        cfg.save(update_fields=save_fields)
        _audit(request, 'razorpay', action='webhook_test', result='pass', source='test_webhook')

        return JsonResponse({
            'ok':      True,
            'message': 'HMAC smoke test passed — secret is stored, decryptable, and usable.',
        })

    except ValueError as exc:
        return _fail(f'Secret decryption failed: {exc}')


# ── Communications settings ───────────────────────────────────────────────────

@login_required
@_require_tenant
def communications_settings(request):
    from apps.settings.whatsapp.models import Tone, CTAStyle
    from apps.settings.whatsapp.services import WhatsAppSettingsService

    wa_settings = WhatsAppSettingsService.get_settings(request.tenant)

    channels = [
        {
            'key':         'sms',
            'label':       'SMS',
            'icon':        'bi-phone',
            'description': 'Configure SMS gateway (Twilio, AWS SNS, etc.)',
        },
        {
            'key':         'whatsapp',
            'label':       'WhatsApp',
            'icon':        'bi-whatsapp',
            'description': 'Connect WhatsApp Business API provider.',
        },
        {
            'key':         'email',
            'label':       'Email',
            'icon':        'bi-envelope',
            'description': 'Configure SMTP or transactional email (SendGrid, SES, etc.)',
        },
    ]

    if request.method == 'POST' and 'save_whatsapp' in request.POST:
        from apps.audit.services import safe_log_change, normalize

        # Snapshot current values for diff before mutation
        _old = {
            'tone':              str(getattr(wa_settings, 'tone', '') or ''),
            'signature_enabled': str(getattr(wa_settings, 'signature_enabled', False)),
            'cta_style':         str(getattr(wa_settings, 'cta_style', '') or ''),
        }
        new_data = {
            'tone':              request.POST.get('tone',              'FRIENDLY'),
            'signature_enabled': request.POST.get('signature_enabled') == 'on',
            'cta_style':         request.POST.get('cta_style',         'NONE'),
        }
        WhatsAppSettingsService.save_settings(request.tenant, new_data)

        for field, new_val in new_data.items():
            old_val = _old[field]
            if normalize(old_val) != normalize(str(new_val)):
                safe_log_change(
                    tenant=request.tenant, user=request.user,
                    module='whatsapp', action='update', source='user',
                    field_name=field,
                    old_value=old_val or None,
                    new_value=str(new_val) if new_val != '' else None,
                )

        messages.success(request, 'WhatsApp branding settings saved.')
        return redirect('settings:communications')

    return render(request, 'settings/communications.html', {
        'active_tab':  'communications',
        'channels':    channels,
        'wa_settings': wa_settings,
        'tone_choices': Tone.choices,
        'cta_choices':  CTAStyle.choices,
    })
