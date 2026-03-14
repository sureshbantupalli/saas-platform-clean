from django.http import HttpResponse
from django.shortcuts import get_object_or_404

from apps.authority.decorators import require_permission
from members.models import Member


# --------------------------------------------------
# Simple Permission Test (Create Member)
# --------------------------------------------------

@require_permission("members", "create")
def test_create_member(request):
    """
    RBAC test endpoint for member creation permission
    """
    return HttpResponse("Member created successfully")


# --------------------------------------------------
# Object-Level Scope Test (View Member)
# --------------------------------------------------

def get_member_object(request, member_id):
    """
    Fetch member object for object-level permission validation
    """
    return get_object_or_404(Member, id=member_id)


@require_permission(
    "members",
    "view",
    get_object_func=lambda request, member_id: get_member_object(request, member_id)
)
def view_member(request, member_id):
    """
    RBAC test endpoint for viewing a specific member
    """
    member = get_member_object(request, member_id)

    return HttpResponse(f"Viewing member: {member.id}")

from django.shortcuts import render


def tenant_dashboard(request):

    return render(
        request,
        "core/tenant_dashboard.html"
    )