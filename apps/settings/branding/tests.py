import io
import json

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from apps.authority.models import Role as AuthorityRole
from apps.core.models import Branch, Tenant

from .color_extraction_service import ColorExtractionService
from .models import TenantBranding
from .services import DEFAULTS, BrandingService, _darken, _hex_to_rgb, _hex_to_rgb_str


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


class BrandingServiceTest(TestCase):

    def setUp(self):
        _, self.tenant = make_tenant_user('SvcTest')
        cache.clear()

    def test_get_branding_returns_none_when_no_record(self):
        self.assertIsNone(BrandingService.get_branding(self.tenant))

    def test_get_branding_returns_record_when_exists(self):
        TenantBranding.objects.create(
            tenant=self.tenant,
            primary_color='#ff0000',
        )
        b = BrandingService.get_branding(self.tenant)
        self.assertIsNotNone(b)
        self.assertEqual(b.primary_color, '#ff0000')

    def test_is_enabled_false_by_default(self):
        TenantBranding.objects.create(tenant=self.tenant)
        self.assertFalse(BrandingService.is_enabled(self.tenant))

    def test_is_enabled_true_when_whitelabel_on(self):
        TenantBranding.objects.create(tenant=self.tenant, whitelabel_enabled=True)
        cache.clear()
        self.assertTrue(BrandingService.is_enabled(self.tenant))

    def test_get_css_vars_returns_defaults_when_no_branding(self):
        vars_ = BrandingService.get_css_vars(self.tenant)
        self.assertEqual(vars_['--primary-color'],   DEFAULTS['primary_color'])
        self.assertEqual(vars_['--secondary-color'], DEFAULTS['secondary_color'])

    def test_get_css_vars_returns_custom_when_whitelabel_enabled(self):
        TenantBranding.objects.create(
            tenant=self.tenant,
            primary_color='#aabbcc',
            secondary_color='#112233',
            whitelabel_enabled=True,
        )
        cache.clear()
        vars_ = BrandingService.get_css_vars(self.tenant)
        self.assertEqual(vars_['--primary-color'],   '#aabbcc')
        self.assertEqual(vars_['--secondary-color'], '#112233')

    def test_get_css_vars_falls_back_when_whitelabel_disabled(self):
        TenantBranding.objects.create(
            tenant=self.tenant,
            primary_color='#aabbcc',
            whitelabel_enabled=False,
        )
        cache.clear()
        vars_ = BrandingService.get_css_vars(self.tenant)
        self.assertEqual(vars_['--primary-color'], DEFAULTS['primary_color'])

    def test_save_branding_persists_and_invalidates_cache(self):
        BrandingService.get_branding(self.tenant)  # populate cache
        BrandingService.save_branding(self.tenant, {'primary_color': '#123456', 'secondary_color': '#654321', 'login_title': 'Hi', 'custom_css': ''})
        b = BrandingService.get_branding(self.tenant)
        self.assertEqual(b.primary_color, '#123456')
        self.assertEqual(b.login_title, 'Hi')

    def test_reset_branding_restores_defaults(self):
        TenantBranding.objects.create(
            tenant=self.tenant,
            primary_color='#ff0000',
            login_title='Custom',
        )
        cache.clear()
        BrandingService.reset_branding(self.tenant)
        b = TenantBranding.objects.get(tenant=self.tenant)
        self.assertEqual(b.primary_color, DEFAULTS['primary_color'])
        self.assertEqual(b.login_title, '')

    def test_invalidate_clears_cache(self):
        BrandingService.get_branding(self.tenant)
        from .services import _cache_key
        self.assertIsNone(cache.get(_cache_key(self.tenant.pk)) if False else
                          cache.get(_cache_key(self.tenant.pk)))  # warm
        BrandingService.invalidate(self.tenant)
        sentinel = object()
        self.assertIs(cache.get(_cache_key(self.tenant.pk), sentinel), sentinel)


class BrandingModelValidationTest(TestCase):

    def setUp(self):
        _, self.tenant = make_tenant_user('ValTest')

    def test_invalid_hex_raises(self):
        from django.core.exceptions import ValidationError
        b = TenantBranding(tenant=self.tenant, primary_color='red')
        with self.assertRaises(ValidationError):
            b.full_clean()

    def test_valid_hex_passes(self):
        b = TenantBranding(tenant=self.tenant, primary_color='#1A2B3C')
        b.full_clean()  # should not raise


class BrandingTenantIsolationTest(TestCase):

    def setUp(self):
        cache.clear()
        _, self.tenant_a = make_tenant_user('BrandA')
        _, self.tenant_b = make_tenant_user('BrandB')

    def test_branding_of_a_does_not_affect_b(self):
        TenantBranding.objects.create(
            tenant=self.tenant_a,
            primary_color='#ff0000',
            whitelabel_enabled=True,
        )
        vars_a = BrandingService.get_css_vars(self.tenant_a)
        vars_b = BrandingService.get_css_vars(self.tenant_b)
        self.assertEqual(vars_a['--primary-color'], '#ff0000')
        self.assertEqual(vars_b['--primary-color'], DEFAULTS['primary_color'])


@override_settings(MEDIA_ROOT='/tmp/test_media/')
class BrandingPageTest(TestCase):

    def setUp(self):
        self.user, self.tenant = make_tenant_user('PageBranding')
        self.client = Client()
        self.client.login(email='user@pagebranding.com', password='testpass')
        cache.clear()

    def test_branding_page_loads(self):
        resp = self.client.get(reverse('settings:branding:branding'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Branding')

    def test_feature_locked_notice_shown_without_whitelabel(self):
        resp = self.client.get(reverse('settings:branding:branding'))
        self.assertContains(resp, 'Upgrade your plan')

    def test_no_locked_notice_when_whitelabel_enabled(self):
        TenantBranding.objects.create(
            tenant=self.tenant,
            whitelabel_enabled=True,
        )
        cache.clear()
        resp = self.client.get(reverse('settings:branding:branding'))
        self.assertNotContains(resp, 'Upgrade your plan')

    def test_post_rejected_when_feature_locked(self):
        resp = self.client.post(reverse('settings:branding:branding'), {
            'primary_color': '#ff0000',
            'secondary_color': '#00ff00',
        })
        self.assertRedirects(resp, reverse('settings:branding:branding'))
        self.assertFalse(TenantBranding.objects.filter(tenant=self.tenant).exists())

    def test_post_saves_when_whitelabel_enabled(self):
        TenantBranding.objects.create(tenant=self.tenant, whitelabel_enabled=True)
        cache.clear()
        resp = self.client.post(reverse('settings:branding:branding'), {
            'primary_color':   '#aabbcc',
            'secondary_color': '#112233',
            'login_title':     'Gym Pro',
            'custom_css':      '',
        })
        self.assertRedirects(resp, reverse('settings:branding:branding'))
        b = TenantBranding.objects.get(tenant=self.tenant)
        self.assertEqual(b.primary_color, '#aabbcc')
        self.assertEqual(b.login_title, 'Gym Pro')

    def test_post_invalid_hex_shows_error(self):
        TenantBranding.objects.create(tenant=self.tenant, whitelabel_enabled=True)
        cache.clear()
        resp = self.client.post(reverse('settings:branding:branding'), {
            'primary_color':   'not-a-hex',
            'secondary_color': '#112233',
            'login_title':     '',
            'custom_css':      '',
        }, follow=True)
        self.assertContains(resp, 'valid hex')

    def test_unauthenticated_redirects(self):
        client = Client()
        resp = client.get(reverse('settings:branding:branding'))
        self.assertIn(resp.status_code, [301, 302])

    def test_platform_admin_gets_403(self):
        admin = make_platform_admin()
        client = Client()
        client.login(email='platform@admin.com', password='testpass')
        resp = client.get(reverse('settings:branding:branding'))
        self.assertEqual(resp.status_code, 403)

    def test_live_preview_elements_in_template(self):
        resp = self.client.get(reverse('settings:branding:branding'))
        self.assertContains(resp, 'pv-btn-primary')
        self.assertContains(resp, 'Live Preview')

    def test_generate_colors_button_present(self):
        resp = self.client.get(reverse('settings:branding:branding'))
        self.assertContains(resp, 'Generate Colors')

    def test_api_url_embedded_in_template(self):
        resp = self.client.get(reverse('settings:branding:branding'))
        self.assertContains(resp, 'generate-palette')

    def test_unsaved_banner_element_present(self):
        resp = self.client.get(reverse('settings:branding:branding'))
        self.assertContains(resp, 'unsavedBanner')

    def test_reset_colors_button_present(self):
        resp = self.client.get(reverse('settings:branding:branding'))
        self.assertContains(resp, 'btnResetColors')

    def test_preview_mode_toggle_present(self):
        resp = self.client.get(reverse('settings:branding:branding'))
        self.assertContains(resp, 'previewModeToggle')

    def test_contrast_info_elements_present(self):
        resp = self.client.get(reverse('settings:branding:branding'))
        self.assertContains(resp, 'primaryContrastInfo')


# ── ColorExtractionService ──────────────────────────────────────────────────

def _make_image_file(color=(255, 0, 0), size=(100, 100), fmt='PNG') -> io.BytesIO:
    img = Image.new('RGB', size, color)
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    buf.seek(0)
    return buf


class ColorExtractionServiceTest(TestCase):

    def test_returns_valid_hex_colors(self):
        result = ColorExtractionService.extract_from_file(_make_image_file((200, 50, 50)))
        self.assertRegex(result['primary_color'],   r'^#[0-9a-f]{6}$')
        self.assertRegex(result['secondary_color'], r'^#[0-9a-f]{6}$')

    def test_low_confidence_false_for_saturated_color(self):
        result = ColorExtractionService.extract_from_file(_make_image_file((200, 50, 50)))
        self.assertFalse(result['low_confidence'])

    def test_low_confidence_true_for_tiny_image(self):
        result = ColorExtractionService.extract_from_file(_make_image_file(size=(30, 30)))
        self.assertTrue(result['low_confidence'])

    def test_near_gray_image_returns_low_confidence(self):
        # Near-gray solid color → low saturation → low_confidence
        result = ColorExtractionService.extract_from_file(_make_image_file((140, 140, 140)))
        self.assertTrue(result['low_confidence'])

    def test_fallback_on_corrupt_file(self):
        bad = io.BytesIO(b'not-an-image')
        result = ColorExtractionService.extract_from_file(bad)
        self.assertIn('primary_color',   result)
        self.assertIn('secondary_color', result)
        self.assertIn('low_confidence',  result)

    def test_rgba_image_handled(self):
        img = Image.new('RGBA', (100, 100), (200, 50, 50, 255))
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        result = ColorExtractionService.extract_from_file(buf)
        self.assertRegex(result['primary_color'], r'^#[0-9a-f]{6}$')

    def test_keys_always_present(self):
        result = ColorExtractionService.extract_from_file(_make_image_file())
        self.assertSetEqual(set(result.keys()),
                            {'primary_color', 'secondary_color', 'low_confidence', 'adjusted', 'message'})

    def test_adjusted_field_present(self):
        result = ColorExtractionService.extract_from_file(_make_image_file((200, 50, 50)))
        self.assertIn('adjusted', result)
        self.assertIsInstance(result['adjusted'], bool)

    def test_message_field_is_string(self):
        result = ColorExtractionService.extract_from_file(_make_image_file((200, 50, 50)))
        self.assertIsInstance(result['message'], str)

    def test_svg_file_returns_low_confidence(self):
        svg_content = b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"></svg>'
        svg_file = io.BytesIO(svg_content)
        svg_file.name = 'logo.svg'
        result = ColorExtractionService.extract_from_file(svg_file)
        self.assertTrue(result['low_confidence'])
        self.assertIn('SVG', result['message'])

    def test_svg_by_content_detected_without_extension(self):
        svg_content = b'<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>'
        svg_file = io.BytesIO(svg_content)
        svg_file.name = 'logo.png'  # wrong extension, but SVG content
        result = ColorExtractionService.extract_from_file(svg_file)
        self.assertTrue(result['low_confidence'])

    def test_md5_cache_hit_returns_same_result(self):
        cache.clear()
        buf1 = _make_image_file((0, 128, 255))
        result1 = ColorExtractionService.extract_from_file(buf1)

        buf2 = _make_image_file((0, 128, 255))  # identical image → same MD5
        result2 = ColorExtractionService.extract_from_file(buf2)

        self.assertEqual(result1['primary_color'], result2['primary_color'])

    def test_different_images_produce_different_cache_keys(self):
        cache.clear()
        result_red  = ColorExtractionService.extract_from_file(_make_image_file((200, 0, 0)))
        result_blue = ColorExtractionService.extract_from_file(_make_image_file((0, 0, 200)))
        # Different images — at least one colour should differ
        differ = (result_red['primary_color'] != result_blue['primary_color']
                  or result_red['secondary_color'] != result_blue['secondary_color'])
        self.assertTrue(differ)

    def test_secondary_color_is_valid_hex(self):
        result = ColorExtractionService.extract_from_file(_make_image_file((50, 200, 100)))
        self.assertRegex(result['secondary_color'], r'^#[0-9a-f]{6}$')


# ── BrandingService.generate_palette_from_logo ──────────────────────────────

class GeneratePaletteServiceTest(TestCase):

    def test_generate_palette_delegates_to_extraction(self):
        buf = _make_image_file((0, 100, 200))
        result = BrandingService.generate_palette_from_logo(buf)
        self.assertIn('primary_color', result)
        self.assertFalse(result.get('low_confidence'))  # saturated blue

    def test_generate_palette_returns_no_db_write(self):
        _, tenant = make_tenant_user('PaletteTest')
        buf = _make_image_file((0, 100, 200))
        BrandingService.generate_palette_from_logo(buf)
        self.assertFalse(TenantBranding.objects.filter(tenant=tenant).exists())


# ── CSS helpers ──────────────────────────────────────────────────────────────

class CssHelpersTest(TestCase):

    def test_hex_to_rgb(self):
        self.assertEqual(_hex_to_rgb('#0d6efd'), (13, 110, 253))

    def test_hex_to_rgb_str(self):
        self.assertEqual(_hex_to_rgb_str('#0d6efd'), '13, 110, 253')

    def test_darken(self):
        darkened = _darken('#ffffff', factor=0.5)
        r, g, b = _hex_to_rgb(darkened)
        self.assertLess(r, 255)

    def test_darken_does_not_go_negative(self):
        darkened = _darken('#000000', factor=0.99)
        self.assertEqual(darkened, '#000000')


# ── Updated get_css_vars ─────────────────────────────────────────────────────

class CssVarsTest(TestCase):

    def setUp(self):
        _, self.tenant = make_tenant_user('CssVarsTest')
        cache.clear()

    def test_css_vars_include_all_keys(self):
        vars_ = BrandingService.get_css_vars(self.tenant)
        expected = {'--primary-color', '--primary-rgb', '--primary-hover',
                    '--secondary-color', '--secondary-hover'}
        self.assertEqual(set(vars_.keys()), expected)

    def test_primary_rgb_format(self):
        vars_ = BrandingService.get_css_vars(self.tenant)
        parts = vars_['--primary-rgb'].split(',')
        self.assertEqual(len(parts), 3)
        for p in parts:
            self.assertTrue(0 <= int(p.strip()) <= 255)

    def test_hover_is_darker_than_base(self):
        vars_ = BrandingService.get_css_vars(self.tenant)
        base  = sum(_hex_to_rgb(vars_['--primary-color']))
        hover = sum(_hex_to_rgb(vars_['--primary-hover']))
        self.assertLess(hover, base)


# ── Palette API endpoint ─────────────────────────────────────────────────────

def _make_upload(color=(200, 50, 50), size=(100, 100)):
    img = Image.new('RGB', size, color)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return SimpleUploadedFile('logo.png', buf.read(), content_type='image/png')


class GeneratePaletteAPITest(TestCase):

    def setUp(self):
        self.user, self.tenant = make_tenant_user('APITest')
        self.client = Client()
        self.client.login(email='user@apitest.com', password='testpass')

    def test_returns_200_with_palette(self):
        resp = self.client.post(
            reverse('branding_api:generate_palette'),
            {'logo': _make_upload()},
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertIn('primary_color',   data)
        self.assertIn('secondary_color', data)
        self.assertIn('low_confidence',  data)

    def test_no_file_returns_400(self):
        resp = self.client.post(reverse('branding_api:generate_palette'), {})
        self.assertEqual(resp.status_code, 400)

    def test_oversized_file_returns_400(self):
        big = SimpleUploadedFile(
            'big.png',
            b'x' * (2 * 1024 * 1024 + 1),
            content_type='image/png',
        )
        resp = self.client.post(
            reverse('branding_api:generate_palette'),
            {'logo': big},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('too large', json.loads(resp.content)['error'].lower())

    def test_unsupported_format_returns_400(self):
        bad = SimpleUploadedFile('file.bmp', b'bmpdata', content_type='image/bmp')
        resp = self.client.post(
            reverse('branding_api:generate_palette'),
            {'logo': bad},
        )
        self.assertEqual(resp.status_code, 400)

    def test_get_not_allowed(self):
        resp = self.client.get(reverse('branding_api:generate_palette'))
        self.assertEqual(resp.status_code, 405)

    def test_unauthenticated_returns_401(self):
        resp = Client().post(
            reverse('branding_api:generate_palette'),
            {'logo': _make_upload()},
        )
        self.assertEqual(resp.status_code, 401)

    def test_platform_admin_returns_403(self):
        admin = make_platform_admin()
        c = Client()
        c.login(email='platform@admin.com', password='testpass')
        resp = c.post(
            reverse('branding_api:generate_palette'),
            {'logo': _make_upload()},
        )
        self.assertEqual(resp.status_code, 403)

    def test_does_not_persist_branding(self):
        self.client.post(
            reverse('branding_api:generate_palette'),
            {'logo': _make_upload()},
        )
        self.assertFalse(TenantBranding.objects.filter(tenant=self.tenant).exists())

    def test_svg_upload_accepted_returns_low_confidence(self):
        svg_bytes = b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"></svg>'
        svg_file = SimpleUploadedFile('logo.svg', svg_bytes, content_type='image/svg+xml')
        resp = self.client.post(
            reverse('branding_api:generate_palette'),
            {'logo': svg_file},
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertTrue(data['low_confidence'])

    def test_response_includes_adjusted_field(self):
        resp = self.client.post(
            reverse('branding_api:generate_palette'),
            {'logo': _make_upload()},
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertIn('adjusted', data)
        self.assertIn('message', data)
