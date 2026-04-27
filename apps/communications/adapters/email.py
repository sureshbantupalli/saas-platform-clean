import logging
from .base import BaseAdapter

logger = logging.getLogger("apps.communications.email")


class EmailAdapter(BaseAdapter):
    """Mock email adapter — logs the message. Replace with real SMTP/SES later."""

    def send(self, to: str, message: str, subject: str = "", text: str = "") -> None:
        logger.info(
            "[Email] to=%s | subject=%s | html_len=%d | text_preview=%s",
            to, subject, len(message), (text[:200] if text else "(none)"),
        )
