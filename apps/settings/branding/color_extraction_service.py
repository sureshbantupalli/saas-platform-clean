"""
ColorExtractionService — extract a production-grade palette from a logo image.

Responsibilities:
  - Dominant color extraction via Pillow quantise
  - WCAG 2.1 contrast validation + auto-adjustment
  - Harmonious secondary via HSL hue shifting
  - MD5-based result caching (10 min, per image hash)
  - SVG detection with graceful fallback
  - Near-white / near-black / low-saturation filtering

No DB access. Never raises — always returns a safe result dict.
"""

import colorsys
import hashlib
import io

from django.core.cache import cache
from PIL import Image

# ── tunables ──────────────────────────────────────────────────────────────────

_MAX_DIM        = 200     # px — resize before quantise
_MIN_DIM        = 50      # px — below this → low_confidence
_N_COLORS       = 12      # palette slots
_WHITE_THRESH   = 228     # per-channel: above → "too light"
_BLACK_THRESH   = 28      # per-channel: below → "too dark"
_GRAY_THRESH    = 28      # max–min chanel below → low saturation
_CONTRAST_MIN   = 3.0     # WCAG AA large text minimum
_CACHE_TTL      = 600     # seconds — palette cache (per image MD5)

SAFE_DEFAULTS = {
    'primary_color':   '#0d6efd',
    'secondary_color': '#6c757d',
    'low_confidence':  False,
    'adjusted':        False,
    'message':         '',
}


# ── low-level colour helpers ──────────────────────────────────────────────────

def _rgb_to_hex(rgb: tuple) -> str:
    return '#{:02x}{:02x}{:02x}'.format(int(rgb[0]), int(rgb[1]), int(rgb[2]))


def _hex_to_rgb(h: str) -> tuple:
    h = h.lstrip('#')
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _to_linear(c: float) -> float:
    """sRGB channel → linear (IEC 61966-2-1)."""
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _relative_luminance(rgb: tuple) -> float:
    """WCAG 2.1 relative luminance."""
    r, g, b = (_to_linear(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_ratio(rgb1: tuple, rgb2: tuple) -> float:
    """WCAG 2.1 contrast ratio between two colours."""
    L1 = _relative_luminance(rgb1)
    L2 = _relative_luminance(rgb2)
    light, dark = max(L1, L2), min(L1, L2)
    return (light + 0.05) / (dark + 0.05)


def _best_text_color(bg_rgb: tuple) -> tuple:
    """Return white or black — whichever has higher contrast with bg_rgb."""
    cw = _contrast_ratio(bg_rgb, (255, 255, 255))
    cb = _contrast_ratio(bg_rgb, (0, 0, 0))
    return (255, 255, 255) if cw >= cb else (0, 0, 0)


def _adjust_for_contrast(rgb: tuple, target_ratio: float = _CONTRAST_MIN) -> tuple:
    """
    Lighten or darken rgb until it meets target_ratio against either
    white or black text. Returns the adjusted rgb and whether we changed it.
    """
    white, black = (255, 255, 255), (0, 0, 0)
    if max(_contrast_ratio(rgb, white), _contrast_ratio(rgb, black)) >= target_ratio:
        return rgb, False

    h, l, s = colorsys.rgb_to_hls(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255)
    # Try darkening first (usually better for brand colours)
    for delta in range(1, 16):
        for sign in (-1, 1):
            nl = max(0.0, min(1.0, l + sign * delta * 0.04))
            nr, ng, nb = colorsys.hls_to_rgb(h, nl, s)
            adj = (round(nr * 255), round(ng * 255), round(nb * 255))
            if max(_contrast_ratio(adj, white), _contrast_ratio(adj, black)) >= target_ratio:
                return adj, True
    return rgb, False   # give up — return original


def _is_near_white(rgb: tuple) -> bool:
    return all(c >= _WHITE_THRESH for c in rgb)


def _is_near_black(rgb: tuple) -> bool:
    return all(c <= _BLACK_THRESH for c in rgb)


def _is_usable(rgb: tuple) -> bool:
    return not (_is_near_white(rgb) or _is_near_black(rgb))


def _saturation(rgb: tuple) -> int:
    return max(rgb) - min(rgb)


# ── harmonious secondary colour ───────────────────────────────────────────────

def _harmonious_secondary(primary_rgb: tuple, candidates: list) -> tuple:
    """
    Prefer a candidate from the extracted palette that is:
      1) Not too close in hue to primary  (avoid clashing)
      2) Different enough in lightness

    If no good candidate, synthesise a complementary (180° hue shift)
    at a lightness that guarantees readability.
    """
    ph, pl, ps = colorsys.rgb_to_hls(
        primary_rgb[0] / 255, primary_rgb[1] / 255, primary_rgb[2] / 255
    )

    best, best_score = None, -1.0
    for rgb in candidates:
        if not _is_usable(rgb):
            continue
        h, l, s = colorsys.rgb_to_hls(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255)
        # Angular distance on hue wheel (0–0.5)
        hue_diff = min(abs(h - ph), 1.0 - abs(h - ph))
        lum_diff  = abs(l - pl)
        # Reward hue variety and lightness contrast; penalise near-gray
        score = hue_diff * 2 + lum_diff - (0.5 if s < 0.1 else 0)
        if score > best_score:
            best_score, best = score, rgb

    if best is not None and best_score > 0.05:
        return best

    # Synthesise: complementary hue, contrasting lightness, moderate saturation
    comp_h  = (ph + 0.5) % 1.0
    comp_l  = 0.35 if pl > 0.5 else 0.60
    comp_s  = max(ps, 0.40)
    r, g, b = colorsys.hls_to_rgb(comp_h, comp_l, comp_s)
    synth   = (round(r * 255), round(g * 255), round(b * 255))
    if not _is_usable(synth):
        synth = (90, 103, 115)  # safe slate-gray fallback
    return synth


# ── SVG detection ─────────────────────────────────────────────────────────────

def _is_svg(file_obj) -> bool:
    try:
        if hasattr(file_obj, 'seek'):
            file_obj.seek(0)
        header = file_obj.read(256)
        if hasattr(file_obj, 'seek'):
            file_obj.seek(0)
        if isinstance(header, bytes):
            header = header.decode('utf-8', errors='ignore')
        return '<svg' in header.lower() or '<?xml' in header.lower()
    except Exception:
        return False


def _check_svg_name(file_obj) -> bool:
    name = getattr(file_obj, 'name', '') or ''
    return name.lower().endswith('.svg')


# ── MD5 palette cache ─────────────────────────────────────────────────────────

def _file_md5(file_obj) -> str:
    if hasattr(file_obj, 'seek'):
        file_obj.seek(0)
    h = hashlib.md5()
    while True:
        chunk = file_obj.read(8192)
        if not chunk:
            break
        h.update(chunk)
    if hasattr(file_obj, 'seek'):
        file_obj.seek(0)
    return h.hexdigest()


def _palette_cache_key(md5: str) -> str:
    return f'palette:img:{md5}'


# ── main service ──────────────────────────────────────────────────────────────

class ColorExtractionService:

    @staticmethod
    def extract_from_file(file_obj) -> dict:
        """
        Entry point. Accepts any file-like object (InMemoryUploadedFile, BytesIO).
        Returns {primary_color, secondary_color, low_confidence, adjusted, message}.
        Never raises.
        """
        try:
            # ── SVG gate ─────────────────────────────────────────────
            if _check_svg_name(file_obj) or _is_svg(file_obj):
                return {
                    **dict(SAFE_DEFAULTS),
                    'low_confidence': True,
                    'message': 'SVG color detection may be limited. Suggested defaults applied.',
                }

            # ── MD5 cache ────────────────────────────────────────────
            md5 = _file_md5(file_obj)
            key = _palette_cache_key(md5)
            cached = cache.get(key)
            if cached is not None:
                return cached

            image  = Image.open(file_obj)
            result = ColorExtractionService._extract(image)

            cache.set(key, result, _CACHE_TTL)
            return result

        except Exception:
            return dict(SAFE_DEFAULTS)

    @staticmethod
    def _extract(image: Image.Image) -> dict:
        w, h = image.size

        # ── size gate ─────────────────────────────────────────────────
        if w < _MIN_DIM or h < _MIN_DIM:
            return {**dict(SAFE_DEFAULTS), 'low_confidence': True}

        # ── normalise to RGB ──────────────────────────────────────────
        if image.mode in ('RGBA', 'LA'):
            bg = Image.new('RGB', image.size, (255, 255, 255))
            bg.paste(image, mask=image.split()[-1])
            image = bg
        elif image.mode == 'P' and 'transparency' in image.info:
            image = image.convert('RGBA')
            bg = Image.new('RGB', image.size, (255, 255, 255))
            bg.paste(image, mask=image.split()[-1])
            image = bg
        else:
            image = image.convert('RGB')

        # ── resize for speed ──────────────────────────────────────────
        image = image.copy()
        image.thumbnail((_MAX_DIM, _MAX_DIM), Image.LANCZOS)

        # ── quantise ──────────────────────────────────────────────────
        quantized = image.quantize(colors=_N_COLORS)
        palette   = quantized.getpalette()
        histogram = quantized.histogram()
        n_actual  = min(len(palette) // 3, _N_COLORS)

        color_counts = []
        for i in range(n_actual):
            r, g, b = palette[i * 3], palette[i * 3 + 1], palette[i * 3 + 2]
            color_counts.append((histogram[i], (r, g, b)))
        color_counts.sort(reverse=True)

        # ── filter usable ─────────────────────────────────────────────
        usable = [(cnt, rgb) for cnt, rgb in color_counts if _is_usable(rgb)]
        if not usable:
            return {**dict(SAFE_DEFAULTS), 'low_confidence': True}

        primary_raw = usable[0][1]

        # ── WCAG contrast adjustment ──────────────────────────────────
        primary_adj, was_adjusted = _adjust_for_contrast(primary_raw)

        # ── harmonious secondary ──────────────────────────────────────
        candidates = [rgb for _, rgb in usable[1:]]
        secondary_raw = _harmonious_secondary(primary_adj, candidates)
        secondary_adj, _ = _adjust_for_contrast(secondary_raw)

        # ── confidence ────────────────────────────────────────────────
        low_confidence = _saturation(primary_raw) < _GRAY_THRESH

        return {
            'primary_color':   _rgb_to_hex(primary_adj),
            'secondary_color': _rgb_to_hex(secondary_adj),
            'low_confidence':  low_confidence,
            'adjusted':        was_adjusted,
            'message':         'Primary color was adjusted slightly for accessibility.' if was_adjusted else '',
        }
