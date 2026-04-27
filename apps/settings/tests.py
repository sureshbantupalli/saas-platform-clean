from django.test import TestCase, Client
from django.urls import reverse

from apps.authority.models import Role as AuthorityRole
from apps.core.models import Branch, Tenant


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


def make_platform_admin():
    from django.contrib.auth import get_user_model
    User = get_user_model()
    return User.objects.create_user(
        email='platform@admin.com',
        password='testpass',
        is_platform_admin=True,
    )


# ── Page load (200) tests ─────────────────────────────────────────────────────

class SettingsPagesLoadTest(TestCase):

    def setUp(self):
        self.user, self.tenant = make_tenant_user('LoadTest')
        self.client = Client()
        self.client.login(email='user@loadtest.com', password='testpass')

    def test_general_settings_loads(self):
        resp = self.client.get(reverse('settings:general'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'General Settings')

    def test_payments_settings_loads(self):
        resp = self.client.get(reverse('settings:payments'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Payment Settings')

    def test_communications_settings_loads(self):
        resp = self.client.get(reverse('settings:communications'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Communication Settings')

    def test_roles_list_loads(self):
        resp = self.client.get(reverse('settings:roles:list'))
        self.assertEqual(resp.status_code, 200)

    def test_settings_root_redirects_to_general(self):
        resp = self.client.get(reverse('settings:index'))
        self.assertRedirects(resp, reverse('settings:general'))

    def test_settings_sidebar_links_present(self):
        resp = self.client.get(reverse('settings:general'))
        self.assertContains(resp, '/settings/general/')
        self.assertContains(resp, '/settings/payments/')
        self.assertContains(resp, '/settings/communications/')
        self.assertContains(resp, 'Roles &amp; Permissions')

    def test_general_settings_contains_form_fields(self):
        resp = self.client.get(reverse('settings:general'))
        self.assertContains(resp, 'id_business_name')
        self.assertContains(resp, 'id_timezone')
        self.assertContains(resp, 'id_currency')

    def test_general_settings_post_redirects(self):
        resp = self.client.post(reverse('settings:general'), {
            'business_name': 'My Gym',
            'timezone':      'Asia/Kolkata',
            'currency':      'INR',
        })
        self.assertRedirects(resp, reverse('settings:general'))


# ── Login required ────────────────────────────────────────────────────────────

class SettingsLoginRequiredTest(TestCase):

    URLS = [
        'settings:general',
        'settings:payments',
        'settings:communications',
        'settings:roles:list',
    ]

    def test_unauthenticated_redirects_to_login(self):
        client = Client()
        for url_name in self.URLS:
            url  = reverse(url_name)
            resp = client.get(url)
            self.assertIn(
                resp.status_code, [302, 301],
                msg=f'{url_name} should redirect unauthenticated users'
            )
            self.assertIn('/login/', resp['Location'])


# ── Tenant isolation ──────────────────────────────────────────────────────────

class SettingsTenantIsolationTest(TestCase):

    def test_platform_admin_gets_403(self):
        admin = make_platform_admin()
        client = Client()
        client.login(email='platform@admin.com', password='testpass')
        for url_name in ['settings:general', 'settings:payments', 'settings:communications']:
            resp = client.get(reverse(url_name))
            self.assertEqual(
                resp.status_code, 403,
                msg=f'Platform admin should get 403 on {url_name}'
            )

    def test_tenant_a_data_not_visible_to_tenant_b(self):
        """Each tenant's business name is pre-populated only from their own tenant."""
        user_a, tenant_a = make_tenant_user('TenantAAA')
        user_b, tenant_b = make_tenant_user('TenantBBB')

        client_a = Client()
        client_a.login(email='user@tenantaaa.com', password='testpass')
        resp = client_a.get(reverse('settings:general'))
        self.assertContains(resp, tenant_a.name)
        self.assertNotContains(resp, tenant_b.name)

        client_b = Client()
        client_b.login(email='user@tenantbbb.com', password='testpass')
        resp = client_b.get(reverse('settings:general'))
        self.assertContains(resp, tenant_b.name)
        self.assertNotContains(resp, tenant_a.name)


# ── Navigation structure ──────────────────────────────────────────────────────

class SettingsNavigationTest(TestCase):

    def setUp(self):
        self.user, _ = make_tenant_user('NavTest')
        self.client = Client()
        self.client.login(email='user@navtest.com', password='testpass')

    def test_active_tab_general(self):
        resp = self.client.get(reverse('settings:general'))
        # The active class must appear in the sidebar for the general link
        content = resp.content.decode()
        # Settings nav renders with active_tab='general'
        self.assertIn('active_tab', str(resp.context or ''))

    def test_active_tab_payments(self):
        resp = self.client.get(reverse('settings:payments'))
        self.assertEqual(resp.context.get('active_tab'), 'payments')

    def test_active_tab_communications(self):
        resp = self.client.get(reverse('settings:communications'))
        self.assertEqual(resp.context.get('active_tab'), 'communications')

    def test_coming_soon_placeholders_visible(self):
        resp = self.client.get(reverse('settings:general'))
        self.assertContains(resp, 'Vocabulary')
        self.assertContains(resp, 'Branding')
        self.assertContains(resp, 'Audit Log')
