"""
Tests for Phase 7.1 timeline query service.

Covers: basic retrieval, tenant isolation, metadata filtering,
        N+1 guard, descending order, pagination (limit + before).
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.audit.models import SettingsAuditLog
from apps.audit.timeline_service import get_timeline
from apps.core.models import Tenant


# ── Fixtures ──────────────────────────────────────────────────────────────────

_ctr = [0]
def _uid():
    _ctr[0] += 1
    return _ctr[0]


def _make_tenant():
    n = _uid()
    return Tenant.objects.create(name=f"TimelineGym{n}", subdomain=f"timelinegym{n}")


def _log(tenant, *, module="payments", action="update", source="system", metadata=None, **kwargs):
    return SettingsAuditLog.objects.create(
        tenant=tenant,
        module=module,
        action=action,
        source=source,
        metadata=metadata or {},
        **kwargs,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

class TimelineRetrievalTests(TestCase):

    def setUp(self):
        self.tenant = _make_tenant()

    def test_timeline_returns_logs(self):
        _log(self.tenant)
        _log(self.tenant)
        result = list(get_timeline(tenant=self.tenant))
        self.assertEqual(len(result), 2)

    def test_timeline_empty_when_no_logs(self):
        result = list(get_timeline(tenant=self.tenant))
        self.assertEqual(result, [])

    def test_timeline_respects_tenant(self):
        other = _make_tenant()
        _log(self.tenant)
        _log(other)
        result = list(get_timeline(tenant=self.tenant))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].tenant_id, self.tenant.pk)

    def test_timeline_sorted_desc(self):
        """Most-recent log must come first."""
        _log(self.tenant)
        _log(self.tenant)
        result = list(get_timeline(tenant=self.tenant))
        self.assertGreaterEqual(result[0].timestamp, result[-1].timestamp)

    def test_no_n_plus_one(self):
        """Exactly one DB query regardless of result count (select_related user)."""
        _log(self.tenant)
        _log(self.tenant)
        _log(self.tenant)
        with self.assertNumQueries(1):
            # Force evaluation of the queryset AND user attribute access
            results = list(get_timeline(tenant=self.tenant))
            _ = [r.user for r in results]


class TimelineFilterTests(TestCase):

    def setUp(self):
        self.tenant = _make_tenant()

    def test_module_filter(self):
        _log(self.tenant, module="payments")
        _log(self.tenant, module="roles")
        result = list(get_timeline(tenant=self.tenant, module="payments"))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].module, "payments")

    def test_member_timeline_filters_correctly(self):
        mid = "abc-member-123"
        _log(self.tenant, metadata={"member_id": mid})
        _log(self.tenant, metadata={"member_id": "other-member"})
        result = list(get_timeline(tenant=self.tenant, member_id=mid))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].metadata["member_id"], mid)

    def test_payment_timeline_filters_correctly(self):
        pid = "pay-uuid-456"
        _log(self.tenant, metadata={"payment_id": pid, "amount": "500"})
        _log(self.tenant, metadata={"payment_id": "other-pay"})
        result = list(get_timeline(tenant=self.tenant, payment_id=pid))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].metadata["payment_id"], pid)

    def test_member_filter_is_tenant_scoped(self):
        """member_id match in a different tenant must not appear."""
        other = _make_tenant()
        mid = "shared-member-id"
        _log(self.tenant, metadata={"member_id": mid})
        _log(other,       metadata={"member_id": mid})
        result = list(get_timeline(tenant=self.tenant, member_id=mid))
        self.assertEqual(len(result), 1)


class TimelinePaginationTests(TestCase):

    def setUp(self):
        self.tenant = _make_tenant()
        for _ in range(5):
            _log(self.tenant)

    def test_limit_respected(self):
        result = list(get_timeline(tenant=self.tenant, limit=3))
        self.assertEqual(len(result), 3)

    def test_default_limit_is_50(self):
        for _ in range(60):
            _log(self.tenant)
        result = list(get_timeline(tenant=self.tenant))
        self.assertEqual(len(result), 50)

    def test_before_cursor_excludes_newer(self):
        """before= returns only logs strictly older than the given timestamp."""
        cutoff = timezone.now() - timedelta(seconds=1)
        result = list(get_timeline(tenant=self.tenant, before=cutoff))
        for log in result:
            self.assertLess(log.timestamp, cutoff)
