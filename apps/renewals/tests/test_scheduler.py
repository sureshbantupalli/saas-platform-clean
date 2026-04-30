from datetime import date
from unittest.mock import call, patch

from django.test import TestCase

from apps.core.models import Branch, Tenant
from apps.renewals.scheduler import run_daily_renewals, run_renewals_task


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _tenant(name, active=True):
    t = Tenant.objects.create(
        name=name,
        subdomain=name.lower().replace(' ', '-'),
    )
    if not active:
        t.is_active = False
        t.save()
    return t


# ---------------------------------------------------------------------------
# Scheduler tests
# ---------------------------------------------------------------------------

PATCH_TRIGGER = 'apps.renewals.scheduler.RenewalTriggerService.trigger_all'
TODAY = date(2026, 5, 1)


class RunDailyRenewalsTests(TestCase):

    def setUp(self):
        self.t1 = _tenant('GymA')
        self.t2 = _tenant('GymB')

    # ── 1. Runs for all active tenants ──────────────────────────────────────

    def test_runs_for_all_tenants(self):
        with patch(PATCH_TRIGGER, return_value={'triggered': 1, 'skipped': 0}) as mock_t:
            result = run_daily_renewals(today=TODAY)

        self.assertEqual(mock_t.call_count, 2)
        called_ids = {c[0][0].id for c in mock_t.call_args_list}
        self.assertIn(self.t1.id, called_ids)
        self.assertIn(self.t2.id, called_ids)
        self.assertEqual(result['tenants_processed'], 2)
        self.assertEqual(result['total_triggered'],   2)

    # ── 2. Skips inactive tenants ────────────────────────────────────────────

    def test_runs_single_tenant_only_when_others_inactive(self):
        self.t2.is_active = False
        self.t2.save()

        with patch(PATCH_TRIGGER, return_value={'triggered': 1, 'skipped': 0}) as mock_t:
            result = run_daily_renewals(today=TODAY)

        self.assertEqual(mock_t.call_count, 1)
        self.assertEqual(mock_t.call_args[0][0].id, self.t1.id)
        self.assertEqual(result['tenants_processed'], 1)

    # ── 3. Exception in one tenant doesn't stop the others ──────────────────

    def test_handles_exception_and_continues(self):
        def _fail_first(tenant, today=None):
            if tenant.id == self.t1.id:
                raise RuntimeError('DB unavailable')
            return {'triggered': 2, 'skipped': 0}

        with patch(PATCH_TRIGGER, side_effect=_fail_first):
            result = run_daily_renewals(today=TODAY)

        # t2 still processed despite t1 failing
        self.assertEqual(result['tenants_processed'], 1)
        self.assertEqual(result['total_triggered'],   2)
        self.assertEqual(len(result['failed_tenants']), 1)
        self.assertIn(str(self.t1.id), result['failed_tenants'])

    # ── 4. Correct arguments forwarded to trigger service ───────────────────

    def test_calls_trigger_service_with_correct_args(self):
        with patch(PATCH_TRIGGER, return_value={'triggered': 0, 'skipped': 0}) as mock_t:
            run_daily_renewals(today=TODAY)

        for c in mock_t.call_args_list:
            tenant_arg = c[0][0]        # positional: tenant
            date_kwarg = c[1]['today']  # keyword: today
            self.assertIsInstance(tenant_arg, Tenant)
            self.assertEqual(date_kwarg, TODAY)

    # ── 5. Structured logs are emitted ──────────────────────────────────────

    def test_logs_summary_per_tenant(self):
        with patch(PATCH_TRIGGER, return_value={'triggered': 3, 'skipped': 1}):
            with self.assertLogs('apps.renewals.scheduler', level='INFO') as cm:
                run_daily_renewals(today=TODAY)

        # One renewals_triggered record per tenant; both should carry triggered=3
        triggered_values = [getattr(r, 'triggered', None) for r in cm.records]
        self.assertEqual(triggered_values.count(3), 2)

    def test_logs_error_on_failure(self):
        with patch(PATCH_TRIGGER, side_effect=RuntimeError('oops')):
            with self.assertLogs('apps.renewals.scheduler', level='ERROR') as cm:
                run_daily_renewals(today=TODAY)

        errors = [getattr(r, 'error', None) for r in cm.records]
        self.assertTrue(any('oops' in (e or '') for e in errors))

    # ── 6. Return shape is correct ───────────────────────────────────────────

    def test_return_value_shape(self):
        with patch(PATCH_TRIGGER, return_value={'triggered': 1, 'skipped': 2}):
            result = run_daily_renewals(today=TODAY)

        self.assertIn('tenants_processed', result)
        self.assertIn('total_triggered',   result)
        self.assertIn('total_skipped',     result)
        self.assertIn('failed_tenants',    result)
        self.assertIsInstance(result['failed_tenants'], list)

    # ── 7. Celery wrapper delegates to run_daily_renewals ───────────────────

    def test_run_renewals_task_delegates(self):
        with patch('apps.renewals.scheduler.run_daily_renewals',
                   return_value={'tenants_processed': 1, 'total_triggered': 1,
                                 'total_skipped': 0, 'failed_tenants': []}) as mock_rd:
            run_renewals_task()

        mock_rd.assert_called_once_with()
