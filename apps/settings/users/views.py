from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.models import User
from apps.authority.models import Role
from apps.audit.services import safe_log_change


def _tenant_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not getattr(request, 'tenant', None):
            return HttpResponseForbidden(
                'Staff settings are tenant-specific. Platform admins use Django Admin.'
            )
        return view_func(request, *args, **kwargs)
    return _wrapped


def _tenant_roles(tenant):
    return Role.base_objects.filter(tenant=tenant).order_by('name')


@login_required
@_tenant_required
def user_list(request):
    staff = (
        User.objects
        .filter(tenant=request.tenant)
        .select_related('role')
        .order_by('email')
    )
    return render(request, 'settings/users/user_list.html', {
        'staff':      staff,
        'active_tab': 'staff',
    })


@login_required
@_tenant_required
def user_invite(request):
    roles = _tenant_roles(request.tenant)

    if request.method == 'POST':
        email      = request.POST.get('email', '').strip().lower()
        first_name = request.POST.get('first_name', '').strip()
        last_name  = request.POST.get('last_name', '').strip()
        role_id    = request.POST.get('role', '').strip()
        password   = request.POST.get('password', '')
        password2  = request.POST.get('password2', '')

        errors = []

        if not email:
            errors.append('Email is required.')
        elif User.objects.filter(email=email).exists():
            errors.append(f'A user with email "{email}" already exists.')

        if not role_id:
            errors.append('Role is required.')
        else:
            try:
                role = Role.base_objects.get(pk=role_id, tenant=request.tenant)
            except Role.DoesNotExist:
                errors.append('Invalid role selected.')
                role = None

        if not password:
            errors.append('Password is required.')
        elif len(password) < 8:
            errors.append('Password must be at least 8 characters.')
        elif password != password2:
            errors.append('Passwords do not match.')

        if errors:
            for e in errors:
                messages.error(request, e)
            return render(request, 'settings/users/user_form.html', {
                'user_obj':     None,
                'roles':        roles,
                'active_tab':   'staff',
                'f_email':      email,
                'f_first_name': first_name,
                'f_last_name':  last_name,
                'f_role':       role_id,
            })

        user = User(
            email=email,
            first_name=first_name,
            last_name=last_name,
            tenant=request.tenant,
            role=role,
            is_active=True,
            is_platform_admin=False,
        )
        user.set_password(password)
        user.save()

        safe_log_change(
            tenant=request.tenant, user=request.user,
            module='staff', action='create', source='user',
            field_name='email', new_value=email,
            metadata={'role': role.name},
        )
        messages.success(request, f'Staff account created for {email}.')
        return redirect('settings:staff:list')

    return render(request, 'settings/users/user_form.html', {
        'user_obj':    None,
        'roles':       roles,
        'active_tab':  'staff',
        'f_email':     '',
        'f_first_name': '',
        'f_last_name':  '',
        'f_role':       '',
    })


@login_required
@_tenant_required
def user_edit(request, user_id: int):
    staff_user = get_object_or_404(User, pk=user_id, tenant=request.tenant)
    roles = _tenant_roles(request.tenant)

    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name  = request.POST.get('last_name', '').strip()
        role_id    = request.POST.get('role', '').strip()
        is_active  = request.POST.get('is_active') == 'on'

        def _edit_ctx():
            return {
                'user_obj': staff_user, 'roles': roles, 'active_tab': 'staff',
                'f_email':      staff_user.email,
                'f_first_name': first_name,
                'f_last_name':  last_name,
                'f_role':       role_id,
            }

        if not role_id:
            messages.error(request, 'Role is required.')
            return render(request, 'settings/users/user_form.html', _edit_ctx())

        try:
            role = Role.base_objects.get(pk=role_id, tenant=request.tenant)
        except Role.DoesNotExist:
            messages.error(request, 'Invalid role selected.')
            return render(request, 'settings/users/user_form.html', _edit_ctx())

        old_role      = staff_user.role
        old_is_active = staff_user.is_active

        staff_user.first_name = first_name
        staff_user.last_name  = last_name
        staff_user.role       = role
        staff_user.is_active  = is_active
        staff_user.save()

        if old_role != role:
            safe_log_change(
                tenant=request.tenant, user=request.user,
                module='staff', action='update', source='user',
                field_name='role',
                old_value=str(old_role), new_value=role.name,
                metadata={'user_email': staff_user.email},
            )
        if old_is_active != is_active:
            safe_log_change(
                tenant=request.tenant, user=request.user,
                module='staff', action='update', source='user',
                field_name='is_active',
                old_value=old_is_active, new_value=is_active,
                metadata={'user_email': staff_user.email},
            )

        messages.success(request, f'Staff account for {staff_user.email} updated.')
        return redirect('settings:staff:list')

    return render(request, 'settings/users/user_form.html', {
        'user_obj':     staff_user,
        'roles':        roles,
        'active_tab':   'staff',
        'f_email':      staff_user.email,
        'f_first_name': staff_user.first_name,
        'f_last_name':  staff_user.last_name,
        'f_role':       str(staff_user.role_id) if staff_user.role_id else '',
    })


@login_required
@_tenant_required
@require_POST
def user_toggle(request, user_id: int):
    staff_user = get_object_or_404(User, pk=user_id, tenant=request.tenant)

    # Prevent the logged-in user from deactivating themselves
    if staff_user.pk == request.user.pk:
        messages.error(request, 'You cannot deactivate your own account.')
        return redirect('settings:staff:list')

    staff_user.is_active = not staff_user.is_active
    staff_user.save()

    status = 'activated' if staff_user.is_active else 'deactivated'
    safe_log_change(
        tenant=request.tenant, user=request.user,
        module='staff', action='update', source='user',
        field_name='is_active',
        old_value=not staff_user.is_active, new_value=staff_user.is_active,
        metadata={'user_email': staff_user.email},
    )
    messages.success(request, f'{staff_user.email} has been {status}.')
    return redirect('settings:staff:list')
