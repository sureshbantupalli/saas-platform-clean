from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse

from apps.authority.models import Role as AuthorityRole
from apps.core.models import Branch, Tenant

from .models import TenantVocabulary
from .services import DEFAULT_VOCABULARY, VocabularyService


def make_tenant_user(name='Acme'):
    from django.contrib.auth import get_user_model
    User = get_user_model()
    tenant = Tenant.objects.create(name=name, subdomain=name.lower())
    Branch.objects.create(tenant=tenant, name='Main')
    role = AuthorityRole.base_objects.create(tenant=tenant, name='Staff')
    user = User.objects.create_user(
        email=f'user@{name.lower()}.com',
        password='testpass',
        tenant=tenant,
        role=role,
    )
    return user, tenant


class VocabularyDefaultsTest(TestCase):

    def setUp(self):
        _, self.tenant = make_tenant_user('DefaultsTest')
        cache.clear()

    def test_defaults_returned_when_no_override(self):
        labels = VocabularyService.get_labels(self.tenant)
        self.assertEqual(labels['member']['singular'], 'Member')
        self.assertEqual(labels['member']['plural'], 'Members')
        self.assertEqual(labels['enquiry']['singular'], 'Enquiry')

    def test_all_default_keys_present(self):
        labels = VocabularyService.get_labels(self.tenant)
        for key in DEFAULT_VOCABULARY:
            self.assertIn(key, labels, f'Missing default key: {key}')

    def test_get_label_singular(self):
        result = VocabularyService.get_label(self.tenant, 'member')
        self.assertEqual(result, 'Member')

    def test_get_label_plural(self):
        result = VocabularyService.get_label(self.tenant, 'member', plural=True)
        self.assertEqual(result, 'Members')

    def test_get_label_unknown_key_returns_capitalised(self):
        result = VocabularyService.get_label(self.tenant, 'unknown_key')
        self.assertEqual(result, 'Unknown_key')


class VocabularyOverrideTest(TestCase):

    def setUp(self):
        _, self.tenant = make_tenant_user('OverrideTest')
        cache.clear()

    def test_override_replaces_default(self):
        TenantVocabulary.base_objects.create(
            tenant=self.tenant,
            key='member',
            label='Client',
            plural_label='Clients',
        )
        labels = VocabularyService.get_labels(self.tenant)
        self.assertEqual(labels['member']['singular'], 'Client')
        self.assertEqual(labels['member']['plural'], 'Clients')

    def test_save_labels_persists_override(self):
        VocabularyService.save_labels(self.tenant, {'enquiry': ('Prospect', 'Prospects')})
        labels = VocabularyService.get_labels(self.tenant)
        self.assertEqual(labels['enquiry']['singular'], 'Prospect')
        self.assertEqual(labels['enquiry']['plural'], 'Prospects')

    def test_save_labels_ignores_unknown_keys(self):
        VocabularyService.save_labels(self.tenant, {'fake_key': ('X', 'Xs')})
        self.assertFalse(
            TenantVocabulary.base_objects.filter(tenant=self.tenant, key='fake_key').exists()
        )


class VocabularyCacheTest(TestCase):

    def setUp(self):
        _, self.tenant = make_tenant_user('CacheTest')
        cache.clear()

    def test_cache_is_populated_after_first_call(self):
        VocabularyService.get_labels(self.tenant)
        from .services import _cache_key
        cached = cache.get(_cache_key(self.tenant.pk))
        self.assertIsNotNone(cached)

    def test_invalidate_clears_cache(self):
        VocabularyService.get_labels(self.tenant)
        VocabularyService.invalidate(self.tenant)
        from .services import _cache_key
        self.assertIsNone(cache.get(_cache_key(self.tenant.pk)))

    def test_save_labels_invalidates_cache(self):
        VocabularyService.get_labels(self.tenant)  # populate
        VocabularyService.save_labels(self.tenant, {'member': ('Athlete', 'Athletes')})
        # After save, re-fetch should return new value (cache was busted)
        labels = VocabularyService.get_labels(self.tenant)
        self.assertEqual(labels['member']['singular'], 'Athlete')


class VocabularyTenantIsolationTest(TestCase):

    def setUp(self):
        cache.clear()
        _, self.tenant_a = make_tenant_user('IsoA')
        _, self.tenant_b = make_tenant_user('IsoB')

    def test_override_in_a_does_not_affect_b(self):
        TenantVocabulary.base_objects.create(
            tenant=self.tenant_a, key='member', label='Athlete', plural_label='Athletes'
        )
        labels_a = VocabularyService.get_labels(self.tenant_a)
        labels_b = VocabularyService.get_labels(self.tenant_b)
        self.assertEqual(labels_a['member']['singular'], 'Athlete')
        self.assertEqual(labels_b['member']['singular'], 'Member')  # still default


class VocabularyPageTest(TestCase):

    def setUp(self):
        self.user, _ = make_tenant_user('PageTest')
        self.client = Client()
        self.client.login(email='user@pagetest.com', password='testpass')
        cache.clear()

    def test_vocabulary_page_loads(self):
        resp = self.client.get(reverse('settings:vocabulary:vocabulary'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Vocabulary')

    def test_vocabulary_page_shows_all_keys(self):
        resp = self.client.get(reverse('settings:vocabulary:vocabulary'))
        for key in DEFAULT_VOCABULARY:
            self.assertContains(resp, key)

    def test_vocabulary_post_saves_and_redirects(self):
        resp = self.client.post(
            reverse('settings:vocabulary:vocabulary'),
            {'member_singular': 'Athlete', 'member_plural': 'Athletes'},
        )
        self.assertRedirects(resp, reverse('settings:vocabulary:vocabulary'))
        self.assertTrue(
            TenantVocabulary.base_objects.filter(key='member', label='Athlete').exists()
        )

    def test_unauthenticated_redirects(self):
        client = Client()
        resp = client.get(reverse('settings:vocabulary:vocabulary'))
        self.assertIn(resp.status_code, [301, 302])
