from django.http import HttpResponse
from django.shortcuts import get_object_or_404

from apps.authority.decorators import require_permission


# --------------------------------------------------
# Simple Permission Test (Create)
# --------------------------------------------------

@require_permission("members", "create")
def test_create_member(request):
    return HttpResponse("Member created successfully")


# --------------------------------------------------
# Object-Level Scope Test (View Member)
# --------------------------------------------------

def get_member_object(request, member_id):
    return get_object_or_404(Member, id=member_id)


@require_permission(
    "members",
    "view",
    get_object_func=lambda request, member_id: get_member_object(request, member_id)
)
def view_member(request, member_id):
    return HttpResponse("Viewing member")