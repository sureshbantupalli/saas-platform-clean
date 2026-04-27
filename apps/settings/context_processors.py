from apps.settings.vocabulary.services import VocabularyService

_CSS_DEFAULTS = {
    'b_primary':         '#0d6efd',
    'b_primary_rgb':     '13, 110, 253',
    'b_primary_hover':   '#0b5ed7',
    'b_secondary':       '#6c757d',
    'b_secondary_hover': '#5c636a',
}


def _get_tenant(request):
    tenant = getattr(request, 'tenant', None)
    if tenant is None and request.user.is_authenticated:
        tenant = getattr(request.user, 'tenant', None)
    return tenant


def vocabulary_labels(request):
    tenant = _get_tenant(request)
    if not tenant:
        return {'labels': {}}
    return {'labels': VocabularyService.get_labels(tenant)}


def tenant_branding(request):
    tenant = _get_tenant(request)
    if not tenant:
        return {'tenant_branding': None, **_CSS_DEFAULTS}

    from apps.settings.branding.services import BrandingService
    branding = BrandingService.get_branding(tenant)
    css_vars  = BrandingService.get_css_vars(tenant)

    return {
        'tenant_branding':   branding,
        'b_primary':         css_vars['--primary-color'],
        'b_primary_rgb':     css_vars['--primary-rgb'],
        'b_primary_hover':   css_vars['--primary-hover'],
        'b_secondary':       css_vars['--secondary-color'],
        'b_secondary_hover': css_vars['--secondary-hover'],
    }
