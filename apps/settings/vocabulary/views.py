from django.contrib import messages
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render

from .services import DEFAULT_VOCABULARY, VocabularyService


def vocabulary_settings(request):
    if not request.user.is_authenticated:
        from django.conf import settings as django_settings
        return redirect(django_settings.LOGIN_URL)

    if not getattr(request.user, 'tenant', None):
        return HttpResponseForbidden('Platform admins cannot access tenant settings.')

    tenant = request.user.tenant
    labels = VocabularyService.get_labels(tenant)

    if request.method == 'POST':
        overrides = {}
        for key in DEFAULT_VOCABULARY:
            singular = request.POST.get(f'{key}_singular', '').strip()
            plural   = request.POST.get(f'{key}_plural',   '').strip()
            default_s, default_p = DEFAULT_VOCABULARY[key]
            if singular and singular != default_s:
                overrides[key] = (singular, plural or singular + 's')
            elif plural and plural != default_p:
                overrides[key] = (singular or default_s, plural)
        VocabularyService.save_labels(tenant, overrides)
        messages.success(request, 'Vocabulary saved.')
        return redirect('settings:vocabulary:vocabulary')

    rows = []
    for key, defaults in DEFAULT_VOCABULARY.items():
        entry = labels.get(key, {})
        rows.append({
            'key':             key,
            'default_singular': defaults[0],
            'default_plural':   defaults[1],
            'singular':         entry.get('singular', defaults[0]),
            'plural':           entry.get('plural',   defaults[1]),
        })

    return render(request, 'settings/vocabulary.html', {
        'active_tab': 'vocabulary',
        'rows':       rows,
    })
