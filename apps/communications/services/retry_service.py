"""
Retry logic for failed CommunicationLog records.

retry_failed_messages(tenant=None, max_retries=3)
    Finds FAILED logs that are due for retry (next_attempt_at <= now or null)
    and reattempts sending. Returns the count of newly-successful retries.

Exponential backoff: next_attempt_at = now + BASE_DELAY_MINUTES * 2^(retry_count-1)
Priority ordering: HIGH(1) before MEDIUM(2) before LOW(3).
"""
import logging
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from apps.communications.models import CommunicationLog, MessageStatus

logger = logging.getLogger("apps.communications")

MAX_RETRIES        = 3
BASE_DELAY_MINUTES = 5
MAX_BACKOFF_MINUTES = 60


def _backoff_minutes(retry_count: int) -> int:
    """Exponential delay capped at MAX_BACKOFF_MINUTES."""
    return min(BASE_DELAY_MINUTES * (2 ** (retry_count - 1)), MAX_BACKOFF_MINUTES)


def retry_failed_messages(tenant=None, max_retries: int = MAX_RETRIES) -> int:
    """
    Retry all FAILED CommunicationLogs that are due (next_attempt_at <= now or null)
    and have not yet hit max_retries. Ordered by priority then next_attempt_at.
    Returns the count of messages that succeeded on this retry pass.
    """
    now = timezone.now()
    qs = (
        CommunicationLog.base_objects
        .filter(
            status=MessageStatus.FAILED,
            retry_count__lt=max_retries,
            is_deleted=False,
        )
        .filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now))
        .select_related("tenant")
        .order_by("priority", "next_attempt_at")
    )
    if tenant is not None:
        qs = qs.filter(tenant=tenant)

    succeeded = 0
    for log in qs:
        if _retry_log(log):
            succeeded += 1
    return succeeded


def _retry_log(log: CommunicationLog) -> bool:
    """
    Attempt one resend for a single FAILED log entry.
    Updates retry_count, last_attempt_at, and next_attempt_at regardless of outcome.
    Returns True on success.
    """
    from apps.communications.services.communication_service import _get_adapter

    adapter = _get_adapter(log.channel)
    log.retry_count     += 1
    log.last_attempt_at  = timezone.now()

    if adapter is None:
        delay_minutes       = _backoff_minutes(log.retry_count)
        log.next_attempt_at = timezone.now() + timedelta(minutes=delay_minutes)
        log.status          = MessageStatus.FAILED
        log.error_message   = f"No adapter for channel: {log.channel}"
        log.save(update_fields=[
            "retry_count", "last_attempt_at", "next_attempt_at", "error_message", "updated_at"
        ])
        return False

    try:
        adapter.send(to=log.recipient, message=log.message, subject=log.subject or "")
        log.status          = MessageStatus.SENT
        log.error_message   = ""
        log.next_attempt_at = None
        log.save(update_fields=[
            "status", "retry_count", "last_attempt_at", "next_attempt_at", "error_message", "updated_at"
        ])
        logger.info(
            "[Communications] Retry succeeded",
            extra={
                "reason":      "retry_success",
                "log_id":      str(log.pk),
                "channel":     log.channel,
                "event":       log.event_type,
                "tenant_id":   str(log.tenant_id),
                "recipient":   log.recipient,
                "retry_count": log.retry_count,
            },
        )
        return True
    except Exception as exc:
        delay_minutes       = _backoff_minutes(log.retry_count)
        log.next_attempt_at = timezone.now() + timedelta(minutes=delay_minutes)
        log.status          = MessageStatus.FAILED
        log.error_message   = str(exc)
        log.save(update_fields=[
            "status", "retry_count", "last_attempt_at", "next_attempt_at", "error_message", "updated_at"
        ])
        logger.warning(
            "[Communications] Retry failed",
            extra={
                "reason":      "retry_failed",
                "log_id":      str(log.pk),
                "channel":     log.channel,
                "event":       log.event_type,
                "tenant_id":   str(log.tenant_id),
                "recipient":   log.recipient,
                "retry_count": log.retry_count,
                "error":       str(exc),
            },
        )
        return False
