
import typing as t

from .globals import _cv_app
from .globals import _cv_request


def _default_template_ctx_processor() -> dict[str, t.Any]:
    """默认的模版上下文处理器. 注入`request`, `session` 和 `g`."""
    appctx = _cv_app.get(None)
    reqctx = _cv_request.get(None)
    rv: dict[str, t.Any] = {}
    if appctx is not None:
        rv["g"] = appctx.g
    if reqctx is not None:
        rv["request"] = reqctx.request
        rv["session"] = reqctx.session
    return rv
