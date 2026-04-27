"""
EmailRenderer — wraps any email body in the tenant-branded HTML layout.

Public API:

  render_branded_email(content, context, tenant, request=None) → HTML string
      Renders the branded HTML email. Pass request when available to build
      absolute logo URLs via request.build_absolute_uri().

      Optional context keys:
        preview_text (str) — inbox snippet text (≤120 chars). When absent,
                             auto-derived from the first sentence of content.

  render_branded_email_text(content, context, tenant) → plain-text string
      Multipart-safe plain text. Strips HTML from inner content, adds a
      simple branded header and footer. Never raises.

  render_plain_text_email(content, context) → plain-text string
      Renders {{variable}} content without any layout or branding.
      Suitable for SMS or standalone plain-text messages.

Internal:
  _strip_html(html_str) — HTML → readable plain text (tested directly).
  _derive_preview_text(inner_html, max_chars) — auto-generates inbox snippet.
"""
import html as _html
import re

from django.template.loader import render_to_string

from apps.communications.utils.renderer import render_template
from .branding_adapter import BrandingAdapter

_BASE_TEMPLATE = 'emails/base.html'

# ── HTML → plain-text conversion ──────────────────────────────────────────────

# Remove entire <style> / <script> blocks (content + tags)
_BLOCK_CONTENT_RE = re.compile(
    r'<(style|script)[^>]*>.*?</\1\s*>', re.IGNORECASE | re.DOTALL
)
# HTML comments
_COMMENT_RE = re.compile(r'<!--.*?-->', re.DOTALL)
# Hyperlinks — capture href and visible text separately
_LINK_RE = re.compile(
    r'<a(?:\s[^>]*)?\shref=["\']([^"\']*)["\'][^>]*>(.*?)</a\s*>',
    re.IGNORECASE | re.DOTALL,
)
# List items → bullet points
_LI_RE = re.compile(r'<li[^>]*>', re.IGNORECASE)
# Block-level elements → newlines (opening and closing)
_BLOCK_TAG_RE = re.compile(
    r'<(?:br\s*/?|/?(?:p|div|tr|td|ul|ol|h[1-6]|blockquote|pre|hr))[^>]*>',
    re.IGNORECASE,
)
# Any remaining tag
_ANY_TAG_RE = re.compile(r'<[^>]+>')
_MULTI_NL_RE = re.compile(r'\n{3,}')
_MULTI_SP_RE = re.compile(r'[ \t]+')


def _link_to_text(m: re.Match) -> str:
    """Convert <a href="url">text</a> to 'text (url)' for plain-text email."""
    href = m.group(1).strip()
    text = _ANY_TAG_RE.sub('', m.group(2)).strip()
    # Strip mailto: prefix so it reads naturally
    if href.startswith('mailto:'):
        href = href[7:]
    # Avoid 'url (url)' duplication when text already is the URL
    if not text or text == href:
        return href
    return f'{text} ({href})'


def _strip_html(html_str: str) -> str:
    """
    Convert an HTML fragment to clean, readable plain text.

    Handles:
    - <style>/<script> blocks removed entirely (content + tags)
    - <a href="…"> links rendered as 'text (url)'
    - <li> converted to '• ' bullet points
    - Block-level tags (<p>, <br>, <div>, headings, etc.) become newlines
    - All HTML entities decoded via stdlib html.unescape (handles &amp;,
      &#160;, &#x2014;, &eacute;, etc. — not just the common handful)
    """
    text = _BLOCK_CONTENT_RE.sub('', html_str)
    text = _COMMENT_RE.sub('', text)
    text = _LINK_RE.sub(_link_to_text, text)
    text = _LI_RE.sub('\n• ', text)
    text = _BLOCK_TAG_RE.sub('\n', text)
    text = _ANY_TAG_RE.sub('', text)
    text = _html.unescape(text)
    lines = [_MULTI_SP_RE.sub(' ', line).strip() for line in text.splitlines()]
    text  = _MULTI_NL_RE.sub('\n\n', '\n'.join(lines))
    return text.strip()


def _derive_preview_text(inner_html: str, max_chars: int = 120) -> str:
    """
    Auto-generate inbox preview text from HTML content.
    Strips HTML, collapses whitespace, truncates at a word boundary.
    """
    text = ' '.join(_strip_html(inner_html).split())
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    last_space = truncated.rfind(' ')
    if last_space > max_chars // 2:
        truncated = truncated[:last_space]
    return truncated + '\u2026'  # …


# ── renderers ──────────────────────────────────────────────────────────────────

def render_branded_email(content: str, context: dict, tenant, request=None) -> str:
    """
    1. Substitute {{variable}} placeholders in content using context.
    2. Derive or accept a preview_text for the inbox snippet.
    3. Fetch tenant branding via BrandingAdapter (cached, never raises).
    4. Render emails/base.html with branding + pre-rendered inner content.
    """
    inner_html   = render_template(content, context)
    branding_ctx = BrandingAdapter.get_branding_context(tenant, request=request)

    # Caller may provide explicit preview_text; otherwise auto-derive it
    preview_text = context.get('preview_text') or _derive_preview_text(inner_html)

    template_ctx = {
        **context,
        **branding_ctx,
        'content':      inner_html,
        'preview_text': preview_text,
    }

    return render_to_string(_BASE_TEMPLATE, template_ctx)


def render_branded_email_text(content: str, context: dict, tenant) -> str:
    """
    Plain-text counterpart to render_branded_email.
    Produces a readable, branded plain-text email for multipart MIME messages.
    """
    inner_text   = _strip_html(render_template(content, context))
    branding_ctx = BrandingAdapter.get_branding_context(tenant)
    brand_name   = branding_ctx.get('brand_name', '')

    separator = '=' * max(len(brand_name), 20)
    lines = []

    if brand_name:
        lines += [brand_name, separator, '']

    lines.append(inner_text)
    lines.append('')
    lines.append('-' * 40)

    if brand_name:
        lines.append(brand_name)

    footer_phone = context.get('footer_phone', '')
    footer_email = context.get('footer_email', '')
    if footer_phone:
        lines.append(footer_phone)
    if footer_email:
        lines.append(footer_email)

    return '\n'.join(lines)


def render_plain_text_email(content: str, context: dict) -> str:
    """Plain-text fallback — no HTML, no branding, just substituted content."""
    return render_template(content, context)
