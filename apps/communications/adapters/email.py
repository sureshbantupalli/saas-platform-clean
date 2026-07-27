"""Email adapter.

Replaces the previous mock, which only wrote the message to the log.

Sends through Django's own email framework rather than a provider SDK. AWS SES
is reached over its SMTP interface, which means:

  * no extra dependency (no boto3)
  * the provider is swappable via settings alone — SES, SendGrid, Mailgun or a
    local relay all work unchanged
  * tests can use Django's locmem backend and assert against ``mail.outbox``

Design constraints this file has to respect:

* ``communication_service._get_adapter()`` instantiates **every** adapter on
  each send, so ``__init__`` must never raise. Missing mail credentials must
  not take SMS and WHATSAPP down with it.
* The caller wraps ``send()`` in try/except and builds a FAILED
  CommunicationLog from the exception, which ``retry_failed_messages`` later
  picks up. A delivery failure therefore MUST raise — returning quietly would
  record an undelivered message as SENT.
* The caller passes rendered HTML in ``message`` and the plain-text
  alternative in ``text``, so this sends a real multipart/alternative message
  rather than HTML only. Text-only clients and spam filters both care.
* When mail is not configured the adapter falls back to the old logging
  behaviour, so local development and the test-suite work without credentials.
"""

import logging
import os
import re

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection

from .base import BaseAdapter

logger = logging.getLogger("apps.communications.email")

# Deliberately permissive — the goal is to catch obviously unusable values
# (empty, a phone number, a name) before opening an SMTP connection, not to
# re-implement RFC 5322.
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

SMTP_BACKEND = "django.core.mail.backends.smtp.EmailBackend"


class EmailDeliveryError(Exception):
    """Raised when the message could not be handed to the mail provider."""


def _setting(name: str, default: str = "") -> str:
    """Read config from Django settings, falling back to the environment."""
    value = getattr(settings, name, None)
    if value in (None, ""):
        value = os.environ.get(name, default)
    return (value or "").strip()


def _html_to_text(html: str) -> str:
    """Crude fallback used only when the caller supplied no text alternative.

    A multipart message with an empty text part is worse than no text part at
    all, so this produces something readable rather than nothing.
    """
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", html or "")
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|tr|h[1-6])\s*>", "\n\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


class EmailAdapter(BaseAdapter):
    """Sends branded HTML email with a plain-text alternative."""

    def __init__(self):
        # Never raise here — see module docstring.
        self.backend = _setting("EMAIL_BACKEND", SMTP_BACKEND)
        self.host = _setting("EMAIL_HOST")
        self.from_email = _setting("DEFAULT_FROM_EMAIL")

    @property
    def is_configured(self) -> bool:
        """True when mail can actually leave the box.

        Only the SMTP backend needs a host; an explicitly chosen backend
        (locmem in tests, console in dev, a provider backend in production)
        is self-sufficient and just needs a From address.
        """
        if self.backend == SMTP_BACKEND:
            return bool(self.host and self.from_email)
        return bool(self.from_email)

    def send(self, to: str, message: str, subject: str = "", text: str = "") -> None:
        if not self.is_configured:
            # Same behaviour as the old mock, so dev and tests are unaffected.
            logger.info(
                "[Email:unconfigured] to=%s | subject=%s | html_len=%d",
                to,
                subject,
                len(message or ""),
            )
            return

        recipient = (to or "").strip()
        if not EMAIL_RE.match(recipient):
            raise EmailDeliveryError(f"Recipient email looks invalid: {to!r}")

        if not (subject or "").strip():
            # An empty Subject header is a strong spam signal and reads as a
            # broken send to the member.
            raise EmailDeliveryError("Refusing to send an email with an empty subject.")

        body_text = (text or "").strip() or _html_to_text(message)
        if not body_text:
            raise EmailDeliveryError("Refusing to send an email with an empty body.")

        try:
            email = EmailMultiAlternatives(
                subject=subject,
                body=body_text,
                from_email=self.from_email,
                to=[recipient],
                # fail_silently=False so SMTP errors surface as exceptions and
                # the caller can record FAILED for retry.
                connection=get_connection(backend=self.backend, fail_silently=False),
            )
            if message:
                email.attach_alternative(message, "text/html")

            accepted = email.send(fail_silently=False)
        except EmailDeliveryError:
            raise
        except Exception as exc:  # SMTP auth/TLS, DNS, timeouts, refused relay
            raise EmailDeliveryError(f"Email send failed: {exc}") from exc

        if not accepted:
            # send() returning 0 means nothing was delivered; without this the
            # message would be recorded as SENT.
            raise EmailDeliveryError("Mail backend accepted 0 messages.")

        # Deliberately does not log the body (PII) or any credentials.
        logger.info(
            "[Email] accepted by mail backend",
            extra={"recipient": recipient, "subject": subject},
        )
