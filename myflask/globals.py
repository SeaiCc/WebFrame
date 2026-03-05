import typing as t

from contextvars import ContextVar

from mywerkzeug.local import LocalProxy

if t.TYPE_CHECKING: # pragma: no cover
    from .app import Flask
    from .ctx import AppContext
    from .ctx import RequestContext
    from .wrappers import Request

_no_app_msg = """\
Working outside of application context.

This typically means that you attempted to use functionality that needed
the current application. To solve this, set up an application context
with app.app_context(). Set the documentation for more information.\
"""

_cv_app: ContextVar[AppContext] = ContextVar("myflask.app_ctx")

current_app: Flask = LocalProxy( # type: ignore[assignment]
    _cv_app, "app", unbound_message=_no_app_msg
)

_no_req_msg = """\
Working outside of request context.

This typically means tha you attempted to use functionality that needed
an active HTTP request. Consult the documentation on testing for 
information about how to avoid this problem.\
"""
_cv_request: ContextVar[RequestContext] = ContextVar("myflask.request_ctx")
request_ctx: RequestContext = LocalProxy( # type: ignore[assignment]
    _cv_request, unbound_message = _no_req_msg
)
request: Request = LocalProxy( # type: ignore[assignment]
    _cv_request, "request", unbound_message=_no_req_msg
)
