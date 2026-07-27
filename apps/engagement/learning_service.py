"""
Learning service — rule-based channel preference learning.

LearningService
    record_success(member, channel)  — increments success_count; updates
        preferred_channel (all-time) and last_success_channel / last_success_at
        (recency signal).
    record_failure(member, channel)  — increments failure_count only.

EngagementService
    get_best_channel(member) → str | None
        Recency-first strategy:
          1. If last_success_at is within RECENCY_THRESHOLD_DAYS → return last_success_channel.
          2. Else → return preferred_channel (historical aggregate).
          3. If neither → return None (caller uses the TriggerRule default).

Both services silently swallow exceptions so learning failures never interrupt
delivery.  No ML — pure rule-based counting with a recency window.
"""
import logging
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

# Success within this window overrides the historical preferred_channel.
RECENCY_THRESHOLD_DAYS = 30


class LearningService:

    @staticmethod
    def record_success(member, channel: str) -> None:
        if member is None:
            return
        try:
            from apps.engagement.models import MemberEngagementScore
            score, _ = MemberEngagementScore.objects.get_or_create(member=member)
            now = timezone.now()
            score.success_count        += 1
            score.preferred_channel     = channel   # all-time winner
            score.last_success_channel  = channel   # recency signal
            score.last_success_at       = now
            score.last_engaged_at       = now
            score.save(update_fields=[
                'success_count', 'preferred_channel',
                'last_success_channel', 'last_success_at', 'last_engaged_at',
            ])
        except Exception as exc:
            logger.warning('learning_record_success_failed', extra={'error': str(exc)})

    @staticmethod
    def record_failure(member, channel: str) -> None:
        if member is None:
            return
        try:
            from apps.engagement.models import MemberEngagementScore
            score, _ = MemberEngagementScore.objects.get_or_create(member=member)
            score.failure_count += 1
            score.save(update_fields=['failure_count'])
        except Exception as exc:
            logger.warning('learning_record_failure_failed', extra={'error': str(exc)})


class EngagementService:

    @staticmethod
    def get_best_channel(member) -> str | None:
        """
        Recency-first channel selection.

        Returns the most recently successful channel if it falls within
        RECENCY_THRESHOLD_DAYS; otherwise the all-time preferred channel;
        otherwise None (caller falls back to the TriggerRule default or the
        hard-coded escalation order).
        """
        if member is None:
            return None
        try:
            from apps.engagement.models import MemberEngagementScore
            score = MemberEngagementScore.objects.get(member=member)

            # Recency wins: if member responded recently, trust that channel
            if score.last_success_at and score.last_success_channel:
                threshold = timezone.now() - timedelta(days=RECENCY_THRESHOLD_DAYS)
                if score.last_success_at >= threshold:
                    return score.last_success_channel

            # Historical fallback: all-time preferred (may be stale, but better than nothing)
            return score.preferred_channel or None
        except Exception:
            return None
