from apps.dashboard.registry import get_widget, WIDGET_REGISTRY


class WidgetService:
    """
    Executes dashboard widgets and returns serialized data
    for the frontend dashboard.
    """

    def __init__(self, tenant, branch=None):
        self.tenant = tenant
        self.branch = branch

    def run_widget(self, widget_key):
        """
        Execute a single widget.
        """

        widget_class = get_widget(widget_key)

        if not widget_class:
            raise ValueError(f"Widget '{widget_key}' not registered")

        widget = widget_class()

        data = widget.get_data(
            tenant=self.tenant,
            branch=self.branch
        )

        return {
            "key": widget.key,
            "title": widget.title,
            "data": data
        }

    def run_widgets(self, widget_keys):
        """
        Execute multiple widgets.
        """

        results = []

        for key in widget_keys:

            widget_class = get_widget(key)

            if not widget_class:
                continue

            widget = widget_class()

            data = widget.get_data(
                tenant=self.tenant,
                branch=self.branch
            )

            results.append({
                "key": widget.key,
                "title": widget.title,
                "data": data
            })

        return results

    def run_all_widgets(self):
        """
        Execute all registered widgets.
        """

        results = []

        for key, widget_class in WIDGET_REGISTRY.items():

            widget = widget_class()

            data = widget.get_data(
                tenant=self.tenant,
                branch=self.branch
            )

            results.append({
                "key": widget.key,
                "title": widget.title,
                "data": data
            })

        return results