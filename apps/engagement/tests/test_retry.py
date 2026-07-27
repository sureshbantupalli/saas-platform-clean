from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.communications.models import Channel, CommunicationLog, MessageStatus
from apps.core.models import Tenant
from apps.engagement.models import AttemptStatus, MessageAttempt, RetryRule
from apps.engagement.retry_service import process_retries

EMAIL_SEND = 'apps.communications.adapters.email.EmailAdapter.send'


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _tenant(name='RetryGym'):
    return Tenant.objects.create(name=name, subdomain=name.lower().replace(' ', '-'))


def _log(tenant, channel=Channel.SMS, status=MessageStatus.FAILED):
    return CommunicationLog.base_objects.create(
        tenant=tenant,
        channel=channel,
        event_type='membership_expiring_7d',
        recipient='9876543210',
        message='Your membership expires soon.',
        subject='',
        status=status,
    )


def _attempt(tenant, log, status=AttemptStatus.FAILED, attempt_number=1, minutes_ago=90):
    obj = MessageAttempt.objects.create(
        tenant=tenant,
        event_name='membership_expiring_7d',
        channel=Channel.SMS,
        status=status,
        attempt_number=attempt_number,
        communication_log=log,
    )
    # Back-date sent_at to simulate elapsed time
    MessageAttempt.objects.filter(pk=obj.pk).update(
        sent_at=timezone.now() - timedelta(minutes=minutes_ago)
    )
    obj.refresh_from_db()
    return obj


def _rule(max_attempts=3, delay_minutes=60):
    return RetryRule.objects.create(
        event_name='membership_expiring_7d',
        channel=Channel.SMS,
        max_attempts=max_attempts,
        retry_delay_minutes=delay_minutes,
    )


ADAPTER_PATH = 'apps.communications.adapters.sms.SMSAdapter.send'


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class RetryEngineTests(TestCase):

    def setUp(self):
        self.tenant = _tenant()
        self.rule   = _rule(max_attempts=3, delay_minutes=60)

    # ── 1. Retry fires after delay has passed ────────────────────────────────

    def test_retry_happens_after_delay(self):
        log     = _log(self.tenant)
        attempt = _attempt(self.tenant, log, minutes_ago=90)  # 90 min > 60 min delay

        with patch(ADAPTER_PATH) as mock_send:
            result = process_retries(now=timezone.now())

        mock_send.assert_called_once_with(
            to=log.recipient, message=log.message, subject=''
        )
        self.assertEqual(result['sent'], 1)
        self.assertEqual(result['skipped'], 0)

        new_attempt = MessageAttempt.objects.exclude(pk=attempt.pk).get(
            communication_log=log
        )
        self.assertEqual(new_attempt.attempt_number, 2)
        self.assertEqual(new_attempt.status, AttemptStatus.SENT)

    # ── 2. Normal retry stops at max_attempts; escalation fires once ────────────

    def test_retry_stops_after_max_attempts(self):
        """
        attempt_number == max_attempts → normal retry (same channel) stops.
        Escalation fires once to the next channel (SMS → EMAIL).
        The escalated attempt is never normal-retried again.
        """
        log = _log(self.tenant)
        _attempt(self.tenant, log, attempt_number=3, minutes_ago=120)

        with patch(ADAPTER_PATH) as mock_sms, patch(EMAIL_SEND) as mock_email:
            result = process_retries(now=timezone.now())

        mock_sms.assert_not_called()      # normal retry stopped
        mock_email.assert_called_once()   # escalation fired
        self.assertEqual(result['escalated'], 1)

    # ── 3. Old attempt is never mutated; a new row is created ────────────────

    def test_new_attempt_row_created_original_unchanged(self):
        log     = _log(self.tenant)
        attempt = _attempt(self.tenant, log, minutes_ago=90)

        with patch(ADAPTER_PATH):
            process_retries(now=timezone.now())

        # Original row still failed
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, AttemptStatus.FAILED)
        self.assertEqual(attempt.attempt_number, 1)

        # New row exists with incremented number
        self.assertTrue(
            MessageAttempt.objects.filter(
                communication_log=log,
                attempt_number=2,
            ).exists()
        )

    # ── 4. Successful attempts are never retried ─────────────────────────────

    def test_success_not_retried(self):
        log = _log(self.tenant, status=MessageStatus.SENT)
        _attempt(self.tenant, log, status=AttemptStatus.SENT, minutes_ago=90)

        with patch(ADAPTER_PATH) as mock_send:
            result = process_retries(now=timezone.now())

        mock_send.assert_not_called()
        self.assertEqual(result['processed'], 0)

    # ── 5. Attempt not yet past delay is skipped ─────────────────────────────

    def test_skipped_when_delay_not_passed(self):
        log = _log(self.tenant)
        _attempt(self.tenant, log, minutes_ago=30)  # 30 min < 60 min delay

        with patch(ADAPTER_PATH) as mock_send:
            result = process_retries(now=timezone.now())

        mock_send.assert_not_called()
        self.assertEqual(result['skipped'], 1)
        self.assertEqual(result['processed'], 0)

    # ── 6. Only latest attempt in chain is retried (no double-retry) ─────────

    def test_only_latest_attempt_retried(self):
        log      = _log(self.tenant)
        attempt1 = _attempt(self.tenant, log, attempt_number=1, minutes_ago=120)
        # attempt2 supersedes attempt1 — attempt1 must NOT be retried again
        attempt2 = _attempt(self.tenant, log, attempt_number=2, minutes_ago=90)

        with patch(ADAPTER_PATH) as mock_send:
            process_retries(now=timezone.now())

        # Only one send, not two
        self.assertEqual(mock_send.call_count, 1)
        # The new attempt is attempt_number=3 (from attempt2, not 2 from attempt1)
        self.assertTrue(
            MessageAttempt.objects.filter(
                communication_log=log, attempt_number=3
            ).exists()
        )

    # ── 7. Adapter failure still creates a new failed attempt ────────────────

    def test_adapter_failure_creates_failed_attempt(self):
        log = _log(self.tenant)
        _attempt(self.tenant, log, minutes_ago=90)

        with patch(ADAPTER_PATH, side_effect=RuntimeError('gateway down')):
            result = process_retries(now=timezone.now())

        self.assertEqual(result['failed'], 1)
        self.assertEqual(result['sent'], 0)
        new_attempt = MessageAttempt.objects.filter(
            communication_log=log, attempt_number=2
        ).first()
        self.assertIsNotNone(new_attempt)
        self.assertEqual(new_attempt.status, AttemptStatus.FAILED)
