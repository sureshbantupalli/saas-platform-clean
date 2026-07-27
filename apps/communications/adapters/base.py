"""Transport adapter contract for the three messaging channels.

Concrete adapters: ``sms.py`` (MSG91), ``email.py`` (SMTP/SES),
``whatsapp.py`` (Meta Cloud API). ``phone.py`` holds the number normalisation
shared by SMS and WhatsApp.

Every adapter MUST honour all four rules below. They are not stylistic — each
one corresponds to a failure that has actually occurred here.

1. ``__init__`` MUST NOT raise.
   ``communication_service._get_adapter()`` constructs *every* adapter on
   *every* send. An adapter that raises on a missing credential takes the
   other two channels down with it.

2. ``send()`` MUST raise on delivery failure.
   The caller wraps it in try/except and turns the exception into a FAILED
   CommunicationLog, which ``retry_failed_messages`` later picks up. Returning
   quietly records an undelivered message as SENT — the message is lost and
   nothing indicates it.

3. Unconfigured MUST degrade to logging, not failure.
   Local development and the test-suite run without provider credentials.
   Expose an ``is_configured`` property and no-op (log only) when it is false.

4. The signature is exactly ``send(self, to, message, subject="", text="")``.
   All four, always. ``communication_service`` passes ``text=`` on every call,
   including SMS and WhatsApp where it goes unused.

   Rule 4 has bitten before: the original SMS and WhatsApp mocks omitted
   ``text``, so **every** send on those channels raised TypeError and was
   silently recorded as FAILED. Thirty-two existing tests missed it because
   they patch ``send`` with a ``Mock``, which accepts any keyword argument.
   ``tests_sms_adapter.AdapterContractTests`` now pins the real signature —
   keep it passing.

Provider quirks worth knowing before touching these:
  * MSG91 returns HTTP 200 even when it rejects a message, so the response
    body must be inspected rather than the status code.
  * Meta can likewise return an ``error`` object alongside a 200 status.
  * Both India channels are gated on pre-approved templates — TRAI DLT for
    SMS, Meta's 24-hour window for WhatsApp.
"""


class BaseAdapter:
    def send(self, to: str, message: str, subject: str = "", text: str = "") -> None:
        raise NotImplementedError
