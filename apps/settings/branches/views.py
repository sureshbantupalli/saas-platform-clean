from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.models import Branch
from apps.audit.services import safe_log_change, normalize


def _tenant_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not getattr(request, 'tenant', None):
            return HttpResponseForbidden(
                'Branch settings are tenant-specific. Platform admins use Django Admin.'
            )
        return view_func(request, *args, **kwargs)
    return _wrapped


@login_required
@_tenant_required
def branch_list(request):
    branches = Branch.base_objects.filter(
        tenant=request.tenant, is_deleted=False
    ).order_by('name')
    return render(request, 'settings/branches/branch_list.html', {
        'branches':   branches,
        'active_tab': 'branches',
    })


@login_required
@_tenant_required
def branch_create(request):
    if request.method == 'POST':
        name    = request.POST.get('name', '').strip()
        address = request.POST.get('address', '').strip()
        phone   = request.POST.get('phone', '').strip()
        email   = request.POST.get('email', '').strip()

        def _create_ctx(b=None):
            return {
                'branch': b, 'active_tab': 'branches',
                'f_name': name, 'f_address': address,
                'f_phone': phone, 'f_email': email,
            }

        if not name:
            messages.error(request, 'Branch name is required.')
            return render(request, 'settings/branches/branch_form.html', _create_ctx())

        if Branch.base_objects.filter(tenant=request.tenant, name=name, is_deleted=False).exists():
            messages.error(request, f'A branch named "{name}" already exists.')
            return render(request, 'settings/branches/branch_form.html', _create_ctx())

        try:
            branch = Branch.base_objects.create(
                tenant=request.tenant,
                name=name,
                address=address,
                phone=phone,
                email=email,
                is_active=True,
            )
        except IntegrityError:
            messages.error(request, f'A branch named "{name}" already exists.')
            return render(request, 'settings/branches/branch_form.html', _create_ctx())

        safe_log_change(
            tenant=request.tenant, user=request.user,
            module='branches', action='create', source='user',
            field_name='branch', new_value=branch.name,
        )
        messages.success(request, f'Branch "{branch.name}" created.')
        return redirect('settings:branches:list')

    return render(request, 'settings/branches/branch_form.html', {
        'branch': None, 'active_tab': 'branches',
        'f_name': '', 'f_address': '', 'f_phone': '', 'f_email': '',
    })


@login_required
@_tenant_required
def branch_edit(request, branch_id):
    branch = get_object_or_404(
        Branch.base_objects, pk=branch_id, tenant=request.tenant, is_deleted=False
    )

    if request.method == 'POST':
        name    = request.POST.get('name', '').strip()
        address = request.POST.get('address', '').strip()
        phone   = request.POST.get('phone', '').strip()
        email   = request.POST.get('email', '').strip()

        def _edit_ctx():
            return {
                'branch': branch, 'active_tab': 'branches',
                'f_name': name, 'f_address': address,
                'f_phone': phone, 'f_email': email,
            }

        if not name:
            messages.error(request, 'Branch name is required.')
            return render(request, 'settings/branches/branch_form.html', _edit_ctx())

        duplicate = (
            Branch.base_objects
            .filter(tenant=request.tenant, name=name, is_deleted=False)
            .exclude(pk=branch.pk)
            .exists()
        )
        if duplicate:
            messages.error(request, f'A branch named "{name}" already exists.')
            return render(request, 'settings/branches/branch_form.html', _edit_ctx())

        old_name = branch.name
        branch.name    = name
        branch.address = address
        branch.phone   = phone
        branch.email   = email
        branch.save()

        if normalize(old_name) != normalize(name):
            safe_log_change(
                tenant=request.tenant, user=request.user,
                module='branches', action='update', source='user',
                field_name='name', old_value=old_name, new_value=name,
            )

        messages.success(request, f'Branch "{branch.name}" updated.')
        return redirect('settings:branches:list')

    return render(request, 'settings/branches/branch_form.html', {
        'branch': branch, 'active_tab': 'branches',
        'f_name': branch.name, 'f_address': branch.address,
        'f_phone': branch.phone, 'f_email': branch.email,
    })


@login_required
@_tenant_required
@require_POST
def branch_toggle(request, branch_id):
    branch = get_object_or_404(
        Branch.base_objects, pk=branch_id, tenant=request.tenant, is_deleted=False
    )
    branch.is_active = not branch.is_active
    branch.save()

    status = 'activated' if branch.is_active else 'deactivated'
    safe_log_change(
        tenant=request.tenant, user=request.user,
        module='branches', action='update', source='user',
        field_name='is_active', old_value=not branch.is_active, new_value=branch.is_active,
        metadata={'branch_id': str(branch.pk), 'branch_name': branch.name},
    )
    messages.success(request, f'Branch "{branch.name}" {status}.')
    return redirect('settings:branches:list')
