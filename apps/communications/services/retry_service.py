"""
Retry logic for failed CommunicationLog records.

retry_failed_messages(tenant=None, max_retries=3)
    Finds FAILED logs with retry_count < max_retries and reattempts sending.
    Returns the count of newly-successful retries.

Designed to be called by the retry_failed_messages management command,
or triggered programmatically (e.g., from a Celery periodic task).

Exponential backoff is advisory only at this layer — the caller (management
command or task scheduler) controls when to call this function. Simple
approach: run every N minutes; the retry_count cap limits total attempts.
"""
import logging

from django.utils import timezone

from apps.communications.models import CommunicationLog, MessageStatus

logger = logging.getLogger("apps.communications")

MAX_RETRIES = 3


def retry_failed_messages(tenant=None, max_retries: int = MAX_RETRIES) -> int:
    """
    Retry all FAILED CommunicationLogs that have not yet hit max_retries.
    Returns the count of messages that succeeded on this retry pass.
    """
    qs = (
        CommunicationLog.base_objects
        .filter(status=MessageStatus.FAILED, retry_count__lt=max_retries, is_deleted=False)
        .select_related("tenant")
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
    Updates retry_count and last_attempt_at regardless of outcome.
    Returns True on success.
    """
    from apps.communications.services.communication_service import _get_adapter

    adapter = _get_adapter(log.channel)
    log.retry_count     += 1
    log.last_attempt_at  = timezone.now()

    if adapter is None:
        log.status        = MessageStatus.FAILED
        log.error_message = f"No adapter for channel: {log.channel}"
        log.save(update_fields=["retry_count", "last_attempt_at", "error_message", "updated_at"])
        return False

    try:
        adapter.send(to=log.recipient, message=log.message, subject=log.subject or "")
        log.status        = MessageStatus.SENT
        log.error_message = ""
        log.save(update_fields=["status", "retry_count", "last_attempt_at", "error_message", "updated_at"])
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
        log.status        = MessageStatus.FAILED
        log.error_message = str(exc)
        log.save(update_fields=["status", "retry_count", "last_attempt_at", "error_message", "updated_at"])
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
