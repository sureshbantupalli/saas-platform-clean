"""WhatsApp adapter — Meta WhatsApp Cloud API (direct, no reseller).

Replaces the previous mock, which only wrote the message to the log.

Design constraints this file has to respect:

* ``communication_service._get_adapter()`` instantiates **every** adapter on
  each send, so ``__init__`` must never raise. A missing access token must not
  take SMS and EMAIL down with it.
* The caller wraps ``send()`` in try/except and builds a FAILED
  CommunicationLog from the exception, which ``retry_failed_messages`` later
  picks up. A delivery failure therefore MUST raise — returning quietly would
  record an undelivered message as SENT.
* When WhatsApp is not configured the adapter falls back to the old logging
  behaviour, so local development and the test-suite work without credentials.

The 24-hour window — the WhatsApp equivalent of DLT
---------------------------------------------------
Meta only permits free-form text when the member has messaged the business
within the last 24 hours. Everything this platform sends (class reminders,
payment receipts, renewal nudges) is business-initiated and therefore lands
*outside* that window, where Meta rejects free-form text with error 131047.

So business-initiated sends require a **pre-approved template**. Set
``WHATSAPP_TEMPLATE_NAME`` to a template whose body is a single ``{{1}}``
variable — the same one-variable shape the MSG91 DLT template uses — and the
rendered message is injected into it. With no template name configured the
adapter sends free-form text, which is correct only for replies inside the
24-hour window and for testing.

Credentials are resolved PER TENANT via TenantMessagingConfig, because a
WhatsApp Business Account binds to the studio's own phone number and verified
business name — a second tenant sending under the first tenant's WABA would
appear to members as the wrong studio. Global env vars remain as a fallback
for local development and the single-tenant deployment only.
"""

import logging
import os

import requests
from django.conf import settings

from .base import BaseAdapter
from .phone import PhoneNumberError
from .phone import normalise_msisdn as _normalise_msisdn

logger = logging.getLogger("apps.communications.whatsapp")

DEFAULT_API_VERSION = "v21.0"
DEFAULT_TIMEOUT = 10  # seconds — must not hang the request thread
DEFAULT_TEMPLATE_LANG = "en"

# Meta's documented ceilings. Exceeding either is a hard rejection.
MAX_TEXT_BODY = 4096
MAX_TEMPLATE_PARAM = 1024


class WhatsAppDeliveryError(Exception):
    """Raised when Meta does not accept the message for delivery."""


def _setting(name: str, default: str = "") -> str:
    """Read config from Django settings, falling back to the environment."""
    value = getattr(settings, name, None)
    if value in (None, ""):
        value = os.environ.get(name, default)
    return (value or "").strip()


class WhatsAppAdapter(BaseAdapter):
    """Sends WhatsApp messages via Meta's Cloud API, or logs when unconfigured."""

    def __init__(self, tenant=None):
        """Credentials come from the tenant's own WhatsApp Business Account.

        The WABA binds to the studio's phone number and verified business name,
        so a second tenant sending under global env credentials would appear to
        members as the first studio. The env fallback is kept for local
        development and the single-tenant deployment; the config service logs
        loudly when it is used while several tenants exist.

        Never raises — see module docstring.
        """
        from apps.communications.models import MessagingProvider
        from apps.communications.services.messaging_config_service import (
            get_messaging_config, warn_if_env_fallback_is_ambiguous,
        )

        self.tenant = tenant
        provider = MessagingProvider.WHATSAPP_CLOUD
        config = get_messaging_config(tenant, provider)
        warn_if_env_fallback_is_ambiguous(tenant, provider, config)

        self.phone_number_id = getattr(config, "sender_id", "") or ""
        self.access_token = getattr(config, "api_key", "") or ""
        self.template_name = getattr(config, "template_id", "") or ""
        self.template_lang = (
            getattr(config, "template_lang", "") or DEFAULT_TEMPLATE_LANG
        )
        self.api_version = _setting("WHATSAPP_API_VERSION") or DEFAULT_API_VERSION
        try:
            self.timeout = int(_setting("WHATSAPP_TIMEOUT") or DEFAULT_TIMEOUT)
        except ValueError:
            self.timeout = DEFAULT_TIMEOUT

    @property
    def is_configured(self) -> bool:
        return bool(self.phone_number_id and self.access_token)

    @property
    def endpoint(self) -> str:
        return (
            f"https://graph.facebook.com/{self.api_version}"
            f"/{self.phone_number_id}/messages"
        )

    def send(self, to: str, message: str, subject: str = "", text: str = "") -> None:
        if not self.is_configured:
            # Same behaviour as the old mock, so dev and tests are unaffected.
            logger.info(
                "[WhatsApp:unconfigured] to=%s | %s", to, (message or "")[:160]
            )
            return

        try:
            recipient = _normalise_msisdn(to)
        except PhoneNumberError as exc:
            raise WhatsAppDeliveryError(str(exc)) from exc

        body = (message or "").strip()
        if not body:
            raise WhatsAppDeliveryError("Refusing to send an empty WhatsApp message.")

        payload = self._build_payload(recipient, body)

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(
                self.endpoint, json=payload, headers=headers, timeout=self.timeout
            )
        except requests.Timeout as exc:
            raise WhatsAppDeliveryError(
                f"Meta WhatsApp API timed out after {self.timeout}s"
            ) from exc
        except requests.RequestException as exc:
            raise WhatsAppDeliveryError(
                f"Meta WhatsApp API request failed: {exc}"
            ) from exc

        self._raise_for_failure(response)

        # Deliberately does not log the message body (PII) or the access token.
        logger.info(
            "[WhatsApp] accepted by Meta",
            extra={"recipient": recipient, "template": self.template_name or "(text)"},
        )

    def _build_payload(self, recipient: str, body: str) -> dict:
        base = {"messaging_product": "whatsapp", "to": recipient}

        if not self.template_name:
            # Free-form: valid only inside the 24-hour service window.
            return {
                **base,
                "type": "text",
                "text": {"body": self._clamp(body, MAX_TEXT_BODY)},
            }

        return {
            **base,
            "type": "template",
            "template": {
                "name": self.template_name,
                "language": {"code": self.template_lang},
                "components": [
                    {
                        "type": "body",
                        "parameters": [
                            {
                                "type": "text",
                                "text": self._clamp(body, MAX_TEMPLATE_PARAM),
                            }
                        ],
                    }
                ],
            },
        }

    @staticmethod
    def _clamp(body: str, limit: int) -> str:
        """Truncate rather than fail when Meta's length ceiling is exceeded.

        A truncated reminder still reaches the member; a rejected one does not.
        The warning makes the truncation discoverable instead of silent.
        """
        if len(body) <= limit:
            return body
        logger.warning(
            "WhatsApp message truncated to fit Meta's limit",
            extra={"original_length": len(body), "limit": limit},
        )
        return body[: limit - 1] + "…"

    @staticmethod
    def _raise_for_failure(response) -> None:
        """Meta signals rejection with an ``error`` object.

        It usually arrives with a 4xx status, but the body is checked
        regardless of status code: trusting the status alone would record an
        undelivered message as SENT.
        """
        try:
            data = response.json()
        except ValueError:
            raise WhatsAppDeliveryError(
                f"Meta returned non-JSON response "
                f"(HTTP {response.status_code}): {response.text[:200]}"
            )

        if isinstance(data, dict) and data.get("error"):
            error = data["error"]
            raise WhatsAppDeliveryError(
                f"Meta rejected the message "
                f"[code={error.get('code')}]: {error.get('message')}"
            )

        if response.status_code >= 400:
            raise WhatsAppDeliveryError(
                f"Meta WhatsApp API HTTP {response.status_code}: {response.text[:200]}"
            )

        # A success body always carries the accepted message id.
        if not (isinstance(data, dict) and data.get("messages")):
            raise WhatsAppDeliveryError(
                f"Meta response contained no accepted message: {str(data)[:200]}"
            )
