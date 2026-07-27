from django.contrib import messages
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render

from .services import DEFAULT_VOCABULARY, VocabularyService

from apps.audit.services import safe_log_change, normalize


def vocabulary_settings(request):
    if not request.user.is_authenticated:
        from django.conf import settings as django_settings
        return redirect(django_settings.LOGIN_URL)

    if not getattr(request.user, 'tenant', None):
        return HttpResponseForbidden('Platform admins cannot access tenant settings.')

    tenant = request.user.tenant
    labels = VocabularyService.get_labels(tenant)

    if request.method == 'POST':
        # Snapshot current labels before mutation for diff
        old_labels = VocabularyService.get_labels(tenant)

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

        # Log each changed key after successful save
        for key, (new_singular, new_plural) in overrides.items():
            defaults  = DEFAULT_VOCABULARY[key]
            old_entry = old_labels.get(key, {})
            old_s = old_entry.get('singular', defaults[0])
            old_p = old_entry.get('plural',   defaults[1])

            if normalize(old_s) != normalize(new_singular):
                safe_log_change(
                    tenant=tenant, user=request.user,
                    module='vocabulary', action='update', source='user',
                    field_name=f'{key}.singular',
                    old_value=old_s, new_value=new_singular,
                )
            if normalize(old_p) != normalize(new_plural):
                safe_log_change(
                    tenant=tenant, user=request.user,
                    module='vocabulary', action='update', source='user',
                    field_name=f'{key}.plural',
                    old_value=old_p, new_value=new_plural,
                )

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
