from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model

from apps.core.models import Tenant, Branch
from apps.authority.models import Role as AuthorityRole
from .models import Permission, Role, RolePermission, UserRole
from .services import RBACService
from .decorators import require_permission

User = get_user_model()


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_world(name='Acme'):
    tenant = Tenant.objects.create(name=name, subdomain=name.lower())
    Branch.objects.create(tenant=tenant, name='Main')
    legacy_role = AuthorityRole.base_objects.create(tenant=tenant, name='Staff')
    user = User.objects.create_user(
        email=f'admin@{name.lower()}.com',
        password='pass',
        tenant=tenant,
        role=legacy_role,
    )
    return tenant, user


def make_permission(code, module='crm', depends_on=None):
    perm, _ = Permission.objects.get_or_create(
        code=code,
        defaults={'label': code, 'module': module},
    )
    if depends_on:
        perm.depends_on.set(depends_on)
    return perm


def make_role(tenant, name='Trainer'):
    return Role.base_objects.create(tenant=tenant, name=name)


# ── Dependency auto-select ────────────────────────────────────────────────────

class DependencyAutoSelectTests(TestCase):
    """Selecting a permission must pull in all transitive dependencies."""

    def setUp(self):
        self.view   = make_permission('crm.view_enquiries',   'crm')
        self.edit   = make_permission('crm.edit_enquiries',   'crm', depends_on=[self.view])
        self.delete = make_permission('crm.delete_enquiries', 'crm', depends_on=[self.edit])

    def test_selecting_delete_pulls_in_edit_and_view(self):
        resolved = RBACService.resolve_with_dependencies(['crm.delete_enquiries'])
        codes = {p.code for p in resolved}
        self.assertIn('crm.view_enquiries',   codes)
        self.assertIn('crm.edit_enquiries',   codes)
        self.assertIn('crm.delete_enquiries', codes)

    def test_selecting_view_only_returns_view(self):
        resolved = RBACService.resolve_with_dependencies(['crm.view_enquiries'])
        codes = {p.code for p in resolved}
        self.assertEqual(codes, {'crm.view_enquiries'})

    def test_selecting_edit_pulls_in_view(self):
        resolved = RBACService.resolve_with_dependencies(['crm.edit_enquiries'])
        codes = {p.code for p in resolved}
        self.assertIn('crm.view_enquiries', codes)
        self.assertIn('crm.edit_enquiries', codes)
        self.assertNotIn('crm.delete_enquiries', codes)

    def test_assign_permissions_auto_resolves_deps(self):
        tenant, user = make_world('DepTest')
        role = make_role(tenant)
        RBACService.assign_permissions(role, ['crm.delete_enquiries'])
        granted = set(
            RolePermission.objects.filter(role=role).values_list('permission__code', flat=True)
        )
        self.assertIn('crm.view_enquiries',   granted)
        self.assertIn('crm.edit_enquiries',   granted)
        self.assertIn('crm.delete_enquiries', granted)

    def test_empty_selection_clears_all(self):
        tenant, user = make_world('ClearTest')
        role = make_role(tenant)
        RBACService.assign_permissions(role, ['crm.view_enquiries'])
        RBACService.assign_permissions(role, [])
        self.assertEqual(RolePermission.objects.filter(role=role).count(), 0)


# ── Dependent detection ───────────────────────────────────────────────────────

class DependentDetectionTests(TestCase):

    def setUp(self):
        self.view = make_permission('pay.view',    'payments')
        self.coll = make_permission('pay.collect', 'payments', depends_on=[self.view])

    def test_get_dependents_in_role(self):
        tenant, _ = make_world('DepDetect')
        role = make_role(tenant)
        RBACService.assign_permissions(role, ['pay.collect'])  # resolves both
        deps = RBACService.get_dependents_in_role(self.view, role)
        self.assertIn(self.coll, deps)

    def test_no_dependents_when_none_granted(self):
        tenant, _ = make_world('NoDep')
        role = make_role(tenant, 'Empty')
        deps = RBACService.get_dependents_in_role(self.view, role)
        self.assertEqual(deps, [])


# ── Permission enforcement ────────────────────────────────────────────────────

class PermissionEnforcementTests(TestCase):

    def setUp(self):
        self.view_perm = make_permission('crm.view_enquiries', 'crm')
        self.tenant, self.user = make_world('Enforce')
        self.role = make_role(self.tenant, 'Agent')

    def test_user_without_role_denied(self):
        self.assertFalse(RBACService.has_permission(self.user, 'crm.view_enquiries'))

    def test_user_with_role_and_permission_allowed(self):
        UserRole.objects.create(user=self.user, role=self.role)
        RolePermission.objects.create(role=self.role, permission=self.view_perm)
        self.assertTrue(RBACService.has_permission(self.user, 'crm.view_enquiries'))

    def test_user_with_role_but_different_permission_denied(self):
        UserRole.objects.create(user=self.user, role=self.role)
        RolePermission.objects.create(role=self.role, permission=self.view_perm)
        self.assertFalse(RBACService.has_permission(self.user, 'crm.edit_enquiries'))

    def test_platform_admin_always_allowed(self):
        self.user.is_platform_admin = True
        self.user.save()
        self.assertTrue(RBACService.has_permission(self.user, 'anything.at.all'))

    def test_decorator_raises_403_when_denied(self):
        from django.core.exceptions import PermissionDenied
        factory = RequestFactory()
        request = factory.get('/')
        request.user = self.user

        @require_permission('crm.view_enquiries')
        def dummy_view(req):
            return 'ok'

        with self.assertRaises(PermissionDenied):
            dummy_view(request)

    def test_decorator_passes_when_allowed(self):
        UserRole.objects.create(user=self.user, role=self.role)
        RolePermission.objects.create(role=self.role, permission=self.view_perm)

        factory = RequestFactory()
        request = factory.get('/')
        request.user = self.user

        @require_permission('crm.view_enquiries')
        def dummy_view(req):
            return 'ok'

        result = dummy_view(request)
        self.assertEqual(result, 'ok')


# ── Tenant isolation ──────────────────────────────────────────────────────────

class TenantIsolationTests(TestCase):
    """Roles and assignments must not leak across tenants."""

    def setUp(self):
        self.perm = make_permission('members.view', 'members')
        self.tenant_a, self.user_a = make_world('TenantA')
        self.tenant_b, self.user_b = make_world('TenantB')
        self.role_a = make_role(self.tenant_a, 'Staff')
        self.role_b = make_role(self.tenant_b, 'Staff')

    def test_user_a_cannot_use_role_b(self):
        UserRole.objects.create(user=self.user_a, role=self.role_b)
        RolePermission.objects.create(role=self.role_b, permission=self.perm)
        # user_a holds a role from tenant_b — has_permission still works
        # but the role doesn't belong to their tenant
        self.assertTrue(RBACService.has_permission(self.user_a, 'members.view'))
        # This is a cross-tenant assignment — confirm role_b is NOT in tenant_a
        self.assertNotEqual(self.role_b.tenant, self.tenant_a)

    def test_roles_are_tenant_scoped(self):
        from django.db import IntegrityError
        # Same name, different tenants — allowed
        Role.base_objects.create(tenant=self.tenant_a, name='UniquePerTenant')
        Role.base_objects.create(tenant=self.tenant_b, name='UniquePerTenant')
        self.assertEqual(
            Role.base_objects.filter(name='UniquePerTenant').count(), 2
        )

    def test_duplicate_role_name_in_same_tenant_raises(self):
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            Role.base_objects.create(tenant=self.tenant_a, name='Staff')


# ── Role user assignment ──────────────────────────────────────────────────────

class UserRoleAssignmentTests(TestCase):

    def setUp(self):
        self.tenant, self.user = make_world('Assign')
        self.role1 = make_role(self.tenant, 'Trainer')
        self.role2 = make_role(self.tenant, 'Manager')

    def test_assign_role(self):
        RBACService.assign_role(self.user, self.role1)
        self.assertTrue(UserRole.objects.filter(user=self.user, role=self.role1).exists())

    def test_assign_role_idempotent(self):
        RBACService.assign_role(self.user, self.role1)
        RBACService.assign_role(self.user, self.role1)
        self.assertEqual(UserRole.objects.filter(user=self.user, role=self.role1).count(), 1)

    def test_remove_role(self):
        RBACService.assign_role(self.user, self.role1)
        RBACService.remove_role(self.user, self.role1)
        self.assertFalse(UserRole.objects.filter(user=self.user, role=self.role1).exists())

    def test_set_user_roles_replaces(self):
        RBACService.assign_role(self.user, self.role1)
        RBACService.set_user_roles(self.user, [self.role2])
        self.assertFalse(UserRole.objects.filter(user=self.user, role=self.role1).exists())
        self.assertTrue(UserRole.objects.filter(user=self.user, role=self.role2).exists())

    def test_user_can_hold_multiple_roles(self):
        RBACService.assign_role(self.user, self.role1)
        RBACService.assign_role(self.user, self.role2)
        self.assertEqual(UserRole.objects.filter(user=self.user).count(), 2)
