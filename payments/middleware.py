"""
Three toy middleware classes whose only job is to log where they are in
the request/response cycle, so demo_middleware_lifecycle.py can capture
the real call order instead of describing it.

Every middleware follows the same shape: __init__ runs once at server
startup and stores get_response (the next thing in the chain -- either
the next middleware, or the view once you're at the end of the list).
__call__ runs on every request; whatever happens BEFORE calling
self.get_response(request) is the "request phase", whatever happens
AFTER is the "response phase". Django builds the chain in MIDDLEWARE
list order, which means:

  - request phase runs top-to-bottom through MIDDLEWARE
  - response phase runs bottom-to-top (each middleware wraps the next,
    like nested parentheses / an onion)

The log lives on `request.middleware_log`, not a module-level list --
each request gets Django's test Client to hand back `response.wsgi_request`,
so the command can read the log for that specific request without one
request's middleware bleeding into another's.
"""

from django.http import HttpResponse


class OuterLifecycleMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.middleware_log = ["Outer: before view (request phase)"]
        response = self.get_response(request)
        request.middleware_log.append("Outer: after view (response phase)")
        return response


class ShortCircuitMiddleware:
    """
    A middleware can return an HttpResponse itself instead of calling
    self.get_response(request) -- when it does, the view AND every
    middleware listed after this one in MIDDLEWARE are skipped entirely.
    Middleware listed BEFORE this one still run their response phase,
    because the call stack unwinds back through them regardless of where
    it stopped going in.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.middleware_log.append("ShortCircuit: before view (request phase)")
        if request.headers.get("X-Block") == "1":
            request.middleware_log.append(
                "ShortCircuit: short-circuiting here -- view and InnerLifecycleMiddleware never run"
            )
            response = HttpResponse("blocked by ShortCircuitMiddleware", status=403)
        else:
            response = self.get_response(request)
        request.middleware_log.append("ShortCircuit: after view (response phase)")
        return response


class InnerLifecycleMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.middleware_log.append("Inner: before view (request phase)")
        response = self.get_response(request)
        request.middleware_log.append("Inner: after view (response phase)")
        return response
