"""
Rule-based retry engine with escalation and channel learning.

process_retries(now=None)
    One pass over all RetryRules, processed high → normal → low priority.
    For each rule two things happen:

    1. Normal retries  — failed attempts whose attempt_number < rule.max_attempts
       and whose delay has passed are resent on the same channel.

    2. Escalation      — failed attempts whose attempt_number == rule.max_attempts
       (retries exhausted) are tried once more on the next available channel:
         WhatsApp → SMS → Email
       If the member has a recent learned preference (within RECENCY_THRESHOLD_DAYS)
       that differs from the current channel, that is used instead.

    On every outcome a new MessageAttempt row is created (immutable history).
    Old rows are never mutated.  error_code / error_message are recorded on
    failure for downstream intelligence (carrier issues, invalid addresses, etc.).

Invariants:
  - A message is never double-retried: an Exists subquery excludes any attempt
    that already has a newer sibling for the same CommunicationLog.
  - LearningService failures are swallowed — they must never abort a retry.
"""
import logging
from datetime import timedelta

from django.db.models import Exists, OuterRef
from django.utils import timezone

from apps.engagement.models import AttemptStatus, MessageAttempt, RetryRule
from apps.engagement.learning_service import EngagementService, LearningService

logger = logging.getLogger(__name__)

# Channel escalation order when no recent learned preference is available.
_ESCALATION_NEXT: dict[str, str | None] = {
    'WHATSAPP': 'SMS',
    'SMS':      'EMAIL',
    'EMAIL':    None,
}

# Drives the processing order for RetryRules.
_PRIORITY_SORT: dict[str, int] = {'high': 0, 'normal': 1, 'low': 2}


def _pick_escalation_channel(current_channel: str, member) -> str | None:
    """
    Return the best channel to escalate to.

    Preference order:
      1. Member's recent learned channel (if different from current)
      2. Hard-coded escalation order (WhatsApp → SMS → Email)
    """
    preferred = EngagementService.get_best_channel(member)
    if preferred and preferred != current_channel:
        return preferred
    return _ESCALATION_NEXT.get(current_channel)


def _do_send(log, channel: str) -> None:
    """Call the adapter for *channel*.  Raises on failure."""
    from apps.communications.services.communication_service import _get_adapter
    adapter = _get_adapter(channel)
    if adapter is None:
        raise RuntimeError(f"No adapter for channel: {channel}")
    adapter.send(to=log.recipient, message=log.message, subject=log.subject or '')


def _create_attempt(
    attempt,
    channel: str,
    status: str,
    next_number: int,
    error_code: str = '',
    error_message: str = '',
) -> None:
    MessageAttempt.objects.create(
        tenant            = attempt.tenant,
        member            = attempt.member,
        event_name        = attempt.event_name,
        channel           = channel,
        status            = status,
        attempt_number    = next_number,
        communication_log = attempt.communication_log,
        error_code        = error_code,
        error_message     = error_message,
    )


def _run_send(log, channel: str, attempt, next_number: int, counters: dict) -> None:
    """
    Attempt one send, update *counters* in-place, create the new attempt row.
    Extracted to avoid duplicating the try/except across normal retry and
    escalation loops.
    """
    from apps.communications.models import MessageStatus

    new_status   = AttemptStatus.FAILED
    err_code     = ''
    err_message  = ''

    try:
        _do_send(log, channel)
        new_status          = AttemptStatus.SENT
        counters['sent']   += 1
        log.status          = MessageStatus.SENT
        log.save(update_fields=['status', 'updated_at'])
        LearningService.record_success(attempt.member, channel)
        logger.info(
            'retry_sent',
            extra={
                'attempt_id':     attempt.pk,
                'attempt_number': next_number,
                'event_name':     attempt.event_name,
                'channel':        channel,
                'tenant_id':      str(attempt.tenant_id),
            },
        )
    except Exception as exc:
        counters['failed'] += 1
        err_code    = type(exc).__name__
        err_message = str(exc)
        LearningService.record_failure(attempt.member, channel)
        logger.warning(
            'retry_failed',
            extra={
                'attempt_id':     attempt.pk,
                'attempt_number': next_number,
                'event_name':     attempt.event_name,
                'channel':        channel,
                'tenant_id':      str(attempt.tenant_id),
                'error':          err_message,
            },
        )

    _create_attempt(attempt, channel, new_status, next_number,
                    error_code=err_code, error_message=err_message)


def process_retries(now=None) -> dict:
    """
    Run one pass of the retry engine across all RetryRules.

    Rules are processed high → normal → low priority so urgent events
    are retried before marketing / informational messages.

    Returns:
        {
            "processed":  int,  # total retry attempts made (normal + escalation)
            "sent":       int,  # succeeded
            "failed":     int,  # failed again
            "skipped":    int,  # not yet due, no adapter, or no next channel
            "escalated":  int,  # escalation attempts made
        }
    """
    if now is None:
        now = timezone.now()

    counters = {'sent': 0, 'failed': 0, 'skipped': 0, 'escalated': 0}

    # Exclude any attempt that already has a newer sibling for the same log.
    newer_attempt = MessageAttempt.objects.filter(
        communication_log_id=OuterRef('communication_log_id'),
        attempt_number__gt=OuterRef('attempt_number'),
    )

    # Process high-priority rules before normal before low.
    sorted_rules = sorted(
        RetryRule.objects.all(),
        key=lambda r: _PRIORITY_SORT.get(r.priority, 1),
    )

    for rule in sorted_rules:

        # ── 1. Normal retries (same channel) ───────────────────────────────
        eligible = (
            MessageAttempt.objects
            .filter(
                event_name=rule.event_name,
                channel=rule.channel,
                status=AttemptStatus.FAILED,
                attempt_number__lt=rule.max_attempts,
                communication_log__isnull=False,
            )
            .exclude(Exists(newer_attempt))
            .select_related('tenant', 'member', 'communication_log')
        )

        for attempt in eligible:
            cutoff = attempt.sent_at + timedelta(minutes=rule.retry_delay_minutes)
            if now < cutoff:
                counters['skipped'] += 1
                continue

            _run_send(
                attempt.communication_log,
                attempt.channel,
                attempt,
                attempt.attempt_number + 1,
                counters,
            )

        # ── 2. Escalation (next channel after retries exhausted) ────────────
        maxed_out = (
            MessageAttempt.objects
            .filter(
                event_name=rule.event_name,
                channel=rule.channel,
                status=AttemptStatus.FAILED,
                attempt_number=rule.max_attempts,
                communication_log__isnull=False,
            )
            .exclude(Exists(newer_attempt))
            .select_related('tenant', 'member', 'communication_log')
        )

        for attempt in maxed_out:
            cutoff = attempt.sent_at + timedelta(minutes=rule.retry_delay_minutes)
            if now < cutoff:
                counters['skipped'] += 1
                continue

            next_channel = _pick_escalation_channel(attempt.channel, attempt.member)
            if next_channel is None:
                counters['skipped'] += 1
                logger.info(
                    'escalation_no_channel',
                    extra={
                        'attempt_id': attempt.pk,
                        'channel':    attempt.channel,
                        'tenant_id':  str(attempt.tenant_id),
                    },
                )
                continue

            counters['escalated'] += 1
            _run_send(
                attempt.communication_log,
                next_channel,
                attempt,
                attempt.attempt_number + 1,
                counters,
            )

    return {
        'processed': counters['sent'] + counters['failed'],
        'sent':      counters['sent'],
        'failed':    counters['failed'],
        'skipped':   counters['skipped'],
        'escalated': counters['escalated'],
    }
