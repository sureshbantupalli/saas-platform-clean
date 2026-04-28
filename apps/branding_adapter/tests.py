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


# ── WhatsAppBrandingAdapter ───────────────────────────────────────────────────

class WhatsAppAdapterTest(TestCase):
    """Unit tests for WhatsAppBrandingAdapter.format_message()."""

    def setUp(self):
        _, self.tenant = make_tenant_user('WATest')
        cache.clear()

    # helper
    def _make_settings(self, **kwargs):
        from apps.settings.whatsapp.models import TenantWhatsAppSettings
        defaults = dict(
            tone='FRIENDLY',
            signature_enabled=True,
            cta_style='NONE',
            template_overrides={},
        )
        defaults.update(kwargs)
        obj, _ = TenantWhatsAppSettings.objects.get_or_create(tenant=self.tenant)
        for k, v in defaults.items():
            setattr(obj, k, v)
        obj.save()
        cache.delete(f'wa_settings:{self.tenant.pk}')
        return obj

    def _fmt(self, content='Hello.', context=None, event='test.event'):
        from apps.branding_adapter.whatsapp_adapter import WhatsAppBrandingAdapter
        return WhatsAppBrandingAdapter.format_message(
            event=event, content=content, context=context or {}, tenant=self.tenant,
        )

    # ── tone ──────────────────────────────────────────────────────────────────

    def test_friendly_tone_prepends_hi_greeting(self):
        self._make_settings(tone='FRIENDLY')
        result = self._fmt(context={'member_name': 'Alice'})
        self.assertTrue(result.startswith('Hi Alice!'))

    def test_formal_tone_prepends_dear_greeting(self):
        self._make_settings(tone='FORMAL')
        result = self._fmt(context={'member_name': 'Alice'})
        self.assertTrue(result.startswith('Dear Alice,'))

    def test_minimal_tone_has_no_greeting(self):
        self._make_settings(tone='MINIMAL')
        result = self._fmt(content='Your membership is active.', context={})
        self.assertFalse(result.startswith('Hi') or result.startswith('Dear'))
        self.assertIn('Your membership is active.', result)

    def test_greeting_uses_name_key_fallback(self):
        self._make_settings(tone='FRIENDLY')
        result = self._fmt(context={'name': 'Bob'})
        self.assertIn('Hi Bob!', result)

    def test_greeting_empty_name_graceful(self):
        self._make_settings(tone='FRIENDLY')
        result = self._fmt(context={})
        self.assertIn('Hi !', result)

    # ── signature ────────────────────────────────────────────────────────────

    def test_signature_enabled_appends_brand_name(self):
        self._make_settings(signature_enabled=True)
        result = self._fmt()
        self.assertIn(f'— {self.tenant.name}', result)

    def test_signature_disabled_excludes_brand_name(self):
        self._make_settings(signature_enabled=False)
        result = self._fmt()
        self.assertNotIn('—', result)

    # ── CTA ───────────────────────────────────────────────────────────────────

    def test_cta_pay_now_with_payment_link(self):
        self._make_settings(cta_style='PAY_NOW')
        result = self._fmt(context={'payment_link': 'https://pay.example.com/abc'})
        self.assertIn('Click here to pay: https://pay.example.com/abc', result)

    def test_cta_pay_now_without_link_no_cta(self):
        self._make_settings(cta_style='PAY_NOW')
        result = self._fmt(context={})
        self.assertNotIn('Click here to pay', result)

    def test_cta_confirm_appends_reply_yes(self):
        self._make_settings(cta_style='CONFIRM')
        result = self._fmt()
        self.assertIn('Reply YES to confirm.', result)

    def test_cta_contact_with_phone(self):
        self._make_settings(cta_style='CONTACT')
        result = self._fmt(context={'support_phone': '+911234567890'})
        self.assertIn('Call us at +911234567890', result)

    def test_cta_none_adds_nothing(self):
        self._make_settings(cta_style='NONE')
        result = self._fmt(content='Done.', context={})
        self.assertNotIn('Click here', result)
        self.assertNotIn('Reply YES', result)
        self.assertNotIn('Call us', result)

    # ── template overrides ───────────────────────────────────────────────────

    def test_event_override_replaces_content(self):
        self._make_settings(
            template_overrides={'membership.activated': 'Custom: {{member_name}} activated!'},
        )
        result = self._fmt(
            content='Generic content.',
            context={'member_name': 'Carol'},
            event='membership.activated',
        )
        self.assertIn('Custom: Carol activated!', result)
        self.assertNotIn('Generic content.', result)

    def test_no_override_uses_content(self):
        self._make_settings(template_overrides={})
        result = self._fmt(content='Default content.', context={})
        self.assertIn('Default content.', result)

    def test_unmatched_event_override_uses_content(self):
        self._make_settings(template_overrides={'other.event': 'Other.'})
        result = self._fmt(content='My content.', event='membership.activated', context={})
        self.assertIn('My content.', result)

    # ── variable substitution ────────────────────────────────────────────────

    def test_placeholder_substituted_in_body(self):
        self._make_settings(tone='MINIMAL', signature_enabled=False)
        result = self._fmt(content='Hi {{member_name}}, amount: {{amount}}',
                           context={'member_name': 'Dave', 'amount': '500'})
        self.assertIn('Hi Dave, amount: 500', result)

    def test_missing_placeholder_renders_empty(self):
        self._make_settings(tone='MINIMAL', signature_enabled=False)
        result = self._fmt(content='Amount: {{amount}}', context={})
        self.assertNotIn('{{amount}}', result)

    # ── fallback with no settings record ─────────────────────────────────────

    def test_no_settings_record_uses_defaults(self):
        from apps.branding_adapter.whatsapp_adapter import WhatsAppBrandingAdapter
        # No TenantWhatsAppSettings created — falls back to FRIENDLY + signature
        result = WhatsAppBrandingAdapter.format_message(
            event='test', content='Hello.', context={'member_name': 'Eve'}, tenant=self.tenant,
        )
        self.assertIn('Hi Eve!', result)
        self.assertIn('Hello.', result)
        self.assertIn(f'— {self.tenant.name}', result)

    # ── tenant isolation ──────────────────────────────────────────────────────

    def test_different_tenants_independent_settings(self):
        from apps.settings.whatsapp.models import TenantWhatsAppSettings
        from apps.branding_adapter.whatsapp_adapter import WhatsAppBrandingAdapter
        _, tenant_b = make_tenant_user('WATest2')

        self._make_settings(tone='FORMAL')
        TenantWhatsAppSettings.objects.get_or_create(tenant=tenant_b)
        obj_b = TenantWhatsAppSettings.objects.get(tenant=tenant_b)
        obj_b.tone = 'MINIMAL'
        obj_b.signature_enabled = False
        obj_b.save()
        cache.delete(f'wa_settings:{tenant_b.pk}')

        result_a = WhatsAppBrandingAdapter.format_message(
            event='test', content='Body.', context={'member_name': 'X'}, tenant=self.tenant,
        )
        result_b = WhatsAppBrandingAdapter.format_message(
            event='test', content='Body.', context={'member_name': 'X'}, tenant=tenant_b,
        )
        self.assertIn('Dear X,', result_a)
        self.assertNotIn('Dear', result_b)


# ── WhatsApp communication_service integration ────────────────────────────────

class WhatsAppCommunicationServiceTest(TestCase):
    """Integration: send_message applies WhatsApp branding for WHATSAPP channel."""

    def setUp(self):
        from apps.communications.models import MessageTemplate, Channel
        _, self.tenant = make_tenant_user('WAIntegTest')
        cache.clear()
        self.template = MessageTemplate.objects.create(
            tenant=self.tenant,
            name='WA Membership',
            channel=Channel.WHATSAPP,
            content='Your membership {{plan}} is now active.',
        )

    def test_whatsapp_message_has_greeting(self):
        from apps.communications.services.communication_service import send_message
        log = send_message(
            template=self.template,
            context={'member_name': 'Frank', 'plan': 'Gold', 'phone': '+911234567890'},
            tenant=self.tenant,
        )
        self.assertIn('Hi Frank!', log.message)
        self.assertIn('Gold', log.message)

    def test_whatsapp_message_has_signature_by_default(self):
        from apps.communications.services.communication_service import send_message
        log = send_message(
            template=self.template,
            context={'member_name': 'Grace', 'plan': 'Silver', 'phone': '+911234567890'},
            tenant=self.tenant,
        )
        self.assertIn(f'— {self.tenant.name}', log.message)

    def test_whatsapp_message_not_html(self):
        from apps.communications.services.communication_service import send_message
        log = send_message(
            template=self.template,
            context={'member_name': 'Hank', 'plan': 'Basic', 'phone': '+911234567890'},
            tenant=self.tenant,
        )
        self.assertNotIn('<!DOCTYPE html>', log.message)
        self.assertNotIn('<p>', log.message)

    def test_whatsapp_uses_template_override_from_settings(self):
        from apps.settings.whatsapp.models import TenantWhatsAppSettings
        from apps.communications.services.communication_service import send_message
        TenantWhatsAppSettings.objects.create(
            tenant=self.tenant,
            tone='MINIMAL',
            signature_enabled=False,
            cta_style='NONE',
            template_overrides={'membership.activated': 'Custom WA: {{member_name}}'},
        )
        cache.delete(f'wa_settings:{self.tenant.pk}')
        log = send_message(
            template=self.template,
            context={'member_name': 'Ivy', 'plan': 'Gold', 'phone': '+911234567890'},
            tenant=self.tenant,
            event_type='membership.activated',
        )
        self.assertIn('Custom WA: Ivy', log.message)
        self.assertNotIn('Your membership', log.message)


# ── WhatsApp adapter hardening tests ─────────────────────────────────────────

class WhatsAppAdapterHardeningTest(TestCase):
    """
    Covers the 7 hardening improvements:
      1. Missing-var structured warning
      2. Tone registry extensibility contract
      3. link_service delegation
      4. CTA registry independence
      5. Message length guard
      6. Idempotent formatting (no duplicate signature/CTA on retry)
      7. CTA + signature order, long content edge case
    """

    def setUp(self):
        _, self.tenant = make_tenant_user('HardenTest')
        cache.clear()

    def _make_settings(self, **kwargs):
        from apps.settings.whatsapp.models import TenantWhatsAppSettings
        defaults = dict(tone='FRIENDLY', signature_enabled=True, cta_style='NONE', template_overrides={})
        defaults.update(kwargs)
        obj, _ = TenantWhatsAppSettings.objects.get_or_create(tenant=self.tenant)
        for k, v in defaults.items():
            setattr(obj, k, v)
        obj.save()
        cache.delete(f'wa_settings:{self.tenant.pk}')
        return obj

    def _fmt(self, content='Hello.', context=None, event='test.event'):
        from apps.branding_adapter.whatsapp_adapter import WhatsAppBrandingAdapter
        return WhatsAppBrandingAdapter.format_message(
            event=event, content=content, context=context or {}, tenant=self.tenant,
        )

    # 1. Missing-var warning ───────────────────────────────────────────────────

    def test_missing_var_emits_structured_warning(self):
        self._make_settings(tone='MINIMAL', signature_enabled=False)
        with self.assertLogs('apps.branding_adapter', level='WARNING') as cm:
            self._fmt(content='Hi {{member_name}}, amount: {{amount}}', context={})
        reasons = [getattr(r, 'reason', '') for r in cm.records]
        self.assertIn('missing_template_vars', reasons)

    def test_missing_var_still_renders_without_raising(self):
        self._make_settings(tone='MINIMAL', signature_enabled=False)
        result = self._fmt(content='Amount: {{amount}}', context={})
        self.assertIsInstance(result, str)
        self.assertNotIn('{{amount}}', result)

    def test_no_warning_when_all_vars_present(self):
        self._make_settings(tone='MINIMAL', signature_enabled=False)
        import logging
        with self.assertLogs('apps.branding_adapter', level='DEBUG') as cm:
            # Emit a DEBUG so assertLogs doesn't fail when no WARNING is issued
            logging.getLogger('apps.branding_adapter').debug('sentinel')
            self._fmt(content='Hi {{name}}', context={'name': 'Alice'})
        warnings = [line for line in cm.output if 'missing_template_vars' in line]
        self.assertEqual(warnings, [])

    # 2. Tone registry contract ────────────────────────────────────────────────

    def test_greeting_registry_contains_all_required_tones(self):
        from apps.branding_adapter.whatsapp_adapter import GREETING_REGISTRY
        for tone in ('FORMAL', 'FRIENDLY', 'MINIMAL'):
            self.assertIn(tone, GREETING_REGISTRY)

    def test_greeting_registry_unknown_tone_falls_back_to_friendly(self):
        self._make_settings(tone='FORMAL')  # we'll override at adapter level
        from apps.branding_adapter.whatsapp_adapter import _build_greeting
        result = _build_greeting('UNKNOWN_TONE', {'member_name': 'Bob'})
        self.assertIn('Hi Bob!', result)

    # 3. link_service delegation ───────────────────────────────────────────────

    def test_link_service_brand_link_returns_url_unchanged_by_default(self):
        from apps.branding_adapter.link_service import brand_link
        url = 'https://pay.example.com/xyz'
        self.assertEqual(brand_link(url, self.tenant), url)

    def test_link_service_brand_links_in_text_rewrites_all_urls(self):
        from apps.branding_adapter.link_service import brand_links_in_text
        # With no custom domain configured, URLs pass through unchanged
        text = 'Pay here: https://a.com/pay or visit https://b.com/info'
        result = brand_links_in_text(text, self.tenant)
        self.assertIn('https://a.com/pay', result)
        self.assertIn('https://b.com/info', result)

    def test_adapter_uses_link_service_not_inline_regex(self):
        # Patch link_service to verify adapter delegates to it
        from unittest.mock import patch
        self._make_settings(tone='MINIMAL', signature_enabled=False)
        with patch('apps.branding_adapter.whatsapp_adapter.brand_links_in_text',
                   wraps=lambda t, _: t) as mock_ls:
            self._fmt(content='Pay here: https://pay.example.com/abc',
                      context={'payment_link': 'https://pay.example.com/abc'})
        mock_ls.assert_called_once()

    # 4. CTA registry independence ─────────────────────────────────────────────

    def test_cta_registry_all_styles_callable(self):
        from apps.branding_adapter.cta_registry import CTA_REGISTRY
        for style in ('PAY_NOW', 'CONFIRM', 'CONTACT', 'NONE'):
            self.assertIn(style, CTA_REGISTRY)
            result = CTA_REGISTRY[style]({'payment_link': 'https://x.com', 'phone': '+91999'})
            self.assertIsInstance(result, str)

    def test_build_cta_unknown_style_returns_empty(self):
        from apps.branding_adapter.cta_registry import build_cta
        self.assertEqual(build_cta('TOTALLY_UNKNOWN', {}), '')

    def test_adapter_uses_registry_not_inline_logic(self):
        from unittest.mock import patch
        self._make_settings(cta_style='CONFIRM')
        with patch('apps.branding_adapter.whatsapp_adapter.build_cta',
                   wraps=lambda style, ctx: '\n\nReply YES to confirm.') as mock_cta:
            self._fmt()
        mock_cta.assert_called_once()

    # 5. Message length guard ─────────────────────────────────────────────────

    def test_soft_limit_warning_emitted_for_long_message(self):
        self._make_settings(tone='MINIMAL', signature_enabled=False)
        long_body = 'A' * 1_700
        with self.assertLogs('apps.branding_adapter', level='WARNING') as cm:
            self._fmt(content=long_body)
        reasons = [getattr(r, 'reason', '') for r in cm.records]
        self.assertIn('message_long', reasons)

    def test_hard_limit_truncates_message(self):
        self._make_settings(tone='MINIMAL', signature_enabled=False)
        long_body = 'B' * 5_000
        result = self._fmt(content=long_body)
        self.assertLessEqual(len(result), 4_096)

    def test_hard_limit_warning_emitted_when_truncated(self):
        self._make_settings(tone='MINIMAL', signature_enabled=False)
        long_body = 'C' * 5_000
        with self.assertLogs('apps.branding_adapter', level='WARNING') as cm:
            self._fmt(content=long_body)
        reasons = [getattr(r, 'reason', '') for r in cm.records]
        self.assertIn('message_too_long', reasons)

    def test_normal_length_message_no_length_warning(self):
        self._make_settings(tone='MINIMAL', signature_enabled=False)
        import logging
        with self.assertLogs('apps.branding_adapter', level='DEBUG') as cm:
            logging.getLogger('apps.branding_adapter').debug('sentinel')
            self._fmt(content='Short message.')
        length_warnings = [l for l in cm.output if 'message_too_long' in l or 'message_long' in l]
        self.assertEqual(length_warnings, [])

    # 6. Idempotent formatting ────────────────────────────────────────────────

    def test_calling_format_twice_does_not_duplicate_signature(self):
        self._make_settings(tone='MINIMAL', signature_enabled=True, cta_style='NONE')
        first  = self._fmt(content='Membership active.')
        # simulate retry: pass already-formatted message as content
        second = self._fmt(content=first)
        sig = f'— {self.tenant.name}'
        self.assertEqual(second.count(sig), 1, "signature should appear exactly once")

    def test_calling_format_twice_does_not_duplicate_cta(self):
        self._make_settings(tone='MINIMAL', signature_enabled=False, cta_style='CONFIRM')
        first  = self._fmt(content='Please confirm.')
        second = self._fmt(content=first)
        self.assertEqual(second.count('Reply YES to confirm.'), 1,
                         "CTA should appear exactly once")

    def test_calling_format_twice_does_not_duplicate_pay_now_cta(self):
        self._make_settings(tone='MINIMAL', signature_enabled=False, cta_style='PAY_NOW')
        first  = self._fmt(content='Your invoice.', context={'payment_link': 'https://pay.example.com/1'})
        second = self._fmt(content=first, context={'payment_link': 'https://pay.example.com/1'})
        self.assertEqual(second.count('Click here to pay:'), 1)

    # 7a. CTA + signature correct order ───────────────────────────────────────

    def test_signature_appears_before_cta(self):
        self._make_settings(signature_enabled=True, cta_style='CONFIRM', tone='MINIMAL')
        result = self._fmt(content='Your booking is confirmed.')
        sig_pos = result.find(f'— {self.tenant.name}')
        cta_pos = result.find('Reply YES to confirm.')
        self.assertGreater(sig_pos, 0, "signature should be present")
        self.assertGreater(cta_pos, 0, "CTA should be present")
        self.assertLess(sig_pos, cta_pos, "signature must come before CTA")

    def test_cta_and_signature_both_present_and_distinct(self):
        self._make_settings(signature_enabled=True, cta_style='CONFIRM', tone='FRIENDLY')
        result = self._fmt(content='Booking confirmed.', context={'member_name': 'Jay'})
        self.assertIn(f'— {self.tenant.name}', result)
        self.assertIn('Reply YES to confirm.', result)

    # 7b. Long content edge case ──────────────────────────────────────────────

    def test_long_content_preserves_structure(self):
        # Signature and CTA must still be appended even when body is near the limit
        self._make_settings(signature_enabled=True, cta_style='CONFIRM', tone='MINIMAL')
        # 1500 chars — fits under soft limit, well under hard limit after sig+CTA
        result = self._fmt(content='X' * 1_500)
        self.assertIn(f'— {self.tenant.name}', result)
        self.assertIn('Reply YES to confirm.', result)

    def test_long_content_truncation_at_hard_limit_is_clean_string(self):
        self._make_settings(tone='MINIMAL', signature_enabled=False)
        result = self._fmt(content='Y' * 5_000)
        self.assertIsInstance(result, str)
        self.assertLessEqual(len(result), 4_096)
