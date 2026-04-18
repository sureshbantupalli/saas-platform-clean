import logging
from .base import BaseAdapter

logger = logging.getLogger("apps.communications.email")


class EmailAdapter(BaseAdapter):
    """Mock email adapter — logs the message. Replace with real SMTP/SES later."""

    def send(self, to: str, message: str, subject: str = "") -> None:
        logger.info("[Email] to=%s | subject=%s | %s", to, subject, message[:500])
