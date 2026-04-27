from unittest.mock import MagicMock

from django.core.cache import cache
from django.test import TestCase, override_settings

from apps.authority.models import Role as AuthorityRole
from apps.core.models import Branch, Tenant
from apps.settings.branding.models import TenantBranding
from apps.settings.branding.services import DEFAULTS

from .branding_adapter import BrandingAdapter, _contrast_text_color, get_logo_url
from .email_renderer import (
    render_branded_email, render_branded_email_text,
    render_plain_text_email, _strip_html,
)


# ── shared helpers ────────────────────────────────────────────────────────────

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


# ── BrandingAdapter ───────────────────────────────────────────────────────────

class BrandingAdapterTest(TestCase):

    def setUp(self):
        _, self.tenant = make_tenant_user('AdapterTest')
        cache.clear()

    def test_get_branding_context_returns_required_keys(self):
        ctx = BrandingAdapter.get_branding_context(self.tenant)
        expected = {'logo_url', 'primary_color', 'secondary_color',
                    'primary_hover', 'text_color', 'brand_name'}
        self.assertEqual(set(ctx.keys()), expected)

    def test_fallback_defaults_when_no_branding(self):
        ctx = BrandingAdapter.get_branding_context(self.tenant)
        self.assertEqual(ctx['primary_color'],   DEFAULTS['primary_color'])
        self.assertEqual(ctx['secondary_color'], DEFAULTS['secondary_color'])
        self.assertEqual(ctx['logo_url'],        '')

    def test_custom_colors_used_when_whitelabel_enabled(self):
        TenantBranding.objects.create(
            tenant=self.tenant,
            primary_color='#cc0000',
            secondary_color='#003366',
            whitelabel_enabled=True,
        )
        cache.clear()
        ctx = BrandingAdapter.get_branding_context(self.tenant)
        self.assertEqual(ctx['primary_color'],   '#cc0000')
        self.assertEqual(ctx['secondary_color'], '#003366')

    def test_defaults_used_when_whitelabel_disabled(self):
        TenantBranding.objects.create(
            tenant=self.tenant,
            primary_color='#cc0000',
            whitelabel_enabled=False,
        )
        cache.clear()
        ctx = BrandingAdapter.get_branding_context(self.tenant)
        self.assertEqual(ctx['primary_color'], DEFAULTS['primary_color'])

    def test_primary_hover_is_darker_than_primary(self):
        TenantBranding.objects.create(
            tenant=self.tenant, primary_color='#0088ff', whitelabel_enabled=True,
        )
        cache.clear()
        ctx = BrandingAdapter.get_branding_context(self.tenant)
        primary = sum(int(ctx['primary_color'].lstrip('#')[i:i+2], 16) for i in (0,2,4))
        hover   = sum(int(ctx['primary_hover'].lstrip('#')[i:i+2], 16) for i in (0,2,4))
        self.assertLess(hover, primary)

    def test_brand_name_comes_from_tenant(self):
        ctx = BrandingAdapter.get_branding_context(self.tenant)
        self.assertEqual(ctx['brand_name'], 'AdapterTest')

    def test_logo_url_empty_when_no_logo(self):
        TenantBranding.objects.create(tenant=self.tenant, whitelabel_enabled=True)
        cache.clear()
        ctx = BrandingAdapter.get_branding_context(self.tenant)
        self.assertEqual(ctx['logo_url'], '')

    def test_text_color_is_string(self):
        ctx = BrandingAdapter.get_branding_context(self.tenant)
        self.assertIn(ctx['text_color'], ('#ffffff', '#000000'))

    def test_different_tenants_get_independent_branding(self):
        _, tenant_b = make_tenant_user('BrandB')
        TenantBranding.objects.create(
            tenant=self.tenant, primary_color='#ff0000', whitelabel_enabled=True,
        )
        TenantBranding.objects.create(
            tenant=tenant_b,   primary_color='#0000ff', whitelabel_enabled=True,
        )
        cache.clear()
        ctx_a = BrandingAdapter.get_branding_context(self.tenant)
        ctx_b = BrandingAdapter.get_branding_context(tenant_b)
        self.assertEqual(ctx_a['primary_color'], '#ff0000')
        self.assertEqual(ctx_b['primary_color'], '#0000ff')


# ── contrast text colour ──────────────────────────────────────────────────────

class ContrastTextColorTest(TestCase):

    def test_white_text_on_dark_background(self):
        self.assertEqual(_contrast_text_color('#000000'), '#ffffff')

    def test_black_text_on_light_background(self):
        self.assertEqual(_contrast_text_color('#ffffff'), '#000000')

    def test_white_text_on_saturated_dark_blue(self):
        self.assertEqual(_contrast_text_color('#0d3b6e'), '#ffffff')

    def test_black_text_on_light_yellow(self):
        self.assertEqual(_contrast_text_color('#ffff99'), '#000000')

    def test_returns_hex_string(self):
        result = _contrast_text_color('#aabbcc')
        self.assertIn(result, ('#ffffff', '#000000'))


# ── EmailRenderer ─────────────────────────────────────────────────────────────

@override_settings(SITE_URL='http://testserver')
class EmailRendererTest(TestCase):

    def setUp(self):
        _, self.tenant = make_tenant_user('RenderTest')
        cache.clear()

    def test_render_branded_email_returns_html_string(self):
        html = render_branded_email('Hello {{name}}', {'name': 'Alice'}, self.tenant)
        self.assertIsInstance(html, str)
        self.assertIn('<!DOCTYPE html>', html)

    def test_inner_content_substituted_in_output(self):
        html = render_branded_email('Welcome, {{member_name}}!', {'member_name': 'Bob'}, self.tenant)
        self.assertIn('Welcome, Bob!', html)

    def test_brand_name_appears_in_output(self):
        html = render_branded_email('Test', {}, self.tenant)
        self.assertIn('RenderTest', html)

    def test_primary_color_applied_in_output(self):
        TenantBranding.objects.create(
            tenant=self.tenant, primary_color='#cc1234', whitelabel_enabled=True,
        )
        cache.clear()
        html = render_branded_email('Body', {}, self.tenant)
        self.assertIn('#cc1234', html)

    def test_different_tenants_produce_different_html(self):
        _, tenant_b = make_tenant_user('OtherGym')
        TenantBranding.objects.create(
            tenant=self.tenant, primary_color='#aa0000', whitelabel_enabled=True,
        )
        TenantBranding.objects.create(
            tenant=tenant_b,   primary_color='#0000aa', whitelabel_enabled=True,
        )
        cache.clear()
        html_a = render_branded_email('Hi', {}, self.tenant)
        html_b = render_branded_email('Hi', {}, tenant_b)
        self.assertIn('#aa0000', html_a)
        self.assertIn('#0000aa', html_b)
        self.assertNotIn('#0000aa', html_a)
        self.assertNotIn('#aa0000', html_b)

    def test_fallback_works_without_branding_record(self):
        html = render_branded_email('Fallback test', {}, self.tenant)
        self.assertIn('<!DOCTYPE html>', html)
        from apps.settings.branding.services import DEFAULTS
        self.assertIn(DEFAULTS['primary_color'], html)

    def test_no_logo_renders_without_img_tag(self):
        TenantBranding.objects.create(
            tenant=self.tenant, whitelabel_enabled=True,
        )
        cache.clear()
        html = render_branded_email('No logo here', {}, self.tenant)
        # The img tag block should be absent when logo_url is empty
        self.assertNotIn('<img src=""', html)

    def test_missing_placeholder_renders_empty_not_literal(self):
        html = render_branded_email('Hello {{unknown_var}}', {}, self.tenant)
        self.assertNotIn('{{unknown_var}}', html)
        self.assertIn('Hello ', html)

    def test_html_content_not_double_escaped(self):
        # Verifies content|safe is honoured — a <strong> tag should survive
        html = render_branded_email('<strong>Bold</strong>', {}, self.tenant)
        self.assertIn('<strong>Bold</strong>', html)


# ── Plain text renderer ───────────────────────────────────────────────────────

class PlainTextRendererTest(TestCase):

    def test_renders_variables(self):
        result = render_plain_text_email('Hi {{name}}, amount: {{amount}}', {
            'name': 'Carol', 'amount': '500',
        })
        self.assertEqual(result, 'Hi Carol, amount: 500')

    def test_missing_variable_renders_empty(self):
        result = render_plain_text_email('Hi {{name}}', {})
        self.assertEqual(result, 'Hi ')

    def test_no_html_wrapper(self):
        result = render_plain_text_email('Plain content', {})
        self.assertNotIn('<!DOCTYPE', result)
        self.assertNotIn('<body', result)


# ── Integration: send_message uses branded HTML for EMAIL ─────────────────────

class SendMessageBrandingIntegrationTest(TestCase):

    def setUp(self):
        from apps.communications.models import MessageTemplate, Channel
        _, self.tenant = make_tenant_user('IntegTest')
        cache.clear()
        self.template = MessageTemplate.objects.create(
            tenant=self.tenant,
            name='Test Email',
            channel=Channel.EMAIL,
            subject='Hello {{member_name}}',
            content='<p>Dear {{member_name}}, your booking is confirmed.</p>',
        )

    def test_email_message_log_contains_html(self):
        from apps.communications.services.communication_service import send_message
        log = send_message(
            template=self.template,
            context={'member_name': 'Dave', 'email': 'dave@example.com'},
            tenant=self.tenant,
        )
        self.assertIn('<!DOCTYPE html>', log.message)
        self.assertIn('Dave', log.message)

    def test_email_message_log_contains_brand_name(self):
        from apps.communications.services.communication_service import send_message
        log = send_message(
            template=self.template,
            context={'member_name': 'Eve', 'email': 'eve@example.com'},
            tenant=self.tenant,
        )
        self.assertIn('IntegTest', log.message)

    def test_sms_message_is_plain_text(self):
        from apps.communications.models import MessageTemplate, Channel
        from apps.communications.services.communication_service import send_message
        sms_template = MessageTemplate.objects.create(
            tenant=self.tenant,
            name='Test SMS',
            channel=Channel.SMS,
            content='Hi {{member_name}}, your booking is confirmed.',
        )
        log = send_message(
            template=sms_template,
            context={'member_name': 'Frank', 'phone': '+911234567890'},
            tenant=self.tenant,
        )
        self.assertNotIn('<!DOCTYPE html>', log.message)
        self.assertIn('Frank', log.message)


# ── get_logo_url robustness ───────────────────────────────────────────────────

class GetLogoUrlTest(TestCase):

    def _make_branding_with_logo(self, tenant):
        """Return a TenantBranding mock whose .logo.url returns a relative path."""
        branding = MagicMock()
        branding.logo.url = '/media/tenant/logos/logo.png'
        return branding

    def setUp(self):
        _, self.tenant = make_tenant_user('LogoUrlTest')
        self.branding  = self._make_branding_with_logo(self.tenant)

    @override_settings(SITE_URL='https://cdn.example.com')
    def test_site_url_used_when_configured(self):
        url = get_logo_url(self.branding)
        self.assertEqual(url, 'https://cdn.example.com/media/tenant/logos/logo.png')

    @override_settings(SITE_URL='https://cdn.example.com/')
    def test_no_double_slash_when_site_url_has_trailing_slash(self):
        url = get_logo_url(self.branding)
        self.assertNotIn('//', url.split('https://')[1])

    @override_settings(SITE_URL='')
    def test_request_build_absolute_uri_used_as_fallback(self):
        request = MagicMock()
        request.build_absolute_uri.return_value = 'http://testserver/media/tenant/logos/logo.png'
        url = get_logo_url(self.branding, request=request)
        self.assertEqual(url, 'http://testserver/media/tenant/logos/logo.png')
        request.build_absolute_uri.assert_called_once_with('/media/tenant/logos/logo.png')

    @override_settings(SITE_URL='https://cdn.example.com')
    def test_site_url_preferred_over_request(self):
        request = MagicMock()
        request.build_absolute_uri.return_value = 'http://django-server/media/logo.png'
        url = get_logo_url(self.branding, request=request)
        self.assertIn('cdn.example.com', url)
        request.build_absolute_uri.assert_not_called()

    @override_settings(SITE_URL='')
    def test_returns_empty_when_no_site_url_and_no_request(self):
        url = get_logo_url(self.branding)
        self.assertEqual(url, '')

    def test_returns_empty_when_no_logo(self):
        branding = MagicMock()
        branding.logo = None
        self.assertEqual(get_logo_url(branding), '')

    def test_returns_empty_when_branding_is_none(self):
        self.assertEqual(get_logo_url(None), '')


# ── _strip_html ───────────────────────────────────────────────────────────────

class StripHtmlTest(TestCase):

    def test_removes_tags(self):
        self.assertEqual(_strip_html('<p>Hello</p>'), 'Hello')

    def test_br_becomes_newline(self):
        result = _strip_html('Line one<br>Line two')
        self.assertIn('Line one', result)
        self.assertIn('Line two', result)

    def test_decodes_entities(self):
        self.assertIn('&', _strip_html('A &amp; B'))
        self.assertNotIn('&amp;', _strip_html('A &amp; B'))

    def test_no_excessive_blank_lines(self):
        result = _strip_html('<p>A</p>\n\n\n\n<p>B</p>')
        self.assertNotIn('\n\n\n', result)

    def test_plain_text_passes_through(self):
        self.assertEqual(_strip_html('Just text'), 'Just text')


# ── render_branded_email_text ─────────────────────────────────────────────────

@override_settings(SITE_URL='http://testserver')
class BrandedEmailTextTest(TestCase):

    def setUp(self):
        _, self.tenant = make_tenant_user('TextTest')
        cache.clear()

    def test_returns_string(self):
        result = render_branded_email_text('Hello {{name}}', {'name': 'Alice'}, self.tenant)
        self.assertIsInstance(result, str)

    def test_contains_substituted_content(self):
        result = render_branded_email_text('Welcome, {{member_name}}!', {'member_name': 'Bob'}, self.tenant)
        self.assertIn('Bob', result)

    def test_contains_brand_name(self):
        result = render_branded_email_text('Test', {}, self.tenant)
        self.assertIn('TextTest', result)

    def test_no_html_tags_in_output(self):
        result = render_branded_email_text('<p>Hello <strong>{{name}}</strong></p>', {'name': 'Carol'}, self.tenant)
        self.assertNotIn('<p>', result)
        self.assertNotIn('<strong>', result)
        self.assertIn('Carol', result)

    def test_no_doctype_or_html_in_output(self):
        result = render_branded_email_text('Body', {}, self.tenant)
        self.assertNotIn('<!DOCTYPE', result)
        self.assertNotIn('<html', result)

    def test_missing_placeholder_renders_empty_not_literal(self):
        result = render_branded_email_text('Amount: {{amount}}', {}, self.tenant)
        self.assertNotIn('{{amount}}', result)

    def test_footer_phone_included_when_in_context(self):
        result = render_branded_email_text(
            'Message', {'footer_phone': '+91 9876543210'}, self.tenant
        )
        self.assertIn('+91 9876543210', result)

    def test_different_tenants_produce_different_text(self):
        _, tenant_b = make_tenant_user('OtherGym')
        result_a = render_branded_email_text('Hi', {}, self.tenant)
        result_b = render_branded_email_text('Hi', {}, tenant_b)
        self.assertIn('TextTest', result_a)
        self.assertIn('OtherGym', result_b)
        self.assertNotIn('OtherGym', result_a)


# ── Subject branding ──────────────────────────────────────────────────────────

class SubjectBrandingTest(TestCase):

    def setUp(self):
        from apps.communications.models import MessageTemplate, Channel
        _, self.tenant = make_tenant_user('SubjTest')
        cache.clear()
        self.template = MessageTemplate.objects.create(
            tenant=self.tenant,
            name='Payment Email',
            channel=Channel.EMAIL,
            subject='Payment Successful',
            content='Your payment is done.',
        )

    @override_settings(COMMS_BRAND_EMAIL_SUBJECT=True)
    def test_subject_prefixed_when_flag_enabled(self):
        from apps.communications.services.communication_service import send_message
        log = send_message(
            template=self.template,
            context={'email': 'x@x.com'},
            tenant=self.tenant,
        )
        self.assertEqual(log.subject, '[SubjTest] Payment Successful')

    @override_settings(COMMS_BRAND_EMAIL_SUBJECT=False)
    def test_subject_unchanged_when_flag_disabled(self):
        from apps.communications.services.communication_service import send_message
        log = send_message(
            template=self.template,
            context={'email': 'x@x.com'},
            tenant=self.tenant,
        )
        self.assertEqual(log.subject, 'Payment Successful')

    @override_settings(COMMS_BRAND_EMAIL_SUBJECT=True)
    def test_no_prefix_when_subject_empty(self):
        from apps.communications.models import MessageTemplate, Channel
        from apps.communications.services.communication_service import send_message
        t = MessageTemplate.objects.create(
            tenant=self.tenant, name='No Subject Email',
            channel=Channel.EMAIL, subject='', content='Body.',
        )
        log = send_message(template=t, context={'email': 'x@x.com'}, tenant=self.tenant)
        self.assertEqual(log.subject, '')

    @override_settings(COMMS_BRAND_EMAIL_SUBJECT=True)
    def test_sms_subject_not_prefixed(self):
        from apps.communications.models import MessageTemplate, Channel
        from apps.communications.services.communication_service import send_message
        sms = MessageTemplate.objects.create(
            tenant=self.tenant, name='SMS',
            channel=Channel.SMS, content='Hi {{name}}.',
        )
        log = send_message(
            template=sms,
            context={'name': 'Dave', 'phone': '+911234567890'},
            tenant=self.tenant,
        )
        self.assertEqual(log.subject, '')


# ── Multi-tenant cache isolation (branding service layer) ─────────────────────

class BrandingCacheIsolationTest(TestCase):

    def setUp(self):
        cache.clear()
        _, self.tenant_a = make_tenant_user('CacheA')
        _, self.tenant_b = make_tenant_user('CacheB')

    def test_cache_keys_are_tenant_scoped(self):
        from apps.settings.branding.services import _cache_key
        key_a = _cache_key(self.tenant_a.pk)
        key_b = _cache_key(self.tenant_b.pk)
        self.assertNotEqual(key_a, key_b)
        self.assertIn(str(self.tenant_a.pk), key_a)
        self.assertIn(str(self.tenant_b.pk), key_b)

    def test_save_branding_invalidates_only_own_tenant_cache(self):
        from apps.settings.branding.services import BrandingService, _cache_key
        TenantBranding.objects.create(tenant=self.tenant_a, primary_color='#aaaaaa', whitelabel_enabled=True)
        TenantBranding.objects.create(tenant=self.tenant_b, primary_color='#bbbbbb', whitelabel_enabled=True)
        BrandingService.get_branding(self.tenant_a)  # populate cache
        BrandingService.get_branding(self.tenant_b)  # populate cache

        BrandingService.save_branding(self.tenant_a, {'primary_color': '#cccccc'})

        sentinel = object()
        # A's cache is invalidated
        self.assertIs(cache.get(_cache_key(self.tenant_a.pk), sentinel), sentinel)
        # B's cache is still warm
        self.assertIsNotNone(cache.get(_cache_key(self.tenant_b.pk), sentinel))

    def test_adapter_returns_independent_contexts(self):
        TenantBranding.objects.create(tenant=self.tenant_a, primary_color='#ff0000', whitelabel_enabled=True)
        TenantBranding.objects.create(tenant=self.tenant_b, primary_color='#0000ff', whitelabel_enabled=True)
        cache.clear()
        ctx_a = BrandingAdapter.get_branding_context(self.tenant_a)
        ctx_b = BrandingAdapter.get_branding_context(self.tenant_b)
        self.assertEqual(ctx_a['primary_color'], '#ff0000')
        self.assertEqual(ctx_b['primary_color'], '#0000ff')
