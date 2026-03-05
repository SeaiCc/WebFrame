
import typing as t

from ..exceptions import HTTPException
from ..utils import redirect

if t.TYPE_CHECKING:
    from _typeshed.wsgi import WSGIEnvironment

    from ..wrappers.request import Request
    from ..wrappers.response import Response

class RoutingException(Exception):
    """特殊异常，例如需要应用程序重定向、通知缺少 URL 等。"""

class RequestRedirect(HTTPException, RoutingException):
    """如果map需要重定向，抛出。一个例子是`strict_slashes`被激活，并且url需要斜线
    
    属性“new_url”包含绝对目标 URL
    """

    code = 308

    def __init__(self, new_url: str) -> None:
        super().__init__(new_url)
        self.new_url = new_url
    
    def get_response(
        self,
        environ: WSGIEnvironment | Request | None = None,
        scope: dict[str, t.Any] | None = None,
    ) -> Response:
        return redirect(self.new_url, self.code)

class RequestPath(RoutingException):
    """网络错误"""
    __solts__ = ("path_info",)

    def __init__(self, path_info: str) -> None:
        super().__init__()
        self.path_info = path_info

class RequestAliasRedirect(RoutingException):  # noqa: B903
    """这条规则是一个别名，它想要重定向到规范 URL。"""

    def __init__(self, matched_values: t.Mapping[str, t.Any], endpoint: t.Any) -> None:
        super().__init__()
        self.matched_values = matched_values
        self.endpoint = endpoint

class NoMatch(Exception):
    __slots__ = ("have_match_for", "websocket_mismatch")

    def __init__(self, have_match_for: set[str], websocket_mismatch: bool) -> None:
        self.have_match_for = have_match_for
        self.websocket_mismatch = websocket_mismatch