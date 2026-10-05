from .context import acting_as


class CurrentUserMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        with acting_as(user if user is not None and user.is_authenticated else None):
            return self.get_response(request)
