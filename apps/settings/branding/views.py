import re

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render

from .models import TenantBranding
from .services import DEFAULTS, BrandingService

_HEX_RE = re.compile(r'^#[0-9A-Fa-f]{6}$')


def _require_tenant(request):
    if not request.user.is_authenticated:
        return redirect('/login/')
    if not getattr(request.user, 'tenant', None):
        return HttpResponseForbidden('Platform admins cannot access tenant settings.')
    return None


def branding_settings(request):
    guard = _require_tenant(request)
    if guard is not None:
        return guard

    tenant = request.user.tenant
    branding = BrandingService.get_branding(tenant)
    feature_locked = not BrandingService.is_enabled(tenant)

    if request.method == 'POST':
        if feature_locked:
            messages.error(request, 'Enable white-label branding to save changes.')
            return redirect('settings:branding:branding')

        primary   = request.POST.get('primary_color',   '').strip() or DEFAULTS['primary_color']
        secondary = request.POST.get('secondary_color', '').strip() or DEFAULTS['secondary_color']
        errors = []
        if not _HEX_RE.match(primary):
            errors.append('Primary colour must be a valid hex code, e.g. #1a2b3c.')
        if not _HEX_RE.match(secondary):
            errors.append('Secondary colour must be a valid hex code, e.g. #1a2b3c.')

        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            logo    = request.FILES.get('logo')    or None
            favicon = request.FILES.get('favicon') or None

            if request.POST.get('reset'):
                BrandingService.reset_branding(tenant)
                messages.success(request, 'Branding reset to defaults.')
            else:
                try:
                    BrandingService.save_branding(
                        tenant,
                        data={
                            'primary_color':   primary,
                            'secondary_color': secondary,
                            'login_title':     request.POST.get('login_title', '').strip(),
                            'custom_css':      request.POST.get('custom_css',  '').strip(),
                        },
                        logo=logo,
                        favicon=favicon,
                    )
                    messages.success(request, 'Branding saved.')
                except ValidationError as exc:
                    for msg in exc.messages:
                        messages.error(request, msg)

        return redirect('settings:branding:branding')

    return render(request, 'settings/branding.html', {
        'active_tab':     'branding',
        'branding':       branding,
        'feature_locked': feature_locked,
        'defaults':       DEFAULTS,
    })
