class BaseWidget:
    key = None
    name = None

    def __init__(self, request):
        self.request = request
        self.tenant = getattr(request, "tenant", None)

    def get_data(self):
        raise NotImplementedError("Each widget must implement get_data method")