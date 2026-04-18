import logging
from .base import BaseAdapter

logger = logging.getLogger("apps.communications.whatsapp")


class WhatsAppAdapter(BaseAdapter):
    """Mock WhatsApp adapter — logs the message. Replace with real provider later."""

    def send(self, to: str, message: str, subject: str = "") -> None:
        logger.info("[WhatsApp] to=%s | %s", to, message[:1000])
