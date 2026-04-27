from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render

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
    # TODO: apply @require_permission("settings.view") once RBAC is enforced
    # TODO: load payment provider configs (Phase 3 – Payments)
    default_providers = [
        {
            'name':        'Razorpay',
            'icon':        'bi-lightning-charge',
            'description': 'Indian payment gateway — cards, UPI, net banking.',
        },
        {
            'name':        'Stripe',
            'icon':        'bi-stripe',
            'description': 'Global payment platform — cards, wallets, subscriptions.',
        },
        {
            'name':        'Cash / Manual',
            'icon':        'bi-cash-stack',
            'description': 'Record offline payments collected in person.',
        },
    ]
    return render(request, 'settings/payments.html', {
        'active_tab':        'payments',
        'default_providers': default_providers,
    })


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
        WhatsAppSettingsService.save_settings(request.tenant, {
            'tone':              request.POST.get('tone',              'FRIENDLY'),
            'signature_enabled': request.POST.get('signature_enabled') == 'on',
            'cta_style':         request.POST.get('cta_style',         'NONE'),
        })
        messages.success(request, 'WhatsApp branding settings saved.')
        return redirect('settings:communications')

    return render(request, 'settings/communications.html', {
        'active_tab':  'communications',
        'channels':    channels,
        'wa_settings': wa_settings,
        'tone_choices': Tone.choices,
        'cta_choices':  CTAStyle.choices,
    })
