from apps.core.tenant_context import set_current_tenant


class TenantMiddleware:
    """
    Sets the current tenant in thread-local storage
    based on the authenticated user's tenant.
    Must run AFTER AuthenticationMiddleware.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):

        # Default to None
        tenant = None

        # Only set tenant if user is authenticated
        if hasattr(request, "user") and request.user.is_authenticated:
            tenant = getattr(request.user, "tenant", None)

        set_current_tenant(tenant)

        response = self.get_response(request)

        return response