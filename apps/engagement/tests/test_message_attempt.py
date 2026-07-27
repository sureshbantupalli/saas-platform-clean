from unittest.mock import patch

from django.test import TestCase

from apps.accounts.models import User
from apps.authority.models import Role
from apps.communications.models import Channel, MessageTemplate
from apps.communications.services.communication_service import send_message
from apps.core.models import Tenant
from apps.engagement.models import AttemptStatus, MessageAttempt


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _tenant(name='EngagementGym'):
    return Tenant.objects.create(name=name, subdomain=name.lower().replace(' ', '-'))


def _template(tenant, channel=Channel.SMS):
    return MessageTemplate.base_objects.create(
        tenant=tenant,
        name='Test SMS',
        channel=channel,
        content='Hi {{member_name}}, your membership expires soon.',
        is_active=True,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class MessageAttemptTrackingTests(TestCase):

    def setUp(self):
        self.tenant   = _tenant()
        self.template = _template(self.tenant)

    # ── 1. Successful send writes a 'sent' attempt ───────────────────────────

    def test_records_sent_on_success(self):
        ctx = {'member_name': 'Priya', 'phone': '9876543210'}
        with patch('apps.communications.adapters.sms.SMSAdapter.send'):
            send_message(self.template, ctx, self.tenant, event_type='membership_expiring_7d')

        attempt = MessageAttempt.objects.filter(tenant=self.tenant).first()
        self.assertIsNotNone(attempt)
        self.assertEqual(attempt.status,     AttemptStatus.SENT)
        self.assertEqual(attempt.channel,    Channel.SMS)
        self.assertEqual(attempt.event_name, 'membership_expiring_7d')

    # ── 2. Adapter error writes a 'failed' attempt ──────────────────────────

    def test_records_failed_on_adapter_error(self):
        ctx = {'member_name': 'Ravi', 'phone': '9123456780'}
        with patch('apps.communications.adapters.sms.SMSAdapter.send',
                   side_effect=RuntimeError('gateway timeout')):
            send_message(self.template, ctx, self.tenant, event_type='membership_expiring_3d')

        attempt = MessageAttempt.objects.filter(tenant=self.tenant).first()
        self.assertIsNotNone(attempt)
        self.assertEqual(attempt.status,     AttemptStatus.FAILED)
        self.assertEqual(attempt.event_name, 'membership_expiring_3d')

    # ── 3. No attempt for early exits (no recipient) ────────────────────────

    def test_no_attempt_when_no_recipient(self):
        ctx = {'member_name': 'Ghost'}   # no phone field
        with patch('apps.communications.adapters.sms.SMSAdapter.send') as mock_send:
            send_message(self.template, ctx, self.tenant, event_type='membership_expiring_1d')

        mock_send.assert_not_called()
        self.assertEqual(MessageAttempt.objects.filter(tenant=self.tenant).count(), 0)

    # ── 4. Tracking failure never breaks message delivery ───────────────────

    def test_tracking_failure_does_not_raise(self):
        ctx = {'member_name': 'Sana', 'phone': '9000000001'}
        with patch('apps.communications.adapters.sms.SMSAdapter.send'):
            with patch('apps.engagement.models.MessageAttempt.objects') as mock_mgr:
                mock_mgr.create.side_effect = Exception('DB down')
                # Should not raise — message delivery must complete regardless
                log = send_message(self.template, ctx, self.tenant, event_type='test_event')

        from apps.communications.models import MessageStatus
        self.assertEqual(log.status, MessageStatus.SENT)
