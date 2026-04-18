"""
RazorpayAdapter — isolated outbound gateway wrapper.

Responsibilities:
  - Translate Payment model fields into Razorpay API calls
  - Return raw gateway data to the caller
  - Know nothing about memberships, tenants, or domain business rules

Constructed with a config object (TenantPaymentConfig or SimpleNamespace) so
there is zero dependency on global Django settings at runtime.

All domain logic (idempotency, state transitions, signals) lives in PaymentService.
"""
import razorpay


class RazorpayError(Exception):
    pass


class RazorpayAdapter:

    def __init__(self, config):
        """
        Args:
            config: TenantPaymentConfig instance or SimpleNamespace with
                    .key_id and .key_secret attributes.
        """
        self._config = config
        self._client = razorpay.Client(auth=(config.key_id, config.key_secret))

    def create_order(self, payment) -> dict:
        """
        Create a Razorpay order for the given Payment record.

        Returns:
            {
                "order_id": str,  — Razorpay order ID (order_Xxx...)
                "amount":   int,  — amount in paise (₹1 = 100 paise)
                "currency": str,  — e.g. "INR"
                "key":      str,  — public key_id for Razorpay Checkout JS
            }

        Raises:
            RazorpayError: on SDK or network failure
        """
        amount_paise = int(payment.amount * 100)

        try:
            order = self._client.order.create({
                "amount":   amount_paise,
                "currency": payment.currency,
                "receipt":  str(payment.id),
                "notes": {
                    "payment_id":     str(payment.id),
                    "reference_type": payment.reference_type or "",
                    "reference_id":   str(payment.reference_id) if payment.reference_id else "",
                },
            })
        except razorpay.errors.BadRequestError as exc:
            raise RazorpayError(f"Razorpay order creation failed: {exc}") from exc
        except Exception as exc:
            raise RazorpayError(f"Razorpay API error: {exc}") from exc

        return {
            "order_id": order["id"],
            "amount":   amount_paise,
            "currency": order["currency"],
            "key":      self._config.key_id,   # safe to expose to frontend
        }
