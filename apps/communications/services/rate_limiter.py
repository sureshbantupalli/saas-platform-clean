"""
Simple DB-based rate limiter for outbound communications.

No Redis or external cache required. Counts non-failed messages sent to
a tenant within the last 60 seconds using a DB aggregate.

Configure via Django settings:
    COMMS_RATE_LIMIT_PER_MINUTE     = 60   (default; 0 = unlimited)
    COMMS_RATE_LIMIT_SAFE_FALLBACK  = 10   (used when DB is unavailable)
"""
import logging
import threading
import time
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger("apps.communications")

_DEFAULT_LIMIT        = 60
_DEFAULT_SAFE_LIMIT   = 10

# In-memory fallback: {tenant_pk: [(timestamp, ...), ...]}
_fallback_lock    = threading.Lock()
_fallback_counts: dict[str, list] = {}


def get_limit() -> int:
    return getattr(settings, "COMMS_RATE_LIMIT_PER_MINUTE", _DEFAULT_LIMIT)


def _get_safe_limit() -> int:
    return getattr(settings, "COMMS_RATE_LIMIT_SAFE_FALLBACK", _DEFAULT_SAFE_LIMIT)


def _fallback_is_rate_limited(tenant_pk: str) -> bool:
    """
    Thread-safe in-memory counter used when the DB is unavailable.
    Counts sends in the last 60 seconds against COMMS_RATE_LIMIT_SAFE_FALLBACK.
    """
    safe_limit = _get_safe_limit()
    if safe_limit <= 0:
        return False

    now = time.monotonic()
    cutoff = now - 60.0

    with _fallback_lock:
        timestamps = _fallback_counts.get(tenant_pk, [])
        # Evict stale entries
        timestamps = [t for t in timestamps if t > cutoff]
        _fallback_counts[tenant_pk] = timestamps

        if len(timestamps) >= safe_limit:
            return True

        timestamps.append(now)
        return False


def is_rate_limited(tenant) -> bool:
    """
    Return True if the tenant has exceeded their per-minute message limit.
    Counts SENT + PENDING logs in the last 60 seconds (FAILED don't count
    toward the limit since they never reached the recipient).
    On DB error → fail SAFE using the in-memory fallback counter.
    """
    limit = get_limit()
    if limit <= 0:
        return False

    from apps.communications.models import CommunicationLog, MessageStatus
    tenant_pk = str(tenant.pk)

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
                    "tenant_id": tenant_pk,
                    "count":     recent,
                    "limit":     limit,
                },
            )
            return True
        return False
    except Exception as exc:
        logger.exception(
            "[Communications] Rate limiter DB check failed — using in-memory fallback: %s", exc
        )
        limited = _fallback_is_rate_limited(tenant_pk)
        if limited:
            logger.warning(
                "[Communications] In-memory fallback rate limit exceeded",
                extra={
                    "reason":    "rate_limited_fallback",
                    "tenant_id": tenant_pk,
                    "limit":     _get_safe_limit(),
                },
            )
        return limited


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
