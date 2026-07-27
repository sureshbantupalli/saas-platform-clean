"""
Tests for Phase 4.2 improvements:
  - MessageAttempt error_code / error_message fields
  - RetryRule priority-aware processing order
  - MemberEngagementScore recency signal (last_success_channel / last_success_at)
"""
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.authority.models import Role
from apps.communications.models import Channel, CommunicationLog, MessageStatus, MessageTemplate
from apps.communications.services.communication_service import send_message
from apps.core.models import Tenant
from apps.engagement.learning_service import EngagementService, LearningService, RECENCY_THRESHOLD_DAYS
from apps.engagement.models import (
    AttemptStatus, MemberEngagementScore, MessageAttempt, RetryPriority, RetryRule,
)
from apps.engagement.retry_service import process_retries
from members.models import Member


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _tenant(name='ImprovGym'):
    return Tenant.objects.create(name=name, subdomain=name.lower().replace(' ', '-'))


def _member(tenant, first='ImprovMember'):
    user = User.objects.create_user(
        email=f'{first.lower()}@improv.test',
        password='pass',
        tenant=tenant,
        role=Role.objects.create(tenant=tenant, name=f'Role-{first}'),
    )
    return Member.objects.create(
        tenant=tenant, created_by=user,
        first_name=first, last_name='Test',
        email=f'{first.lower()}@improv.test', phone='9100000000',
    )


def _template(tenant, channel=Channel.SMS):
    return MessageTemplate.base_objects.create(
        tenant=tenant, name='ImprovTemplate',
        channel=channel, content='Hi {{member_name}}.', is_active=True,
    )


def _log(tenant, channel=Channel.WHATSAPP, status=MessageStatus.FAILED):
    return CommunicationLog.base_objects.create(
        tenant=tenant, channel=channel,
        event_type='test_event', recipient='9876543210',
        message='Test message.', subject='', status=status,
    )


def _attempt(tenant, log, member=None, channel=Channel.WHATSAPP,
             status=AttemptStatus.FAILED, attempt_number=1, minutes_ago=90):
    obj = MessageAttempt.objects.create(
        tenant=tenant, member=member,
        event_name='test_event', channel=channel,
        status=status, attempt_number=attempt_number,
        communication_log=log,
    )
    MessageAttempt.objects.filter(pk=obj.pk).update(
        sent_at=timezone.now() - timedelta(minutes=minutes_ago)
    )
    obj.refresh_from_db()
    return obj


SMS_SEND   = 'apps.communications.adapters.sms.SMSAdapter.send'
EMAIL_SEND = 'apps.communications.adapters.email.EmailAdapter.send'
WA_SEND    = 'apps.communications.adapters.whatsapp.WhatsAppAdapter.send'


# ===========================================================================
# 1. Error fields on MessageAttempt
# ===========================================================================

class ErrorFieldTests(TestCase):

    def setUp(self):
        self.tenant   = _tenant('ErrorGym')
        self.template = _template(self.tenant)

    # ── error_code and error_message stored when adapter raises ─────────────

    def test_error_fields_populated_on_failure(self):
        ctx = {'member_name': 'Raj', 'phone': '9000000001'}
        with patch(SMS_SEND, side_effect=RuntimeError('carrier_rejected')):
            send_message(self.template, ctx, self.tenant, event_type='test_event')

        attempt = MessageAttempt.objects.filter(tenant=self.tenant).first()
        self.assertIsNotNone(attempt)
        self.assertEqual(attempt.status,        AttemptStatus.FAILED)
        self.assertEqual(attempt.error_code,    'RuntimeError')
        self.assertEqual(attempt.error_message, 'carrier_rejected')

    # ── error fields are empty on success ────────────────────────────────────

    def test_error_fields_empty_on_success(self):
        ctx = {'member_name': 'Priya', 'phone': '9000000002'}
        with patch(SMS_SEND):
            send_message(self.template, ctx, self.tenant, event_type='test_event')

        attempt = MessageAttempt.objects.filter(tenant=self.tenant).first()
        self.assertEqual(attempt.status,        AttemptStatus.SENT)
        self.assertEqual(attempt.error_code,    '')
        self.assertEqual(attempt.error_message, '')

    # ── retry failure also captures error fields ──────────────────────────────

    def test_retry_failure_stores_error_fields(self):
        log     = _log(self.tenant, channel=Channel.WHATSAPP)
        attempt = _attempt(self.tenant, log, channel=Channel.WHATSAPP, minutes_ago=90)
        RetryRule.objects.create(
            event_name='test_event', channel=Channel.WHATSAPP,
            max_attempts=3, retry_delay_minutes=60,
        )

        with patch(WA_SEND, side_effect=ConnectionError('template_rejected')):
            process_retries(now=timezone.now())

        new_attempt = MessageAttempt.objects.filter(
            communication_log=log, attempt_number=2
        ).first()
        self.assertIsNotNone(new_attempt)
        self.assertEqual(new_attempt.error_code,    'ConnectionError')
        self.assertEqual(new_attempt.error_message, 'template_rejected')

    # ── retry success has empty error fields ──────────────────────────────────

    def test_retry_success_has_empty_error_fields(self):
        log     = _log(self.tenant, channel=Channel.WHATSAPP)
        attempt = _attempt(self.tenant, log, channel=Channel.WHATSAPP, minutes_ago=90)
        RetryRule.objects.create(
            event_name='test_event', channel=Channel.WHATSAPP,
            max_attempts=3, retry_delay_minutes=60,
        )

        with patch(WA_SEND):
            process_retries(now=timezone.now())

        new_attempt = MessageAttempt.objects.filter(
            communication_log=log, attempt_number=2
        ).first()
        self.assertEqual(new_attempt.error_code,    '')
        self.assertEqual(new_attempt.error_message, '')


# ===========================================================================
# 2. Priority-aware RetryRule ordering
# ===========================================================================

class PriorityOrderingTests(TestCase):

    def setUp(self):
        self.tenant = _tenant('PriorityGym')

    # ── high-priority rule is processed before low-priority ──────────────────

    def test_priority_high_rules_processed_first(self):
        """
        High-priority messages should be retried before low-priority ones.
        We verify this by checking that the high-priority attempt's new row
        has a lower (earlier) created attempt_number context than low-priority.

        Simpler verification: both succeed — just confirm high processed.
        """
        RetryRule.objects.create(
            event_name='high_event', channel=Channel.SMS,
            max_attempts=3, retry_delay_minutes=60, priority=RetryPriority.HIGH,
        )
        RetryRule.objects.create(
            event_name='low_event', channel=Channel.SMS,
            max_attempts=3, retry_delay_minutes=60, priority=RetryPriority.LOW,
        )

        log_high = CommunicationLog.base_objects.create(
            tenant=self.tenant, channel=Channel.SMS, event_type='high_event',
            recipient='9111111111', message='High msg.', subject='', status=MessageStatus.FAILED,
        )
        log_low  = CommunicationLog.base_objects.create(
            tenant=self.tenant, channel=Channel.SMS, event_type='low_event',
            recipient='9222222222', message='Low msg.', subject='', status=MessageStatus.FAILED,
        )

        for log, event in [(log_high, 'high_event'), (log_low, 'low_event')]:
            obj = MessageAttempt.objects.create(
                tenant=self.tenant, event_name=event, channel=Channel.SMS,
                status=AttemptStatus.FAILED, attempt_number=1, communication_log=log,
            )
            MessageAttempt.objects.filter(pk=obj.pk).update(
                sent_at=timezone.now() - timedelta(minutes=90)
            )

        call_order = []

        original_send = __import__(
            'apps.communications.adapters.sms', fromlist=['SMSAdapter']
        ).SMSAdapter.send

        def tracking_send(self_adapter, to, message, subject='', text=''):
            call_order.append(to)

        with patch(SMS_SEND, tracking_send):
            process_retries(now=timezone.now())

        # high_event recipient should appear before low_event recipient
        self.assertIn('9111111111', call_order)
        self.assertIn('9222222222', call_order)
        self.assertLess(call_order.index('9111111111'), call_order.index('9222222222'))

    # ── RetryPriority choices exist ───────────────────────────────────────────

    def test_retry_priority_choices(self):
        rule = RetryRule.objects.create(
            event_name='prio_test', channel=Channel.EMAIL,
            max_attempts=2, priority=RetryPriority.HIGH,
        )
        self.assertEqual(rule.priority, 'high')

        rule.priority = RetryPriority.LOW
        rule.save()
        rule.refresh_from_db()
        self.assertEqual(rule.priority, 'low')


# ===========================================================================
# 3. Recency-aware channel selection
# ===========================================================================

class RecencyLearningTests(TestCase):

    def setUp(self):
        self.tenant = _tenant('RecencyGym')
        self.member = _member(self.tenant, first='Recency')

    # ── record_success sets both preferred_channel and recency fields ─────────

    def test_record_success_updates_recency_fields(self):
        LearningService.record_success(self.member, Channel.EMAIL)

        score = MemberEngagementScore.objects.get(member=self.member)
        self.assertEqual(score.preferred_channel,    Channel.EMAIL)
        self.assertEqual(score.last_success_channel, Channel.EMAIL)
        self.assertIsNotNone(score.last_success_at)

    # ── recent success overrides historical preferred_channel ─────────────────

    def test_recent_success_overrides_historical(self):
        """
        Member's historical preferred is SMS (older), but recently succeeded
        on EMAIL — get_best_channel should return EMAIL.
        """
        MemberEngagementScore.objects.create(
            member=self.member,
            preferred_channel=Channel.SMS,         # old history
            last_success_channel=Channel.EMAIL,    # recent win
            last_success_at=timezone.now() - timedelta(days=5),
        )
        channel = EngagementService.get_best_channel(self.member)
        self.assertEqual(channel, Channel.EMAIL)

    # ── stale recent success falls back to preferred_channel ─────────────────

    def test_stale_success_falls_back_to_preferred(self):
        """
        last_success_at older than RECENCY_THRESHOLD_DAYS → disregard recency,
        fall back to preferred_channel.
        """
        stale_at = timezone.now() - timedelta(days=RECENCY_THRESHOLD_DAYS + 5)
        MemberEngagementScore.objects.create(
            member=self.member,
            preferred_channel=Channel.SMS,
            last_success_channel=Channel.EMAIL,
            last_success_at=stale_at,
        )
        channel = EngagementService.get_best_channel(self.member)
        self.assertEqual(channel, Channel.SMS)

    # ── no score → returns None ───────────────────────────────────────────────

    def test_no_score_returns_none(self):
        self.assertIsNone(EngagementService.get_best_channel(self.member))

    # ── recency controls escalation channel selection ─────────────────────────

    def test_recency_controls_escalation_channel(self):
        """
        Member recently succeeded on EMAIL.  Escalating from WhatsApp should
        pick EMAIL (recency preference) rather than SMS (hard-coded WA → SMS order).
        """
        MemberEngagementScore.objects.create(
            member=self.member,
            preferred_channel=Channel.SMS,
            last_success_channel=Channel.EMAIL,
            last_success_at=timezone.now() - timedelta(days=2),
        )
        RetryRule.objects.create(
            event_name='test_event', channel=Channel.WHATSAPP,
            max_attempts=2, retry_delay_minutes=60,
        )
        log     = _log(self.tenant, channel=Channel.WHATSAPP)
        attempt = _attempt(self.tenant, log, member=self.member,
                           channel=Channel.WHATSAPP, attempt_number=2, minutes_ago=90)

        with patch(EMAIL_SEND) as mock_email, patch(SMS_SEND) as mock_sms:
            process_retries(now=timezone.now())

        mock_email.assert_called_once()
        mock_sms.assert_not_called()

        escalated = MessageAttempt.objects.filter(
            communication_log=log, attempt_number=3
        ).first()
        self.assertEqual(escalated.channel, Channel.EMAIL)
