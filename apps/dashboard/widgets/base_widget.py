class BaseWidget:
    """
    Base class for all dashboard widgets.
    """

    key = None
    title = None

    def get_data(self, tenant, branch=None):
        """
        Return widget data.
        Must be implemented by child classes.
        """
        raise NotImplementedError("Widget must implement get_data()")