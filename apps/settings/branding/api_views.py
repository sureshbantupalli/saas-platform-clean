from django.http import JsonResponse
from django.views.decorators.http import require_POST

from .services import BrandingService

_RASTER_TYPES  = {'image/png', 'image/jpeg', 'image/jpg', 'image/webp'}
_SVG_TYPES     = {'image/svg+xml', 'image/svg'}
_ALLOWED_TYPES = _RASTER_TYPES | _SVG_TYPES
_MAX_SIZE      = 2 * 1024 * 1024  # 2 MB


def _error(msg: str, status: int = 400) -> JsonResponse:
    return JsonResponse({'error': msg}, status=status)


@require_POST
def generate_palette(request):
    if not request.user.is_authenticated:
        return _error('Authentication required.', 401)

    if not getattr(request.user, 'tenant', None):
        return _error('Platform admins cannot use this endpoint.', 403)

    logo = request.FILES.get('logo')
    if not logo:
        return _error('No logo file uploaded.')

    if logo.size > _MAX_SIZE:
        return _error('File too large. Maximum allowed size is 2 MB.')

    content_type = (getattr(logo, 'content_type', '') or '').lower()
    name         = (logo.name or '').lower()
    type_ok  = content_type in _ALLOWED_TYPES
    name_ok  = any(name.endswith(ext) for ext in ('.png', '.jpg', '.jpeg', '.webp', '.svg'))

    if not (type_ok or name_ok):
        return _error('Unsupported file type. Please upload PNG, JPEG, WebP, or SVG.')

    palette = BrandingService.generate_palette_from_logo(logo)
    return JsonResponse(palette)
