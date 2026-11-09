"""A random id for every web request, returned in the X-Request-ID header and stored on the
activity-log entries the request writes, so a person's "what happened at 10:42?" can be matched
to exactly those entries.

The id is always made here: one sent by the client is ignored, so it can't be forged to tie
someone else's request to a log entry.
"""

import uuid
from contextvars import ContextVar

_current = ContextVar("request_id", default="")


def current_request_id():
    """The id of the request being handled, or "" outside one (a background job, a command)."""
    return _current.get()


class RequestIDMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.id = uuid.uuid4().hex
        token = _current.set(request.id)
        try:
            response = self.get_response(request)
        finally:
            _current.reset(token)
        response["X-Request-ID"] = request.id
        return response
