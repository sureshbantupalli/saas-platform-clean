"""
Simple DB-based rate limiter for outbound communications.

No Redis or external cache required. Counts non-failed messages sent to
a tenant within the last 60 seconds using a DB aggregate.

Configure via Django settings:
    COMMS_RATE_LIMIT_PER_MINUTE = 60  (default; 0 = unlimited)
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger("apps.communications")

_DEFAULT_LIMIT = 60


def get_limit() -> int:
    return getattr(settings, "COMMS_RATE_LIMIT_PER_MINUTE", _DEFAULT_LIMIT)


def is_rate_limited(tenant) -> bool:
    """
    Return True if the tenant has exceeded their per-minute message limit.
    Counts SENT + PENDING logs in the last 60 seconds (FAILED don't count
    toward the limit since they never reached the recipient).
    On any DB error → allow send (fail open, log the exception).
    """
    limit = get_limit()
    if limit <= 0:
        return False

    from apps.communications.models import CommunicationLog, MessageStatus
    try:
        window_start = timezone.now() - timedelta(minutes=1)
        recent = (
            CommunicationLog.base_objects
            .filter(tenant=tenant, created_at__gte=window_start)
            .exclude(status=MessageStatus.FAILED)
            .count()
        )
        if recent >= limit:
            logger.warning(
                "[Communications] Rate limit exceeded — message queued",
                extra={
                    "reason":    "rate_limited",
                    "tenant_id": str(tenant.pk),
                    "count":     recent,
                    "limit":     limit,
                },
            )
            return True
        return False
    except Exception as exc:
        logger.exception("[Communications] Rate limiter check failed — allowing send: %s", exc)
        return False


def record_rate_limited(tenant, channel: str, event_type: str, recipient: str) -> None:
    """Persist a FAILED log so the rate-limit event is auditable."""
    from apps.communications.models import CommunicationLog, MessageStatus
    try:
        CommunicationLog.base_objects.create(
            tenant        = tenant,
            channel       = channel,
            event_type    = event_type,
            recipient     = recipient or "unknown",
            message       = "",
            status        = MessageStatus.FAILED,
            error_message = "rate_limited: per-minute quota exceeded",
        )
    except Exception as exc:
        logger.exception("[Communications] Failed to record rate-limit log: %s", exc)
