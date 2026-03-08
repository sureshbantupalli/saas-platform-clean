# apps/monitoring/permissions.py

class MonitoringPermission:
    """
    Permission handler for Monitoring module.
    """

    def has_permission(self, user, action, obj=None):

        # Platform admin always allowed
        if user.is_superuser:
            return True

        # Allow view action
        if action == "view":
            return user.has_permission("monitoring", "view")

        return False