import logging
from .base import BaseAdapter

logger = logging.getLogger("apps.communications.sms")


class SMSAdapter(BaseAdapter):
    """Mock SMS adapter — logs the message. Replace with real provider later."""

    def send(self, to: str, message: str, subject: str = "") -> None:
        logger.info("[SMS] to=%s | %s", to, message[:160])
