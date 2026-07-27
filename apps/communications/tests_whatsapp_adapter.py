"""Tests for the Meta WhatsApp Cloud API adapter.

Focus is on what would silently lose member communication in production:

1. Meta can answer HTTP 200 with an ``error`` body, so a status-code check
   alone would record undelivered messages as SENT.
2. The adapter must raise on failure, because communication_service turns the
   exception into a FAILED CommunicationLog for the retry command.
3. Business-initiated sends need a pre-approved template (the 24-hour window
   rule), so the template payload shape has to be exactly right — a malformed
   ``components`` block is rejected by Meta at send time.
"""

from unittest.mock import Mock, patch

import requests
from django.test import SimpleTestCase

from apps.communications.adapters.whatsapp import (
    MAX_TEMPLATE_PARAM,
    MAX_TEXT_BODY,
    WhatsAppAdapter,
    WhatsAppDeliveryError,
)

SUCCESS = {
    "messaging_product": "whatsapp",
    "contacts": [{"input": "919876543210", "wa_id": "919876543210"}],
    "messages": [{"id": "wamid.HBgMOTE5...", "message_status": "accepted"}],
}

TEXT_MODE = {
    "WHATSAPP_PHONE_NUMBER_ID": "1234567890",
    "WHATSAPP_ACCESS_TOKEN": "tok-secret",
    "WHATSAPP_TEMPLATE_NAME": "",  # explicit: free-form text mode
}

TEMPLATE_MODE = {
    **TEXT_MODE,
    "WHATSAPP_TEMPLATE_NAME": "class_reminder",
    "WHATSAPP_TEMPLATE_LANG": "en_US",
}


def _response(status=200, body=None, text="", json_ok=True):
    resp = Mock()
    resp.status_code = status
    resp.text = text
    resp.json = (lambda: body) if json_ok else Mock(side_effect=ValueError)
    return resp


class UnconfiguredTests(SimpleTestCase):
    """No credentials must mean 'log and move on', never an exception.

    communication_service builds every adapter on each send, so raising here
    would break SMS and EMAIL too.
    """

    def test_constructor_does_not_raise(self):
        with patch.dict("os.environ", {"WHATSAPP_ACCESS_TOKEN": ""}, clear=False):
            self.assertFalse(WhatsAppAdapter().is_configured)

    def test_send_is_a_no_op_and_makes_no_http_call(self):
        adapter = WhatsAppAdapter()
        adapter.phone_number_id = ""
        adapter.access_token = ""
        with patch("requests.post") as post:
            adapter.send(to="9876543210", message="hi", subject="", text="t")
        post.assert_not_called()


class TextModeTests(SimpleTestCase):
    """Free-form text — valid only inside Meta's 24-hour service window."""

    def setUp(self):
        self.env = patch.dict("os.environ", TEXT_MODE)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.adapter = WhatsAppAdapter()

    def test_accepts_the_base_adapter_signature(self):
        """communication_service always passes `text=`.

        The original mock omitted it, so every WhatsApp send raised TypeError
        and was recorded as FAILED before reaching any provider.
        """
        with patch("requests.post", return_value=_response(body=SUCCESS)):
            self.adapter.send(to="9876543210", message="m", subject="s", text="t")

    def test_posts_text_payload_to_the_graph_endpoint(self):
        with patch("requests.post", return_value=_response(body=SUCCESS)) as post:
            self.adapter.send(to="+91 98765 43210", message="See you at 6am", text="")

        url = post.call_args.args[0]
        kwargs = post.call_args.kwargs
        payload = kwargs["json"]

        self.assertIn("/1234567890/messages", url)
        self.assertEqual(payload["messaging_product"], "whatsapp")
        self.assertEqual(payload["to"], "919876543210")  # normalised
        self.assertEqual(payload["type"], "text")
        self.assertEqual(payload["text"]["body"], "See you at 6am")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer tok-secret")
        self.assertEqual(kwargs["timeout"], 10)

    def test_truncates_body_over_metas_text_limit(self):
        """Meta hard-rejects over-length bodies; a trimmed message still lands."""
        with patch("requests.post", return_value=_response(body=SUCCESS)) as post:
            self.adapter.send(to="9876543210", message="x" * (MAX_TEXT_BODY + 50))

        sent = post.call_args.kwargs["json"]["text"]["body"]
        self.assertEqual(len(sent), MAX_TEXT_BODY)
        self.assertTrue(sent.endswith("…"))


class TemplateModeTests(SimpleTestCase):
    """Business-initiated sends land outside the 24h window and need a template."""

    def setUp(self):
        self.env = patch.dict("os.environ", TEMPLATE_MODE)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.adapter = WhatsAppAdapter()

    def test_posts_template_payload_with_single_body_parameter(self):
        with patch("requests.post", return_value=_response(body=SUCCESS)) as post:
            self.adapter.send(to="9876543210", message="Class at 6am", text="")

        template = post.call_args.kwargs["json"]["template"]
        self.assertEqual(post.call_args.kwargs["json"]["type"], "template")
        self.assertEqual(template["name"], "class_reminder")
        self.assertEqual(template["language"]["code"], "en_US")

        component = template["components"][0]
        self.assertEqual(component["type"], "body")
        self.assertEqual(
            component["parameters"], [{"type": "text", "text": "Class at 6am"}]
        )

    def test_truncates_body_over_metas_template_parameter_limit(self):
        with patch("requests.post", return_value=_response(body=SUCCESS)) as post:
            self.adapter.send(to="9876543210", message="y" * (MAX_TEMPLATE_PARAM + 50))

        param = post.call_args.kwargs["json"]["template"]["components"][0][
            "parameters"
        ][0]["text"]
        self.assertEqual(len(param), MAX_TEMPLATE_PARAM)


class FailureTests(SimpleTestCase):
    def setUp(self):
        self.env = patch.dict("os.environ", TEXT_MODE)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.adapter = WhatsAppAdapter()

    def _assert_raises(self, **post_kwargs):
        with patch("requests.post", **post_kwargs):
            with self.assertRaises(WhatsAppDeliveryError):
                self.adapter.send(to="9876543210", message="m", text="")

    def test_raises_on_error_body_returned_with_http_200(self):
        """The important one — a 200 body can still be a rejection."""
        self._assert_raises(
            return_value=_response(
                body={"error": {"code": 131047, "message": "Re-engagement message"}}
            )
        )

    def test_raises_on_expired_token(self):
        self._assert_raises(
            return_value=_response(
                status=401,
                body={"error": {"code": 190, "message": "Access token has expired"}},
            )
        )

    def test_raises_on_http_error_without_error_body(self):
        self._assert_raises(return_value=_response(status=500, body={}, text="oops"))

    def test_raises_when_response_has_no_accepted_message(self):
        self._assert_raises(return_value=_response(body={"messaging_product": "whatsapp"}))

    def test_raises_on_non_json_body(self):
        self._assert_raises(
            return_value=_response(status=502, text="<html>502</html>", json_ok=False)
        )

    def test_raises_on_timeout(self):
        self._assert_raises(side_effect=requests.Timeout())

    def test_raises_on_connection_error(self):
        self._assert_raises(side_effect=requests.ConnectionError("dns fail"))

    def test_raises_on_invalid_recipient(self):
        for bad in ["", "   ", "123", "abc", None]:
            with self.subTest(bad=bad):
                with patch("requests.post") as post:
                    with self.assertRaises(WhatsAppDeliveryError):
                        self.adapter.send(to=bad, message="m", text="")
                post.assert_not_called()

    def test_raises_on_empty_message(self):
        with patch("requests.post") as post:
            with self.assertRaises(WhatsAppDeliveryError):
                self.adapter.send(to="9876543210", message="   ", text="t")
        post.assert_not_called()

    def test_does_not_log_message_body_or_access_token(self):
        """Message bodies are PII and the token is a secret."""
        with patch("requests.post", return_value=_response(body=SUCCESS)):
            with self.assertLogs(
                "apps.communications.whatsapp", level="INFO"
            ) as captured:
                self.adapter.send(to="9876543210", message="SECRET-BODY-TEXT", text="")

        joined = "\n".join(captured.output)
        self.assertNotIn("SECRET-BODY-TEXT", joined)
        self.assertNotIn("tok-secret", joined)
