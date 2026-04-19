from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .services.next_best_action_service import get_next_actions


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def next_actions_api(request):
    actions = get_next_actions(request.tenant)
    return Response(actions)
