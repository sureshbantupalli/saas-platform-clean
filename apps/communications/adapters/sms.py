"""MSG91 SMS adapter (India).

Replaces the previous mock, which only wrote the message to the log.

Design constraints this file has to respect:

* ``communication_service._get_adapter()`` instantiates **every** adapter on
  each send, so ``__init__`` must never raise. A missing MSG91 key must not
  take EMAIL and WHATSAPP down with it.
* The caller wraps ``send()`` in try/except and builds a FAILED
  CommunicationLog from the exception, which ``retry_failed_messages`` later
  picks up. A delivery failure therefore MUST raise — returning quietly would
  record an undelivered message as SENT.
* The caller always passes ``text=``. The previous signature omitted it, so
  every SMS send raised TypeError before reaching any provider. The full
  four-argument signature from BaseAdapter is required.
* When MSG91 is not configured the adapter falls back to the old logging
  behaviour, so local development and the test-suite work without credentials.
* Credentials are resolved PER TENANT via TenantMessagingConfig. Under TRAI
  DLT the sender header is registered to the tenant's own Principal Entity, so
  a second tenant sending under global env credentials would go out under the
  wrong registration. Env vars remain a fallback for dev / single-tenant.

India specifics: MSG91 delivers through DLT-approved templates, so a flow
template id is required. The rendered message is passed as the ``body``
variable — the DLT template registered with the operator must expose a
matching variable or the operator rejects the submission.
"""

import logging
import os

import requests
from django.conf import settings

from .base import BaseAdapter
from .phone import PhoneNumberError
from .phone import normalise_msisdn as _normalise_msisdn

logger = logging.getLogger("apps.communications.sms")

MSG91_FLOW_URL = "https://control.msg91.com/api/v5/flow/"
DEFAULT_TIMEOUT = 10  # seconds — must not hang the request thread


class SMSDeliveryError(Exception):
    """Raised when MSG91 does not accept the message for delivery."""


def _setting(name: str, default: str = "") -> str:
    """Read config from Django settings, falling back to the environment."""
    value = getattr(settings, name, None)
    if value in (None, ""):
        value = os.environ.get(name, default)
    return (value or "").strip()


def normalise_msisdn(raw: str) -> str:
    """Normalise a recipient number, raising the SMS-channel exception.

    The rules themselves live in ``adapters.phone`` because WhatsApp needs the
    identical treatment; this only re-raises as ``SMSDeliveryError`` so callers
    of this adapter have a single exception type to catch.
    """
    try:
        return _normalise_msisdn(raw)
    except PhoneNumberError as exc:
        raise SMSDeliveryError(str(exc)) from exc


class SMSAdapter(BaseAdapter):
    """Sends SMS via MSG91's Flow API, or logs when unconfigured."""

    def __init__(self, tenant=None):
        """Credentials come from the tenant's own MSG91 registration.

        Under TRAI DLT the sender header belongs to the tenant, so sending a
        second tenant's message under global env credentials would put it out
        under the wrong Principal Entity. The env fallback is kept for local
        development and the single-tenant deployment; the config service logs
        loudly when it is used while several tenants exist.

        Never raises — see module docstring.
        """
        from apps.communications.models import MessagingProvider
        from apps.communications.services.messaging_config_service import (
            get_messaging_config, warn_if_env_fallback_is_ambiguous,
        )

        self.tenant = tenant
        config = get_messaging_config(tenant, MessagingProvider.MSG91)
        warn_if_env_fallback_is_ambiguous(tenant, MessagingProvider.MSG91, config)

        self.auth_key = getattr(config, "api_key", "") or ""
        self.sender_id = getattr(config, "sender_id", "") or ""
        self.template_id = getattr(config, "template_id", "") or ""
        try:
            self.timeout = int(_setting("MSG91_TIMEOUT") or DEFAULT_TIMEOUT)
        except ValueError:
            self.timeout = DEFAULT_TIMEOUT

    @property
    def is_configured(self) -> bool:
        return bool(self.auth_key and self.template_id)

    def send(self, to: str, message: str, subject: str = "", text: str = "") -> None:
        if not self.is_configured:
            # Same behaviour as the old mock, so dev and tests are unaffected.
            logger.info("[SMS:unconfigured] to=%s | %s", to, (message or "")[:160])
            return

        mobile = normalise_msisdn(to)

        payload = {
            "template_id": self.template_id,
            "short_url": "0",
            "realTimeResponse": "1",
            "recipients": [{"mobiles": mobile, "body": message}],
        }
        if self.sender_id:
            payload["sender"] = self.sender_id

        headers = {
            "authkey": self.auth_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        try:
            response = requests.post(
                MSG91_FLOW_URL, json=payload, headers=headers, timeout=self.timeout
            )
        except requests.Timeout as exc:
            raise SMSDeliveryError(f"MSG91 timed out after {self.timeout}s") from exc
        except requests.RequestException as exc:
            raise SMSDeliveryError(f"MSG91 request failed: {exc}") from exc

        self._raise_for_failure(response)

        # Deliberately does not log the message body (PII) or the auth key.
        logger.info(
            "[SMS] accepted by MSG91",
            extra={"recipient": mobile, "template_id": self.template_id},
        )

    @staticmethod
    def _raise_for_failure(response) -> None:
        """MSG91 answers HTTP 200 even for rejections, so inspect the body.

        Trusting the status code is the classic failure mode here: the message
        would be recorded as SENT while the operator never delivered it.
        """
        if response.status_code >= 400:
            raise SMSDeliveryError(
                f"MSG91 HTTP {response.status_code}: {response.text[:200]}"
            )

        try:
            data = response.json()
        except ValueError:
            raise SMSDeliveryError(
                f"MSG91 returned non-JSON response: {response.text[:200]}"
            )

        # Success looks like {"type": "success", "message": "<request id>"}.
        if str(data.get("type", "")).lower() == "error":
            raise SMSDeliveryError(f"MSG91 rejected the message: {data}")

        # Some error shapes omit "type" and carry only an "errors" block.
        if data.get("errors"):
            raise SMSDeliveryError(f"MSG91 rejected the message: {data}")
