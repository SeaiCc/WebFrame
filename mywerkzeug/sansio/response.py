import typing as t
from datetime import timedelta, datetime
from myhttp import HTTPStatus

from mywerkzeug.datastructures import Headers
from mywerkzeug.datastructures import HeaderSet
from mywerkzeug.http import HTTP_STATUS_CODES
from mywerkzeug.utils import get_content_type

from ..datastructures import ResponseCacheControl
from ..http import dump_cookie
from ..http import dump_header
from ..http import http_date
from ..http import parse_cache_control_header
from ..http import parse_date
from ..http import parse_set_header
from ..utils import header_property

if t.TYPE_CHECKING:
    from ..datastructures.cache_control import _CacheControl

def _set_property(name: str, doc: str | None = None) -> property:
    def fget(self: Response) -> HeaderSet:
        def on_update(header_set: HeaderSet) -> None:
            if not header_set and name in self.headers:
                del self.headers[name]
            elif header_set:
                self.headers[name] = header_set.to_header()
        
        return parse_set_header(self.headers.get(name), on_update)

    def fset(
        self: Response,
        value: None | (str | dict[str, str | int] | t.Iterable[str]),
    ) -> None:
        if not value:
            del self.headers[name]
        elif isinstance(value, str):
            self.headers[name] = value
        else:
            self.headers[name] = dump_header(value)
        
        return property(fget, fset, doc=doc)



class Response:
    """Represents the non-IO parts of an HTTP response, specifically the
    status and headers but not the body.

    This class is not meant for general use. It should only be used when
    implementing WSGI, ASGI, or another HTTP application spec. Werkzeug
    provides a WSGI implementation at :cls:`werkzeug.wrappers.Response`.

    :param status: The status code for the response. Either an int, in
        which case the default status message is added, or a string in
        the form ``{code} {message}``, like ``404 Not Found``. Defaults
        to 200.
    :param headers: A :class:`~werkzeug.datastructures.Headers` object,
        or a list of ``(key, value)`` tuples that will be converted to a
        ``Headers`` object.
    :param mimetype: The mime type (content type without charset or
        other parameters) of the response. If the value starts with
        ``text/`` (or matches some other special cases), the charset
        will be added to create the ``content_type``.
    :param content_type: The full content type of the response.
        Overrides building the value from ``mimetype``.

    .. versionchanged:: 
    3.0 - The ``charset`` attribute was removed.
    """
    default_status = 200
    default_mimetype: str | None = "text/plain"

    #: cookie超出此大小警告，默认4093， 应安全地被大多数浏览器<cookie_>支持，大于此size的
    #: cookie仍会被发送，但可能被某些浏览器不正确地处理忽略，设置为0禁用检查

    #: .. _`cookie`: http://browsercookielimits.squawky.net/
    max_cookie_size = 4093
    
    # :class:`Headers`对象表示response头
    headers: Headers

    def __init__(
        self,
        status: int | str | HTTPStatus | None = None,
        headers: t.Mapping[str, str | t.Iterable[str]]
        | t.Iterable[tuple[str, str]]
        | None = None,
        mimetype: str | None = None,
        content_type: str | None = None,
    ) -> None:
        if isinstance(headers, Headers):
            self.headers = headers
        elif not headers:
            self.headers = Headers()
        else:
            self.headers = Headers(headers)
        
        if content_type is None:
            if mimetype is None and "content-type" not in self.headers:
                mimetype = self.default_mimetype
            if mimetype is not None:
                mimetype = get_content_type(mimetype, "utf-8")
            content_type = mimetype
        if content_type is not None:
            self.headers["Content-Type"] = content_type
        if status is None:
            status = self.default_status
        self.status = status
    
    @property
    def status_code(self) -> int:
        """The HTTP status code as a number."""
        return self._status_code
    
    @status_code.setter
    def status_code(self, code: int) -> None:
        self.status = code

    @property
    def status(self) -> str:
        """The HTTP status code as a string."""
        return self._status
    
    @status.setter
    def status(self, value: str | int | HTTPStatus) -> None:
        self._status, self._status_code = self._clean_status(value)

    def _clean_status(self, value: str | int | HTTPStatus) -> tuple[str, int]:
        if isinstance(value, (int, HTTPStatus)):
            status_code = int(value)
        else:
            value = value.strip()
            if not value:
                raise ValueError("Empty status argument")
            code_str, sep, _ = value.partition(" ")
            try:
                status_code = int(code_str)
            except ValueError:
                # only message
                return f"0 {value}", 0
            if sep:
                # code and message
                return value, status_code
        
        # only code, look up message
        try:
            status = f"{status_code} {HTTP_STATUS_CODES[status_code].upper()}"
        except KeyError:
            status = f"{status_code} UNKNOWN"
        
        return status, status_code

    def set_cookie(
        self,
        key: str,
        value: str = "",
        max_age: timedelta | int | None = None,
        expires: str | datetime | int | float | None = None,
        path: str | None = "/",
        domain: str | None = None,
        secure: bool = False,
        httponly: bool = False,
        samesite: str | None = None,
        partitioned: bool = False,
    ) -> None:
        """设置cookie
        
        如果cookie header的size超过了:attr:`max_cookie_size`,会抛出警告，但是header
        会被设置

        :param key: 设置cookie的key
        :param value: cookie的value
        :param max_age: 应为秒数，或者如果cookie应持续到客户端的浏览器session，为`None`
        :param expires: 应该为`datetime`对象或者UNIX时间戳
        :param path: 将cookie限制在给定的路径，默认情况下，它会覆盖整个域
        :param domain: 如果你想设置跨域cookie，例如，``domain="example.com``会设置一个
            ``www.example.com``，``foo.example.com``等域名可读的cookie，否则，cookie
            会只被设置的域名可读
        :param secure: 若为``True``, cookie只对HTTPS可用
        :param httponly: 禁用JavaScript获取cookie
        :param samesite: 限制cookie的scope仅为带有"same-site"的请求
        :param partitioned: 若为``True``, cookie将会被分隔
        """
        self.headers.add(
            "Set-Cookie",
            dump_cookie(
                key,
                value=value,
                max_age=max_age,
                expires=expires,
                path=path,
                domain=domain,
                secure=secure,
                httponly=httponly,
                max_size=self.max_cookie_size,
                samesite=samesite,
                partitioned=partitioned,
            )
        )

    def delete_cookie(
        self,
        key: str,
        path: str | None = "/",
        domain: str | None = None,
        secure: bool = False,
        httponly: bool = False,
        samesite: str | None = None,
        partitioned: bool = False,
    ) -> None:
        """删除cookie，如果key不存在，静默失败
        
        :param key: 需要删除的cookie的key名称
        :param path: 如果要删除的cookie仅限于某个路径，路径必须在这里定义
        :param domain: 如果要删除的cookie的仅限于某个域，需要在这里定义
        :param secure: 若``True``, cookie仅HTTPS可用
        :param httponly: 禁止JavaScript访问cookie
        :param semesite: 限制cookie的scope仅为带有"same-site"的请求
        :param partitioned: 若为``True``, cookie将会被分隔
        """
        self.set_cookie(
            key,
            expires=0,
            max_age=0,
            path=path,
            domain=domain,
            secure=secure,
            httponly=httponly,
            samesite=samesite,
            partitioned=partitioned,
        )

    content_length = header_property(
        "Content-Length",
        None,
        int,
        str,
        doc="""The Content-Length entity-header field indicates the size of
        the entity-body, in decimal number of OCTETs, sent to the recipient or,
        in the case of the HEAD method, the size of the entity-body that would 
        have been sent had the request been a GET."""
    )

    last_modified = header_property(
        "Last-Modified",
        None,
        parse_date,
        http_date,
        doc="""The Last-Modified entity-header field indicates the date
        and time at which the origin server believes the variant was
        last modified.
        """,
    )

    vary = _set_property(
        "Vary",
        doc="""The Vary field value indicates the set of request-header
        fields that fully determines, while the response is fresh,
        whether a cache is permitted to use the response to reply to a
        subsequent request without revalidation."""
    )

    @property
    def cache_control(self) -> ResponseCacheControl:
        """ Cache-Contorl general-header 字段用来执行请求/响应链上的所有缓存机制必须
        遵守的指令"""

        def on_update(cache_control: _CacheControl) -> None:
            if not cache_control and "cache-control" in self.headers:
                del self.headers["cache-control"]
            elif cache_control:
                self.headers["Cache-Control"] = cache_control.to_header()
        
        return parse_cache_control_header(
            self.headers.get("cache-control"), on_update, ResponseCacheControl
        )
