from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.authority.models import Role
from apps.communications.models import Channel, CommunicationLog, MessageStatus
from apps.core.models import Tenant
from apps.engagement.learning_service import EngagementService, LearningService
from apps.engagement.models import AttemptStatus, MemberEngagementScore, MessageAttempt, RetryRule
from apps.engagement.retry_service import process_retries
from members.models import Member


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _tenant(name='EscalationGym'):
    return Tenant.objects.create(name=name, subdomain=name.lower().replace(' ', '-'))


def _member(tenant, first='Test', last='Member'):
    user = User.objects.create_user(
        email=f'{first.lower()}@esctest.com',
        password='pass',
        tenant=tenant,
        role=Role.objects.create(tenant=tenant, name=f'Role-{first}'),
    )
    return Member.objects.create(
        tenant=tenant, created_by=user,
        first_name=first, last_name=last,
        email=f'{first.lower()}@esctest.com', phone='9000000000',
    )


def _log(tenant, channel=Channel.WHATSAPP, status=MessageStatus.FAILED):
    return CommunicationLog.base_objects.create(
        tenant=tenant,
        channel=channel,
        event_type='membership_expiring_7d',
        recipient='9876543210',
        message='Your membership expires soon.',
        subject='',
        status=status,
    )


def _attempt(tenant, log, member=None, channel=Channel.WHATSAPP,
             status=AttemptStatus.FAILED, attempt_number=1, minutes_ago=90):
    obj = MessageAttempt.objects.create(
        tenant=tenant,
        member=member,
        event_name='membership_expiring_7d',
        channel=channel,
        status=status,
        attempt_number=attempt_number,
        communication_log=log,
    )
    MessageAttempt.objects.filter(pk=obj.pk).update(
        sent_at=timezone.now() - timedelta(minutes=minutes_ago)
    )
    obj.refresh_from_db()
    return obj


def _rule(channel=Channel.WHATSAPP, max_attempts=2, delay_minutes=60):
    return RetryRule.objects.create(
        event_name='membership_expiring_7d',
        channel=channel,
        max_attempts=max_attempts,
        retry_delay_minutes=delay_minutes,
    )


SMS_SEND   = 'apps.communications.adapters.sms.SMSAdapter.send'
EMAIL_SEND = 'apps.communications.adapters.email.EmailAdapter.send'
WA_SEND    = 'apps.communications.adapters.whatsapp.WhatsAppAdapter.send'


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class EscalationTests(TestCase):
    """Channel escalation: WhatsApp → SMS → Email after retries exhausted."""

    def setUp(self):
        self.tenant = _tenant()
        self.member = _member(self.tenant)
        self.rule   = _rule(channel=Channel.WHATSAPP, max_attempts=2)

    # ── 1. Channel switches after all retries fail ───────────────────────────

    def test_channel_switch_after_failures(self):
        log     = _log(self.tenant, channel=Channel.WHATSAPP)
        attempt = _attempt(self.tenant, log, member=self.member,
                           channel=Channel.WHATSAPP, attempt_number=2,  # == max_attempts
                           minutes_ago=90)

        with patch(SMS_SEND) as mock_sms:
            result = process_retries(now=timezone.now())

        mock_sms.assert_called_once()
        self.assertEqual(result['escalated'], 1)

        escalated_attempt = MessageAttempt.objects.filter(
            communication_log=log, attempt_number=3
        ).first()
        self.assertIsNotNone(escalated_attempt)
        self.assertEqual(escalated_attempt.channel, Channel.SMS)
        self.assertEqual(escalated_attempt.status,  AttemptStatus.SENT)

    # ── 2. EMAIL is the terminal escalation (no further after EMAIL) ─────────

    def test_no_escalation_from_email(self):
        email_rule = RetryRule.objects.create(
            event_name='membership_expiring_7d',
            channel=Channel.EMAIL,
            max_attempts=2,
            retry_delay_minutes=60,
        )
        log     = _log(self.tenant, channel=Channel.EMAIL)
        attempt = _attempt(self.tenant, log, member=self.member,
                           channel=Channel.EMAIL, attempt_number=2, minutes_ago=90)

        with patch(SMS_SEND) as mock_sms, patch(EMAIL_SEND) as mock_email:
            result = process_retries(now=timezone.now())

        # No further escalation beyond EMAIL
        mock_sms.assert_not_called()
        self.assertEqual(result['escalated'], 0)
        self.assertGreaterEqual(result['skipped'], 1)


class LearningServiceTests(TestCase):
    """LearningService updates MemberEngagementScore correctly."""

    def setUp(self):
        self.tenant = _tenant('LearningGym')
        self.member = _member(self.tenant, first='Learn')

    # ── 3. Success increments success_count ──────────────────────────────────

    def test_success_increases_score(self):
        LearningService.record_success(self.member, Channel.SMS)
        LearningService.record_success(self.member, Channel.SMS)

        score = MemberEngagementScore.objects.get(member=self.member)
        self.assertEqual(score.success_count, 2)
        self.assertIsNotNone(score.last_engaged_at)

    # ── 4. preferred_channel updated on success ──────────────────────────────

    def test_preferred_channel_updates(self):
        LearningService.record_success(self.member, Channel.EMAIL)

        score = MemberEngagementScore.objects.get(member=self.member)
        self.assertEqual(score.preferred_channel, Channel.EMAIL)

    # ── 5. Failure increments failure_count ──────────────────────────────────

    def test_failure_increases_failure_count(self):
        LearningService.record_failure(self.member, Channel.WHATSAPP)
        LearningService.record_failure(self.member, Channel.WHATSAPP)

        score = MemberEngagementScore.objects.get(member=self.member)
        self.assertEqual(score.failure_count, 2)
        # preferred_channel not updated by failure
        self.assertEqual(score.preferred_channel, '')

    # ── 6. No-op when member is None (no crash) ──────────────────────────────

    def test_no_op_when_member_none(self):
        LearningService.record_success(None, Channel.SMS)
        LearningService.record_failure(None, Channel.SMS)
        self.assertEqual(MemberEngagementScore.objects.count(), 0)


class EngagementServiceTests(TestCase):
    """EngagementService.get_best_channel returns the learned preference."""

    def setUp(self):
        self.tenant = _tenant('EngGym')
        self.member = _member(self.tenant, first='Eng')

    # ── 7. Returns preferred channel when score exists ────────────────────────

    def test_learning_affects_future_sends(self):
        MemberEngagementScore.objects.create(
            member=self.member,
            preferred_channel=Channel.SMS,
            success_count=3,
        )
        channel = EngagementService.get_best_channel(self.member)
        self.assertEqual(channel, Channel.SMS)

    # ── 8. Returns None when no score exists ──────────────────────────────────

    def test_returns_none_when_no_score(self):
        channel = EngagementService.get_best_channel(self.member)
        self.assertIsNone(channel)

    # ── 9. Preferred channel used over default escalation order ──────────────

    def test_preferred_channel_overrides_escalation_order(self):
        """
        Member prefers EMAIL.  Escalating from WhatsApp should go to EMAIL
        (not SMS as the hard-coded order would suggest).
        """
        rule = RetryRule.objects.create(
            event_name='membership_expiring_7d',
            channel=Channel.WHATSAPP,
            max_attempts=2,
            retry_delay_minutes=60,
        )
        MemberEngagementScore.objects.create(
            member=self.member,
            preferred_channel=Channel.EMAIL,
        )
        log     = _log(self.tenant, channel=Channel.WHATSAPP)
        attempt = _attempt(self.tenant, log, member=self.member,
                           channel=Channel.WHATSAPP, attempt_number=2, minutes_ago=90)

        with patch(EMAIL_SEND) as mock_email, patch(SMS_SEND) as mock_sms:
            process_retries(now=timezone.now())

        mock_email.assert_called_once()
        mock_sms.assert_not_called()

        escalated_attempt = MessageAttempt.objects.filter(
            communication_log=log, attempt_number=3
        ).first()
        self.assertEqual(escalated_attempt.channel, Channel.EMAIL)
