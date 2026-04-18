"""
Symmetric field-level encryption for payment secrets.

Uses Fernet (AES-128-CBC + HMAC-SHA256) from the `cryptography` package.
The key comes from settings.PAYMENTS_ENCRYPTION_KEY — a URL-safe base64-encoded 32-byte value.
Generate a production key with:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Usage:
    from apps.payments.utils.encryption import EncryptedCharField
    class MyModel(models.Model):
        secret = EncryptedCharField()   # stored encrypted; decrypted transparently on read
"""
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models


def _fernet() -> Fernet:
    key = settings.PAYMENTS_ENCRYPTION_KEY
    if isinstance(key, str):
        key = key.encode()
    return Fernet(key)


def encrypt_value(plaintext: str) -> str:
    if not plaintext:
        return ""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, Exception):
        # Value may be plaintext during initial migration or in tests;
        # re-raise so callers know something is wrong rather than silently returning garbage.
        raise ValueError(
            "Failed to decrypt payment config field. "
            "Check PAYMENTS_ENCRYPTION_KEY setting."
        )


class EncryptedCharField(models.TextField):
    """
    TextField that transparently encrypts on write and decrypts on read.
    - get_prep_value()  → called by Django before INSERT/UPDATE  → encrypts
    - from_db_value()   → called by Django after SELECT          → decrypts
    """

    def from_db_value(self, value, expression, connection):
        return decrypt_value(value) if value else ""

    def to_python(self, value):
        return value or ""

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        return encrypt_value(value) if value else ""
