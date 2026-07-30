"""Public invite-acceptance view.

This is the only unauthenticated view that can create a tenant, so it is
deliberately narrow:

  * The token in the URL is the sole credential; it is looked up by hash and
    must be pending and unexpired.
  * An invalid, expired, used or revoked token gets one generic page. The view
    never reveals which of those it was, so the URL space cannot be probed to
    discover valid invites.
  * Rate limited per IP, because the endpoint is public and does real work.
  * The password is checked with Django's configured validators, not a bare
    length check.
"""

import logging

from django.conf import settings
from django.contrib.auth import password_validation
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from apps.tenants.invite_service import InviteError, accept_invite, get_usable_invite

logger = logging.getLogger("apps.tenants.invites")

RATE_LIMIT_ATTEMPTS = 10
RATE_LIMIT_WINDOW = 300          # seconds


def _client_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "") or "unknown"


def _rate_limited(request) -> bool:
    key = f"invite-accept:{_client_ip(request)}"
    count = cache.get(key, 0)
    if count >= RATE_LIMIT_ATTEMPTS:
        return True
    cache.set(key, count + 1, RATE_LIMIT_WINDOW)
    return False


def _invalid(request, message="This invitation link is not valid or has expired."):
    return render(
        request, "tenants/invite_invalid.html", {"message": message}, status=400
    )


@csrf_protect
@require_http_methods(["GET", "POST"])
def accept_invite_view(request, token):
    """Show the setup form, and provision the workspace on submit."""
    if _rate_limited(request):
        logger.warning("[Invites] Rate limited", extra={"ip": _client_ip(request)})
        return render(
            request,
            "tenants/invite_invalid.html",
            {"message": "Too many attempts. Please wait a few minutes and try again."},
            status=429,
        )

    invite = get_usable_invite(token)
    if invite is None:
        return _invalid(request)

    ctx = {
        "invite": invite,
        "token": token,
        "login_url": getattr(settings, "LOGIN_URL", "/login/"),
    }

    if request.method == "GET":
        return render(request, "tenants/invite_accept.html", ctx)

    password = request.POST.get("password") or ""
    confirm = request.POST.get("password_confirm") or ""
    owner_name = (request.POST.get("owner_name") or "").strip()

    if password != confirm:
        ctx.update({"error": "The two passwords do not match.",
                    "owner_name": owner_name})
        return render(request, "tenants/invite_accept.html", ctx, status=400)

    try:
        password_validation.validate_password(password)
    except ValidationError as exc:
        ctx.update({"error": " ".join(exc.messages), "owner_name": owner_name})
        return render(request, "tenants/invite_accept.html", ctx, status=400)

    try:
        tenant = accept_invite(token, password, owner_name=owner_name)
    except InviteError as exc:
        # Specific, actionable messages are fine here — the token was valid a
        # moment ago, so saying "already used" leaks nothing new.
        ctx.update({"error": str(exc), "owner_name": owner_name})
        return render(request, "tenants/invite_accept.html", ctx, status=400)
    except Exception:
        logger.exception("[Invites] Unexpected failure accepting invite")
        ctx.update({
            "error": "Something went wrong setting up your workspace. Please try "
                     "again, or reply to your invitation email.",
            "owner_name": owner_name,
        })
        return render(request, "tenants/invite_accept.html", ctx, status=500)

    request.session["invite_welcome_tenant"] = tenant.name
    return redirect("tenants:invite_done")


@require_http_methods(["GET"])
def invite_done_view(request):
    return render(
        request,
        "tenants/invite_done.html",
        {
            "tenant_name": request.session.pop("invite_welcome_tenant", ""),
            "login_url": getattr(settings, "LOGIN_URL", "/login/"),
        },
    )
