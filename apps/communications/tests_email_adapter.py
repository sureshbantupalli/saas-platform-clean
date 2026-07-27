"""Tests for the email adapter.

Focus is on the failure modes that would silently lose member communication:

1. The adapter must raise on failure, because communication_service turns the
   exception into a FAILED CommunicationLog, which the retry command later
   picks up. Returning quietly would record an undelivered email as SENT.
2. The caller renders HTML *and* plain text, so the message that leaves must
   be genuinely multipart — an HTML-only send lands in spam far more often.
3. Without credentials the adapter must degrade to logging rather than raise,
   since communication_service builds every adapter on every send.
"""

from smtplib import SMTPAuthenticationError
from unittest.mock import patch

from django.core import mail
from django.test import SimpleTestCase, override_settings

from apps.communications.adapters.email import (
    EmailAdapter,
    EmailDeliveryError,
    _html_to_text,
)

LOCMEM = "django.core.mail.backends.locmem.EmailBackend"
SMTP = "django.core.mail.backends.smtp.EmailBackend"

CONFIGURED = dict(EMAIL_BACKEND=LOCMEM, DEFAULT_FROM_EMAIL="no-reply@anjasi.test")

HTML = "<html><body><p>Hello <b>Asha</b></p></body></html>"


class UnconfiguredTests(SimpleTestCase):
    """No credentials must mean 'log and move on', never an exception."""

    @override_settings(EMAIL_BACKEND=SMTP, EMAIL_HOST="", DEFAULT_FROM_EMAIL="")
    def test_constructor_does_not_raise(self):
        with patch.dict("os.environ", {}, clear=False):
            self.assertFalse(EmailAdapter().is_configured)

    @override_settings(EMAIL_BACKEND=SMTP, EMAIL_HOST="", DEFAULT_FROM_EMAIL="")
    def test_send_is_a_no_op(self):
        with patch.dict("os.environ", {"EMAIL_HOST": "", "DEFAULT_FROM_EMAIL": ""}):
            EmailAdapter().send(to="a@b.com", message=HTML, subject="Hi", text="Hello")
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(EMAIL_BACKEND=SMTP, EMAIL_HOST="smtp.test", DEFAULT_FROM_EMAIL="")
    def test_smtp_host_without_from_address_is_not_configured(self):
        with patch.dict("os.environ", {"DEFAULT_FROM_EMAIL": ""}):
            self.assertFalse(EmailAdapter().is_configured)


@override_settings(**CONFIGURED)
class SendTests(SimpleTestCase):
    def setUp(self):
        self.adapter = EmailAdapter()

    def test_accepts_the_base_adapter_signature(self):
        """communication_service always passes `text=`."""
        self.adapter.send(to="a@b.com", message=HTML, subject="s", text="t")
        self.assertEqual(len(mail.outbox), 1)

    def test_sends_multipart_html_plus_text(self):
        self.adapter.send(
            to="asha@example.com", message=HTML, subject="Welcome", text="Hello Asha"
        )

        sent = mail.outbox[0]
        self.assertEqual(sent.subject, "Welcome")
        self.assertEqual(sent.to, ["asha@example.com"])
        self.assertEqual(sent.from_email, "no-reply@anjasi.test")
        # Plain text is the body; HTML rides as the alternative.
        self.assertEqual(sent.body, "Hello Asha")
        self.assertEqual(sent.alternatives[0][0], HTML)
        self.assertEqual(sent.alternatives[0][1], "text/html")

    def test_derives_text_part_when_caller_supplies_none(self):
        """A multipart email with an empty text part is worse than no text."""
        self.adapter.send(to="a@b.com", message=HTML, subject="Welcome", text="")

        body = mail.outbox[0].body
        self.assertIn("Hello Asha", body)
        self.assertNotIn("<b>", body)

    def test_rejects_invalid_recipient(self):
        for bad in ["", "   ", "9876543210", "not-an-email", "a@b", None]:
            with self.subTest(bad=bad):
                with self.assertRaises(EmailDeliveryError):
                    self.adapter.send(to=bad, message=HTML, subject="s", text="t")
        self.assertEqual(len(mail.outbox), 0)

    def test_rejects_empty_subject(self):
        """An empty Subject header is a strong spam signal."""
        with self.assertRaises(EmailDeliveryError):
            self.adapter.send(to="a@b.com", message=HTML, subject="  ", text="t")

    def test_rejects_empty_body(self):
        with self.assertRaises(EmailDeliveryError):
            self.adapter.send(to="a@b.com", message="", subject="s", text="")

    def test_raises_on_smtp_error(self):
        with patch(
            "django.core.mail.EmailMultiAlternatives.send",
            side_effect=SMTPAuthenticationError(535, b"bad credentials"),
        ):
            with self.assertRaises(EmailDeliveryError):
                self.adapter.send(to="a@b.com", message=HTML, subject="s", text="t")

    def test_raises_when_backend_accepts_zero_messages(self):
        """Without this check an undelivered message is recorded as SENT."""
        with patch("django.core.mail.EmailMultiAlternatives.send", return_value=0):
            with self.assertRaises(EmailDeliveryError):
                self.adapter.send(to="a@b.com", message=HTML, subject="s", text="t")

    def test_does_not_log_message_body(self):
        """Message bodies are PII."""
        with self.assertLogs("apps.communications.email", level="INFO") as captured:
            self.adapter.send(
                to="a@b.com",
                message="<p>SECRET-BODY-TEXT</p>",
                subject="s",
                text="SECRET-BODY-TEXT",
            )
        self.assertNotIn("SECRET-BODY-TEXT", "\n".join(captured.output))


class HtmlToTextTests(SimpleTestCase):
    def test_strips_markup_and_drops_script_and_style(self):
        html = (
            "<style>p{color:red}</style><script>alert(1)</script>"
            "<p>Line one</p><p>Line two<br>Line three</p>"
        )
        text = _html_to_text(html)

        for unwanted in ["<p>", "alert(1)", "color:red"]:
            self.assertNotIn(unwanted, text)
        for wanted in ["Line one", "Line two", "Line three"]:
            self.assertIn(wanted, text)

    def test_handles_empty_input(self):
        self.assertEqual(_html_to_text(""), "")
        self.assertEqual(_html_to_text(None), "")
