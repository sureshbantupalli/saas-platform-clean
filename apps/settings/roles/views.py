import json

from django.apps import apps
from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import Permission, Role, RolePermission, UserRole
from .services import RBACService

from apps.audit.services import safe_log_change, normalize


def _tenant_required(view_func):
    """Guard: reject platform admins (no tenant) from tenant settings."""
    from functools import wraps
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.tenant:
            from django.http import HttpResponseForbidden
            return HttpResponseForbidden('Settings are tenant-specific. Platform admins use Django Admin.')
        return view_func(request, *args, **kwargs)
    return _wrapped


# ── Role list ──────────────────────────────────────────────────────────────────

@login_required
@_tenant_required
def role_list(request):
    roles = (
        Role.base_objects
        .filter(tenant=request.tenant, is_deleted=False)
        .prefetch_related('role_permissions', 'user_roles')
    )
    return render(request, 'settings/roles/role_list.html', {'roles': roles})


# ── Role create ────────────────────────────────────────────────────────────────

@login_required
@_tenant_required
def role_create(request):
    if request.method == 'POST':
        name       = request.POST.get('name', '').strip()
        is_default = request.POST.get('is_default') == 'on'

        if not name:
            messages.error(request, 'Role name is required.')
            return render(request, 'settings/roles/role_form.html', {'role': None, 'name': ''})

        if Role.base_objects.filter(tenant=request.tenant, name=name, is_deleted=False).exists():
            messages.error(request, f'A role named "{name}" already exists.')
            return render(request, 'settings/roles/role_form.html', {'role': None, 'name': name})

        if is_default:
            Role.base_objects.filter(tenant=request.tenant, is_default=True).update(is_default=False)

        role = Role.base_objects.create(
            tenant=request.tenant,
            name=name,
            is_default=is_default,
        )
        safe_log_change(
            tenant=request.tenant,
            user=request.user,
            module='roles',
            action='create',
            source='user',
            field_name='role',
            new_value=role.name,
        )
        messages.success(request, f'Role "{role.name}" created. Now assign permissions.')
        return redirect('settings:roles:permissions', role_id=role.pk)

    return render(request, 'settings/roles/role_form.html', {'role': None, 'name': ''})


# ── Role edit ─────────────────────────────────────────────────────────────────

@login_required
@_tenant_required
def role_edit(request, role_id):
    role = get_object_or_404(Role.base_objects, pk=role_id, tenant=request.tenant, is_deleted=False)

    if request.method == 'POST':
        name       = request.POST.get('name', '').strip()
        is_default = request.POST.get('is_default') == 'on'

        if not name:
            messages.error(request, 'Role name is required.')
            return render(request, 'settings/roles/role_form.html', {'role': role})

        duplicate = (
            Role.base_objects
            .filter(tenant=request.tenant, name=name, is_deleted=False)
            .exclude(pk=role.pk)
            .exists()
        )
        if duplicate:
            messages.error(request, f'A role named "{name}" already exists.')
            return render(request, 'settings/roles/role_form.html', {'role': role})

        if is_default and not role.is_default:
            Role.base_objects.filter(tenant=request.tenant, is_default=True).update(is_default=False)

        # Capture old values before mutation for diff-based logging
        old_name       = role.name
        old_is_default = role.is_default

        role.name       = name
        role.is_default = is_default
        role.save()

        if normalize(old_name) != normalize(name):
            safe_log_change(
                tenant=request.tenant, user=request.user,
                module='roles', action='update', source='user',
                field_name='name', old_value=old_name, new_value=name,
            )
        if old_is_default != is_default:
            safe_log_change(
                tenant=request.tenant, user=request.user,
                module='roles', action='update', source='user',
                field_name='is_default',
                old_value=old_is_default, new_value=is_default,
            )

        messages.success(request, f'Role "{role.name}" updated.')
        return redirect('settings:roles:list')

    return render(request, 'settings/roles/role_form.html', {'role': role})


# ── Role delete ────────────────────────────────────────────────────────────────

@login_required
@_tenant_required
@require_POST
def role_delete(request, role_id):
    role = get_object_or_404(Role.base_objects, pk=role_id, tenant=request.tenant, is_deleted=False)
    name = role.name
    role.delete()
    safe_log_change(
        tenant=request.tenant, user=request.user,
        module='roles', action='delete', source='user',
        field_name='role', old_value=name,
    )
    messages.success(request, f'Role "{name}" deleted.')
    return redirect('settings:roles:list')


# ── Permission assignment ──────────────────────────────────────────────────────

@login_required
@_tenant_required
def role_permissions(request, role_id):
    role = get_object_or_404(Role.base_objects, pk=role_id, tenant=request.tenant, is_deleted=False)

    all_perms    = list(Permission.objects.all().prefetch_related('depends_on'))
    granted_codes = set(
        RolePermission.objects.filter(role=role).values_list('permission__code', flat=True)
    )

    dep_map = {p.code: [d.code for d in p.depends_on.all()] for p in all_perms}
    rev_map = {}
    for perm in all_perms:
        for dep in perm.depends_on.all():
            rev_map.setdefault(dep.code, []).append(perm.code)

    by_module: dict[str, list] = {}
    for p in all_perms:
        by_module.setdefault(p.module, []).append(p)

    if request.method == 'POST':
        selected  = set(request.POST.getlist('permissions'))
        old_perms = set(granted_codes)  # snapshot before mutation

        RBACService.assign_permissions(role, list(selected))

        if selected != old_perms:
            safe_log_change(
                tenant=request.tenant, user=request.user,
                module='roles', action='update', source='user',
                field_name='permissions',
                old_value=sorted(old_perms),
                new_value=sorted(selected),
                metadata={'role_id': str(role.pk), 'role_name': role.name},
            )

        messages.success(request, f'Permissions updated for "{role.name}".')
        return redirect('settings:roles:list')

    return render(request, 'settings/roles/role_permissions.html', {
        'role':          role,
        'by_module':     by_module,
        'granted_codes': granted_codes,
        'dep_map_json':  json.dumps(dep_map),
        'rev_map_json':  json.dumps(rev_map),
    })


# ── User assignment ────────────────────────────────────────────────────────────

@login_required
@_tenant_required
def role_users(request, role_id):
    role = get_object_or_404(Role.base_objects, pk=role_id, tenant=request.tenant, is_deleted=False)

    User = apps.get_model(django_settings.AUTH_USER_MODEL)
    tenant_users   = list(User.objects.filter(tenant=request.tenant).order_by('email'))
    assigned_ids   = set(UserRole.objects.filter(role=role).values_list('user_id', flat=True))

    if request.method == 'POST':
        new_ids = set(request.POST.getlist('users'))

        UserRole.objects.filter(role=role).exclude(user_id__in=new_ids).delete()

        for uid in new_ids - assigned_ids:
            try:
                user = User.objects.get(pk=uid, tenant=request.tenant)
                UserRole.objects.get_or_create(user=user, role=role)
            except User.DoesNotExist:
                pass

        if new_ids != assigned_ids:
            safe_log_change(
                tenant=request.tenant, user=request.user,
                module='roles', action='update', source='user',
                field_name='user_assignments',
                old_value=sorted(str(i) for i in assigned_ids),
                new_value=sorted(str(i) for i in new_ids),
                metadata={'role_id': str(role.pk), 'role_name': role.name},
            )

        messages.success(request, f'Users updated for "{role.name}".')
        return redirect('settings:roles:list')

    return render(request, 'settings/roles/role_users.html', {
        'role':         role,
        'tenant_users': tenant_users,
        'assigned_ids': assigned_ids,
    })
