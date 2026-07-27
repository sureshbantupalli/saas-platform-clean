"""Tests for the MSG91 SMS adapter.

Covers the two things most likely to cause silent data loss in production:

1. MSG91 answers HTTP 200 even when it rejects a message, so a status-code
   check alone would record undelivered messages as SENT.
2. The adapter must raise on failure, because communication_service turns the
   exception into a FAILED CommunicationLog, which is what the retry command
   later picks up.
"""

from unittest.mock import Mock, patch

import requests
from django.test import SimpleTestCase

from apps.communications.adapters.sms import (
    SMSAdapter,
    SMSDeliveryError,
    normalise_msisdn,
)


def _response(status=200, body=None, text="", json_ok=True):
    resp = Mock()
    resp.status_code = status
    resp.text = text
    resp.json = (lambda: body) if json_ok else Mock(side_effect=ValueError)
    return resp


CONFIGURED = {"MSG91_AUTH_KEY": "test-key", "MSG91_DLT_TE_ID": "tmpl-123"}


class NormaliseMsisdnTests(SimpleTestCase):
    def test_accepts_real_world_formats(self):
        for raw in [
            "9876543210",
            "+91 98765 43210",
            "09876543210",
            "098765-43210",
            "919876543210",
            "+919876543210",
        ]:
            with self.subTest(raw=raw):
                self.assertEqual(normalise_msisdn(raw), "919876543210")

    def test_rejects_unusable_numbers(self):
        for raw in ["", "   ", "123", "abc", None]:
            with self.subTest(raw=raw):
                with self.assertRaises(SMSDeliveryError):
                    normalise_msisdn(raw)


class SMSAdapterUnconfiguredTests(SimpleTestCase):
    """Without credentials the adapter must degrade to logging, not explode.

    communication_service builds every adapter on each send, so raising here
    would break EMAIL and WHATSAPP too.
    """

    def test_constructor_does_not_raise(self):
        with patch.dict("os.environ", {}, clear=False):
            SMSAdapter()  # must not raise

    def test_send_is_a_no_op_and_makes_no_http_call(self):
        adapter = SMSAdapter()
        adapter.auth_key = ""
        adapter.template_id = ""
        with patch("requests.post") as post:
            adapter.send(to="9876543210", message="hi", subject="", text="t")
        post.assert_not_called()


class SMSAdapterSendTests(SimpleTestCase):
    def setUp(self):
        self.env = patch.dict("os.environ", CONFIGURED)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.adapter = SMSAdapter()

    def test_accepts_the_base_adapter_signature(self):
        """communication_service always passes `text=`.

        The original adapter omitted it, so every SMS send raised TypeError
        and was recorded as FAILED before reaching any provider.
        """
        with patch("requests.post", return_value=_response(body={"type": "success"})):
            self.adapter.send(to="9876543210", message="m", subject="s", text="t")

    def test_posts_normalised_number_and_template(self):
        with patch(
            "requests.post", return_value=_response(body={"type": "success"})
        ) as post:
            self.adapter.send(to="+91 98765 43210", message="hello", text="")

        kwargs = post.call_args.kwargs
        self.assertEqual(
            kwargs["json"]["recipients"][0]["mobiles"], "919876543210"
        )
        self.assertEqual(kwargs["json"]["template_id"], "tmpl-123")
        self.assertEqual(kwargs["headers"]["authkey"], "test-key")
        self.assertEqual(kwargs["timeout"], 10)

    def test_raises_when_msg91_rejects_with_http_200(self):
        """The important one — a 200 body can still be a rejection."""
        with patch(
            "requests.post",
            return_value=_response(body={"type": "error", "message": "bad template"}),
        ):
            with self.assertRaises(SMSDeliveryError):
                self.adapter.send(to="9876543210", message="m", text="")

    def test_raises_on_errors_block_without_type(self):
        with patch(
            "requests.post",
            return_value=_response(body={"errors": {"mobiles": "invalid"}}),
        ):
            with self.assertRaises(SMSDeliveryError):
                self.adapter.send(to="9876543210", message="m", text="")

    def test_raises_on_http_error(self):
        with patch(
            "requests.post", return_value=_response(status=401, text="unauthorized")
        ):
            with self.assertRaises(SMSDeliveryError):
                self.adapter.send(to="9876543210", message="m", text="")

    def test_raises_on_non_json_body(self):
        with patch(
            "requests.post",
            return_value=_response(text="<html>502</html>", json_ok=False),
        ):
            with self.assertRaises(SMSDeliveryError):
                self.adapter.send(to="9876543210", message="m", text="")

    def test_raises_on_timeout(self):
        with patch("requests.post", side_effect=requests.Timeout()):
            with self.assertRaises(SMSDeliveryError):
                self.adapter.send(to="9876543210", message="m", text="")

    def test_raises_on_connection_error(self):
        with patch("requests.post", side_effect=requests.ConnectionError("dns fail")):
            with self.assertRaises(SMSDeliveryError):
                self.adapter.send(to="9876543210", message="m", text="")

    def test_does_not_log_message_body_or_auth_key(self):
        """Message bodies are PII and the auth key is a secret."""
        with patch("requests.post", return_value=_response(body={"type": "success"})):
            with self.assertLogs("apps.communications.sms", level="INFO") as captured:
                self.adapter.send(
                    to="9876543210", message="SECRET-BODY-TEXT", text=""
                )
        joined = "\n".join(captured.output)
        self.assertNotIn("SECRET-BODY-TEXT", joined)
        self.assertNotIn("test-key", joined)


class AdapterContractTests(SimpleTestCase):
    """Every adapter must accept the full BaseAdapter signature."""

    def test_all_adapters_accept_text_kwarg(self):
        from apps.communications.adapters.email import EmailAdapter
        from apps.communications.adapters.whatsapp import WhatsAppAdapter

        # Force each adapter into its unconfigured/no-op branch, so this
        # exercises the signature without touching a provider no matter what
        # happens to be set in the developer's environment.
        sms = SMSAdapter()
        sms.auth_key = sms.template_id = ""

        whatsapp = WhatsAppAdapter()
        whatsapp.phone_number_id = whatsapp.access_token = ""

        email = EmailAdapter()
        email.host = email.from_email = ""

        with patch("requests.post") as post:
            for adapter in (sms, whatsapp, email):
                with self.subTest(adapter=type(adapter).__name__):
                    adapter.send(to="9876543210", message="m", subject="s", text="t")

        post.assert_not_called()
