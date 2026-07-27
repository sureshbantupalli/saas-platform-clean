"""
Integration tests for audit logging across payment, role, branding, and vocabulary flows.

Design: each test class is self-contained — it sets up its own tenant/user
and asserts audit log entries exist with the correct shape.

Key Django helper used for payment tests:
    self.captureOnCommitCallbacks(execute=True)  — fires on_commit callbacks
    inline so TestCase (which wraps everything in a transaction) still runs them.
"""
from decimal import Decimal
from unittest import mock

from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory, TestCase

from apps.audit.models import AuditSource, SettingsAuditLog
from apps.audit.services import safe_log_change
from apps.core.models import Branch, Tenant
from apps.payments.models import Payment, PaymentStatus
from apps.payments.services.payment_service import PaymentService


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_tenant(n):
    return Tenant.objects.create(name=f'IntAuditGym{n}', subdomain=f'intauditgym{n}')


def _make_branch(tenant):
    return Branch.objects.create(tenant=tenant, name='Main', is_active=True)


def _make_user(tenant):
    from apps.accounts.models import User
    from apps.authority.models import Role
    role = Role.base_objects.create(tenant=tenant, name='Admin')
    return User.objects.create_user(
        email=f'admin@{tenant.subdomain}.com',
        password='x',
        tenant=tenant,
        role=role,
    )


def _make_request(factory, method, url, user, tenant, data=None):
    """Create a fake request with session + messages middleware attached."""
    make = getattr(factory, method)
    request = make(url, data or {})
    request.user   = user
    request.tenant = tenant
    setattr(request, 'session', {})
    setattr(request, '_messages', FallbackStorage(request))
    return request


_ctr = [0]
def _uid():
    _ctr[0] += 1
    return _ctr[0]


# ── Payment audit tests ───────────────────────────────────────────────────────

class PaymentAuditTests(TestCase):

    def setUp(self):
        n = _uid()
        self.tenant = _make_tenant(n)
        self.branch = _make_branch(self.tenant)
        self.user   = _make_user(self.tenant)

    def _payment(self):
        return PaymentService.create_payment(
            tenant=self.tenant,
            amount=Decimal('500'),
            purpose='membership',
        )

    def test_payment_success_logged(self):
        """mark_payment_success writes an audit log after commit."""
        payment = self._payment()
        with self.captureOnCommitCallbacks(execute=True):
            PaymentService.mark_payment_success(payment, gateway_payment_id='gw_001')

        log = SettingsAuditLog.objects.filter(
            tenant=self.tenant, module='payments', field_name='status',
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.new_value, str(PaymentStatus.SUCCESS))
        self.assertEqual(log.source, AuditSource.SYSTEM)
        self.assertIsNone(log.user)
        self.assertIn('payment_id', log.metadata)
        # amount must NOT be in metadata — store a reference, not the financial value
        self.assertNotIn('amount', log.metadata)

    def test_payment_failed_logged(self):
        payment = self._payment()
        with self.captureOnCommitCallbacks(execute=True):
            PaymentService.mark_payment_failed(payment, reason='test_failure')

        log = SettingsAuditLog.objects.filter(
            tenant=self.tenant, module='payments', field_name='status',
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.new_value, str(PaymentStatus.FAILED))
        self.assertEqual(log.source, AuditSource.SYSTEM)
        self.assertEqual(log.metadata.get('reason'), 'test_failure')

    def test_no_log_on_idempotent_success(self):
        """Calling mark_payment_success on an already-SUCCESS payment must not create a new log."""
        payment = self._payment()
        with self.captureOnCommitCallbacks(execute=True):
            PaymentService.mark_payment_success(payment)  # first — state changes
        count_after_first = SettingsAuditLog.objects.filter(
            tenant=self.tenant, module='payments',
        ).count()

        with self.captureOnCommitCallbacks(execute=True):
            PaymentService.mark_payment_success(payment)  # second — idempotent, no change
        self.assertEqual(
            SettingsAuditLog.objects.filter(tenant=self.tenant, module='payments').count(),
            count_after_first,
        )

    def test_logging_failure_does_not_break_payment_flow(self):
        """If audit logging fails, the payment state change must still succeed."""
        payment = self._payment()

        with mock.patch('apps.audit.services.log_change', side_effect=Exception('audit down')):
            with self.captureOnCommitCallbacks(execute=True):
                PaymentService.mark_payment_success(payment, gateway_payment_id='gw_x')

        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.SUCCESS)
        # No log created because log_change raised, but no exception propagated
        self.assertEqual(
            SettingsAuditLog.objects.filter(tenant=self.tenant, module='payments').count(), 0,
        )


# ── Role audit tests ──────────────────────────────────────────────────────────

class RoleAuditTests(TestCase):

    def setUp(self):
        n = _uid()
        self.tenant  = _make_tenant(n)
        self.user    = _make_user(self.tenant)
        self.factory = RequestFactory()

    def _post(self, view_func, url, data):
        from apps.settings.roles.views import role_create
        request = _make_request(self.factory, 'post', url, self.user, self.tenant, data)
        return view_func(request)

    def test_role_create_logged(self):
        from apps.settings.roles.views import role_create
        self._post(role_create, '/settings/roles/create/', {'name': 'Manager'})

        log = SettingsAuditLog.objects.filter(
            tenant=self.tenant, module='roles', action='create',
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.field_name, 'role')
        self.assertEqual(log.new_value, 'Manager')
        self.assertEqual(log.source, AuditSource.USER)
        self.assertEqual(log.user, self.user)

    def test_role_delete_logged(self):
        from apps.settings.roles.models import Role
        from apps.settings.roles.views import role_delete

        role = Role.base_objects.create(tenant=self.tenant, name='Janitor')
        request = _make_request(
            self.factory, 'post', f'/settings/roles/{role.pk}/delete/',
            self.user, self.tenant,
        )
        role_delete(request, role_id=role.pk)

        log = SettingsAuditLog.objects.filter(
            tenant=self.tenant, module='roles', action='delete',
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.old_value, 'Janitor')
        self.assertEqual(log.source, AuditSource.USER)

    def test_role_edit_no_log_when_name_unchanged(self):
        from apps.settings.roles.models import Role
        from apps.settings.roles.views import role_edit

        role = Role.base_objects.create(tenant=self.tenant, name='Trainer')
        request = _make_request(
            self.factory, 'post', f'/settings/roles/{role.pk}/edit/',
            self.user, self.tenant,
            data={'name': 'Trainer'},  # same name — no change
        )
        role_edit(request, role_id=role.pk)

        self.assertEqual(
            SettingsAuditLog.objects.filter(tenant=self.tenant, module='roles', action='update').count(),
            0,
        )

    def test_role_edit_logged_on_name_change(self):
        from apps.settings.roles.models import Role
        from apps.settings.roles.views import role_edit

        role = Role.base_objects.create(tenant=self.tenant, name='OldName')
        request = _make_request(
            self.factory, 'post', f'/settings/roles/{role.pk}/edit/',
            self.user, self.tenant,
            data={'name': 'NewName'},
        )
        role_edit(request, role_id=role.pk)

        log = SettingsAuditLog.objects.filter(
            tenant=self.tenant, module='roles', action='update', field_name='name',
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.old_value, 'OldName')
        self.assertEqual(log.new_value, 'NewName')


# ── Vocabulary audit tests ────────────────────────────────────────────────────

class VocabularyAuditTests(TestCase):

    def setUp(self):
        n = _uid()
        self.tenant  = _make_tenant(n)
        self.user    = _make_user(self.tenant)
        self.factory = RequestFactory()

    def test_vocabulary_change_logged(self):
        from apps.settings.vocabulary.views import vocabulary_settings

        request = _make_request(
            self.factory, 'post', '/settings/vocabulary/',
            self.user, self.tenant,
            data={'member_singular': 'Athlete', 'member_plural': 'Athletes'},
        )
        vocabulary_settings(request)

        log = SettingsAuditLog.objects.filter(
            tenant=self.tenant, module='vocabulary', field_name='member.singular',
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.new_value, 'Athlete')
        self.assertEqual(log.source, AuditSource.USER)

    def test_no_log_when_vocabulary_unchanged(self):
        from apps.settings.vocabulary.views import vocabulary_settings

        # Submit the defaults — no overrides computed, no log
        request = _make_request(
            self.factory, 'post', '/settings/vocabulary/',
            self.user, self.tenant,
            data={},  # empty → no overrides
        )
        vocabulary_settings(request)

        self.assertEqual(
            SettingsAuditLog.objects.filter(tenant=self.tenant, module='vocabulary').count(),
            0,
        )


# ── Safe wrapper contract tests ───────────────────────────────────────────────

class SafeLogChangeContractTests(TestCase):

    def setUp(self):
        self.tenant = _make_tenant(_uid())

    def test_safe_log_change_never_raises(self):
        """safe_log_change must not propagate any exception, ever."""
        with mock.patch('apps.audit.services.log_change', side_effect=RuntimeError('boom')):
            try:
                safe_log_change(
                    tenant=self.tenant,
                    module='settings',
                    action='update',
                    source='system',
                )
            except Exception as exc:
                self.fail(f'safe_log_change propagated: {exc}')

    def test_safe_log_change_writes_log_on_success(self):
        safe_log_change(
            tenant=self.tenant,
            module='settings',
            action='update',
            source='user',
            field_name='test_field',
            old_value='a',
            new_value='b',
        )
        log = SettingsAuditLog.objects.get(tenant=self.tenant)
        self.assertEqual(log.old_value, 'a')
        self.assertEqual(log.new_value, 'b')
        self.assertEqual(log.source, 'user')


# ── Financial field guard ─────────────────────────────────────────────────────

class FinancialFieldGuardTests(TestCase):
    """
    log_change must reject writes that store financial values instead of references.
    These tests prove the guard is active and that safe_log_change absorbs the error.
    """

    def setUp(self):
        self.tenant = _make_tenant(_uid())

    def _ok_kwargs(self):
        return dict(
            tenant=self.tenant,
            module='payments',
            action='update',
            source='system',
            field_name='status',
            old_value='pending',
            new_value='paid',
        )

    def test_financial_field_name_raises(self):
        from apps.audit.services import log_change
        for bad_field in ('amount', 'gst_amount', 'gst_rate', 'refund_amount'):
            with self.subTest(field=bad_field):
                with self.assertRaises(ValueError) as ctx:
                    log_change(
                        tenant=self.tenant, module='payments',
                        action='update', source='system',
                        field_name=bad_field,
                        new_value='100.00',
                    )
                self.assertIn(bad_field, str(ctx.exception))
                self.assertIn('reference', str(ctx.exception))

    def test_financial_metadata_key_raises(self):
        from apps.audit.services import log_change
        for bad_key in ('amount', 'gst_amount', 'gst_rate', 'refund_amount'):
            with self.subTest(key=bad_key):
                with self.assertRaises(ValueError):
                    log_change(
                        **self._ok_kwargs(),
                        metadata={bad_key: '100.00', 'payment_id': 'some-uuid'},
                    )

    def test_reference_metadata_allowed(self):
        """payment_id and other non-financial keys must pass through cleanly."""
        from apps.audit.services import log_change
        log_change(
            **self._ok_kwargs(),
            metadata={'payment_id': 'abc-123', 'reason': 'manual'},
        )
        log = SettingsAuditLog.objects.get(tenant=self.tenant)
        self.assertEqual(log.metadata['payment_id'], 'abc-123')

    def test_safe_log_change_absorbs_guard_error(self):
        """safe_log_change must swallow the ValueError just like any other exception."""
        try:
            safe_log_change(
                tenant=self.tenant, module='payments',
                action='update', source='system',
                field_name='amount',
                new_value='500.00',
            )
        except Exception as exc:
            self.fail(f'safe_log_change propagated guard error: {exc}')
        # No log must have been written — the guard fired before the DB write
        self.assertEqual(SettingsAuditLog.objects.filter(tenant=self.tenant).count(), 0)

    def test_payment_audit_no_longer_stores_amount_in_metadata(self):
        """Regression: _audit_payment_status must not put amount in metadata."""
        payment = PaymentService.create_payment(
            tenant=self.tenant, amount=Decimal('1500'), purpose='membership',
        )
        with self.captureOnCommitCallbacks(execute=True):
            PaymentService.mark_payment_success(payment, gateway_payment_id='gw_x')

        log = SettingsAuditLog.objects.filter(
            tenant=self.tenant, module='payments',
        ).first()
        self.assertIsNotNone(log)
        self.assertNotIn('amount',     log.metadata)
        self.assertNotIn('gst_amount', log.metadata)
        self.assertIn('payment_id',    log.metadata)


# ── Timeline is not source of truth ──────────────────────────────────────────

class TimelineNotSourceOfTruthTests(TestCase):
    """
    Core invariant: deleting every SettingsAuditLog row must leave financial
    reports completely unchanged.

    This test is the executable form of the architectural rule.  If it fails,
    something in the reporting stack has started reading from the audit log.
    """

    def setUp(self):
        from apps.expenses.models import Expense
        from apps.payouts.models import Payout, PayoutStatus
        from apps.verticals.models import BusinessVertical
        from django.utils import timezone
        import datetime

        self.tenant = _make_tenant(_uid())
        self.user   = _make_user(self.tenant)

        def _paid(d):
            return timezone.make_aware(datetime.datetime.combine(d, datetime.time(10, 0)))

        today = datetime.date(2026, 4, 15)
        d_from = datetime.date(2026, 4, 1)
        d_to   = datetime.date(2026, 4, 30)
        self.d_from = d_from
        self.d_to   = d_to

        # Create some payments (success + non-success)
        self.p1 = PaymentService.create_payment(
            tenant=self.tenant, amount=Decimal('3000'), purpose='membership',
        )
        with self.captureOnCommitCallbacks(execute=True):
            PaymentService.mark_payment_success(self.p1)
        self.p2 = PaymentService.create_payment(
            tenant=self.tenant, amount=Decimal('999'), purpose='membership',
        )
        with self.captureOnCommitCallbacks(execute=True):
            PaymentService.mark_payment_failed(self.p2, reason='card_declined')

        # Expense
        Expense.base_objects.create(
            tenant=self.tenant, amount=Decimal('800'), date=today,
        )

        # Payout
        Payout.base_objects.create(
            tenant=self.tenant, staff=self.user,
            amount=Decimal('500'), status='paid',
            paid_at=_paid(today),
        )

        # Audit logs should now exist from the payment transitions
        self.assertTrue(SettingsAuditLog.objects.filter(tenant=self.tenant).exists())

    def _snapshot(self):
        from apps.reporting.services import get_income_expense_summary, get_gst_summary
        return {
            'pl':  get_income_expense_summary(
                tenant=self.tenant, date_from=self.d_from, date_to=self.d_to,
            ),
            'gst': get_gst_summary(
                tenant=self.tenant, date_from=self.d_from, date_to=self.d_to,
            ),
        }

    def test_reports_unchanged_after_deleting_all_audit_logs(self):
        before = self._snapshot()
        SettingsAuditLog.objects.filter(tenant=self.tenant).delete()
        self.assertEqual(SettingsAuditLog.objects.filter(tenant=self.tenant).count(), 0)
        after = self._snapshot()
        self.assertEqual(before['pl']['total_income'],   after['pl']['total_income'])
        self.assertEqual(before['pl']['total_expenses'], after['pl']['total_expenses'])
        self.assertEqual(before['pl']['total_payouts'],  after['pl']['total_payouts'])
        self.assertEqual(before['pl']['net_profit'],     after['pl']['net_profit'])
        self.assertEqual(before['gst']['total_gst_collected'], after['gst']['total_gst_collected'])
        self.assertEqual(before['gst']['taxable_income'],      after['gst']['taxable_income'])
