import json
from datetime import datetime, timezone
from decimal import Decimal

from django.test import TestCase

from apps.audit.models import AuditAction, AuditModule, AuditSource, SettingsAuditLog
from apps.audit.services import log_change, safe_log_change
from apps.core.models import Tenant


def _make_tenant():
    return Tenant.objects.create(name='AuditTestGym', subdomain='auditgym')


class AuditLogCreationTests(TestCase):
    def setUp(self):
        self.tenant = _make_tenant()

    def test_log_created_successfully(self):
        log_change(
            tenant=self.tenant,
            module=AuditModule.BRANDING,
            action=AuditAction.UPDATE,
            source=AuditSource.USER,
            field_name='primary_color',
            old_value='#ffffff',
            new_value='#000000',
        )
        log = SettingsAuditLog.objects.get(tenant=self.tenant)
        self.assertEqual(log.module, AuditModule.BRANDING)
        self.assertEqual(log.action, AuditAction.UPDATE)
        self.assertEqual(log.source, AuditSource.USER)
        self.assertEqual(log.field_name, 'primary_color')
        self.assertEqual(log.old_value, '#ffffff')
        self.assertEqual(log.new_value, '#000000')
        self.assertEqual(log.metadata, {})

    def test_log_handles_none_user(self):
        log_change(
            tenant=self.tenant,
            user=None,
            module=AuditModule.SETTINGS,
            action=AuditAction.CREATE,
            source=AuditSource.SYSTEM,
        )
        log = SettingsAuditLog.objects.get(tenant=self.tenant)
        self.assertIsNone(log.user)

    def test_safe_log_change_never_crashes(self):
        """safe_log_change must swallow all exceptions — this is the public contract."""
        try:
            safe_log_change(
                tenant=None,  # will cause DB NOT NULL violation inside log_change
                module=AuditModule.SETTINGS,
                action=AuditAction.UPDATE,
                source=AuditSource.SYSTEM,
            )
        except Exception as exc:
            self.fail(f'safe_log_change raised an exception: {exc}')

    def test_log_change_propagates_exceptions(self):
        """log_change is the raw write — it CAN raise. safe_log_change wraps it."""
        with self.assertRaises(Exception):
            log_change(
                tenant=None,  # NOT NULL violation
                module=AuditModule.SETTINGS,
                action=AuditAction.UPDATE,
                source=AuditSource.SYSTEM,
            )

    def test_metadata_defaults_empty_dict(self):
        log_change(
            tenant=self.tenant,
            module=AuditModule.ROLES,
            action=AuditAction.DELETE,
            source=AuditSource.USER,
        )
        log = SettingsAuditLog.objects.get(tenant=self.tenant)
        self.assertEqual(log.metadata, {})
        self.assertIsInstance(log.metadata, dict)

    def test_source_defaults_to_system(self):
        log_change(tenant=self.tenant, module=AuditModule.SETTINGS, action=AuditAction.UPDATE)
        log = SettingsAuditLog.objects.get(tenant=self.tenant)
        self.assertEqual(log.source, AuditSource.SYSTEM)

    def test_old_new_value_are_serializable(self):
        """Complex objects are stored as valid JSON, not Python repr.

        Decimal: not JSON-serializable natively — _json_default falls back to str().
        dict:    json.loads() round-trip distinguishes '{"a": 1}' from "{'a': 1}";
                 the latter is Python repr and would break future analytics queries.
        """
        log_change(
            tenant=self.tenant,
            module=AuditModule.PAYMENTS,
            action=AuditAction.UPDATE,
            source=AuditSource.SYSTEM,
            field_name='price',
            old_value=Decimal('99.99'),
            new_value={'amount': 199, 'currency': 'INR'},
        )
        log = SettingsAuditLog.objects.get(tenant=self.tenant)

        self.assertIsInstance(log.old_value, str)
        self.assertIsInstance(log.new_value, str)

        self.assertIn('99.99', log.old_value)
        self.assertEqual(json.loads(log.old_value), '99.99')

        parsed = json.loads(log.new_value)
        self.assertEqual(parsed['amount'], 199)
        self.assertEqual(parsed['currency'], 'INR')

    def test_datetime_serializes_as_iso(self):
        """datetime values must be ISO 8601, not str(datetime) which is locale/system-dependent."""
        dt = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
        log_change(
            tenant=self.tenant,
            module=AuditModule.SETTINGS,
            action=AuditAction.UPDATE,
            source=AuditSource.SYSTEM,
            field_name='renewal_date',
            old_value=dt,
        )
        log = SettingsAuditLog.objects.get(tenant=self.tenant)

        stored = json.loads(log.old_value)
        parsed_dt = datetime.fromisoformat(stored)
        self.assertEqual(parsed_dt.year, 2026)
        self.assertEqual(parsed_dt.month, 5)
        self.assertEqual(parsed_dt.day, 1)
        self.assertIn('T', stored)
