from django.dispatch import Signal

# Fired by PaymentService after a successful state transition
payment_success  = Signal()   # kwargs: payment
payment_failed   = Signal()   # kwargs: payment
payment_refunded = Signal()   # kwargs: payment, refund_amount (Decimal), refund_id (str)
