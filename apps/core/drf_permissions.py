from rest_framework.permissions import BasePermission
from apps.core.permissions import require_permission


class MemberPermission(BasePermission):

    def has_permission(self, request, view):
        # Map HTTP method to action
        action_map = {
            "GET": "view",
            "POST": "create",
            "PUT": "update",
            "PATCH": "update",
            "DELETE": "delete",
        }

        action = action_map.get(request.method)

        if not action:
            return False

        # Use your existing permission system
        decorator = require_permission("members", action)

        # Apply decorator logic manually
        return decorator(lambda r: True)(request)