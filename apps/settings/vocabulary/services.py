from django.core.cache import cache

from .models import TenantVocabulary

DEFAULT_VOCABULARY = {
    # Core people / scheduling
    'member':      ('Member',      'Members'),
    'enquiry':     ('Enquiry',     'Enquiries'),
    'lead':        ('Lead',        'Leads'),
    'session':     ('Session',     'Sessions'),
    'class':       ('Class',       'Classes'),
    'trainer':     ('Trainer',     'Trainers'),
    'booking':     ('Booking',     'Bookings'),
    'plan':        ('Plan',        'Plans'),
    'membership':  ('Membership',  'Memberships'),
    'attendance':  ('Attendance',  'Attendance'),
    'branch':      ('Branch',      'Branches'),
    # Financial + vertical system
    'service':     ('Service',     'Services'),
    'vertical':    ('Vertical',    'Verticals'),
    'invoice':     ('Invoice',     'Invoices'),
    'expense':     ('Expense',     'Expenses'),
    'payout':      ('Payout',      'Payouts'),
}

_CACHE_TTL = 300  # 5 minutes


def _cache_key(tenant_id):
    return f'vocab:{tenant_id}'


class VocabularyService:

    @staticmethod
    def get_labels(tenant) -> dict:
        key = _cache_key(tenant.pk)
        cached = cache.get(key)
        if cached is not None:
            return cached

        overrides = {
            v.key: (v.label, v.plural_label or v.label + 's')
            for v in TenantVocabulary.base_objects.filter(tenant=tenant)
        }

        labels = {}
        for vocab_key, (default_label, default_plural) in DEFAULT_VOCABULARY.items():
            if vocab_key in overrides:
                labels[vocab_key] = {
                    'singular': overrides[vocab_key][0],
                    'plural':   overrides[vocab_key][1],
                }
            else:
                labels[vocab_key] = {
                    'singular': default_label,
                    'plural':   default_plural,
                }

        cache.set(key, labels, _CACHE_TTL)
        return labels

    @staticmethod
    def get_label(tenant, key: str, plural: bool = False) -> str:
        labels = VocabularyService.get_labels(tenant)
        entry = labels.get(key)
        if not entry:
            return key.capitalize()
        return entry['plural'] if plural else entry['singular']

    @staticmethod
    def save_labels(tenant, overrides: dict):
        for key, (label, plural_label) in overrides.items():
            if key not in DEFAULT_VOCABULARY:
                continue
            TenantVocabulary.base_objects.update_or_create(
                tenant=tenant,
                key=key,
                defaults={'label': label, 'plural_label': plural_label},
            )
        cache.delete(_cache_key(tenant.pk))

    @staticmethod
    def invalidate(tenant):
        cache.delete(_cache_key(tenant.pk))
