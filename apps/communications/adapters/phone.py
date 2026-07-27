"""Shared recipient-number normalisation for the messaging adapters.

MSG91 (SMS) and Meta (WhatsApp) both want a bare E.164-style number — country
code plus subscriber number, no ``+``, no spaces or punctuation. The rules for
converting the shapes member data actually arrives in are identical for both,
so they live here rather than being duplicated per adapter and drifting.
"""

import re

INDIA_CC = "91"


class PhoneNumberError(ValueError):
    """Raised when a recipient number cannot be normalised."""


def normalise_msisdn(raw: str) -> str:
    """Return a bare number: country code + subscriber number.

    Accepts the shapes real data arrives in — ``+91 98765 43210``,
    ``098765-43210``, ``9876543210`` — and returns ``919876543210``.
    Numbers that already carry a country code are passed through.
    """
    digits = re.sub(r"\D", "", raw or "")

    if not digits:
        raise PhoneNumberError("Recipient phone number is empty.")

    # Local Indian format: drop a single trunk '0', then prefix the country code.
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10:
        digits = INDIA_CC + digits

    if not (10 < len(digits) <= 15):  # E.164 upper bound
        raise PhoneNumberError(f"Recipient phone number looks invalid: {raw!r}")

    return digits
