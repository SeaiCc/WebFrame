import typing as t

from myhttp import HTTPStatus

from ..datastructures import Headers
from ..sansio.response import Response as _SansIOResponse
from ..urls import iri_to_uri
from ..wsgi import ClosingIterator
from ..wsgi import get_current_url

if t.TYPE_CHECKING:
    from _typeshed.wsgi import StartResponse
    from _typeshed.wsgi import WSGIEnvironment

def _iter_encoded(iterable: t.Iterable[str | bytes]) -> t.Iterable[bytes]:
    for item in iterable:
        if isinstance(item, str):
            yield item.encode()
        else:
            yield item

class Response(_SansIOResponse):
    """Represents an outgoing WSGI HTTP response with body, status, and
    headers. Has properties and methods for using the functionality
    defined by various HTTP specs.

    The response body is flexible to support different use cases. The
    simple form is passing bytes, or a string which will be encoded as
    UTF-8. Passing an iterable of bytes or strings makes this a
    streaming response. A generator is particularly useful for building
    a CSV file in memory or using SSE (Server Sent Events). A file-like
    object is also iterable, although the
    :func:`~werkzeug.utils.send_file` helper should be used in that
    case.

    The response object is itself a WSGI application callable. When
    called (:meth:`__call__`) with ``environ`` and ``start_response``,
    it will pass its status and headers to ``start_response`` then
    return its body as an iterable.

    .. code-block:: python

        from werkzeug.wrappers.response import Response

        def index():
            return Response("Hello, World!")

        def application(environ, start_response):
            path = environ.get("PATH_INFO") or "/"

            if path == "/":
                response = index()
            else:
                response = Response("Not Found", status=404)

            return response(environ, start_response)

    :param response: The data for the body of the response. A string or
        bytes, or tuple or list of strings or bytes, for a fixed-length
        response, or any other iterable of strings or bytes for a
        streaming response. Defaults to an empty body.
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
    :param direct_passthrough: Pass the response body directly through
        as the WSGI iterable. This can be used when the body is a binary
        file or other iterator of bytes, to skip some unnecessary
        checks. Use :func:`~werkzeug.utils.send_file` instead of setting
        this manually.
    """

    autocorrect_location_header = False
    automatically_set_content_length = True

    response: t.Iterable[str] | t.Iterable[bytes]
    def __init__(
        self,
        response: t.Iterable[bytes] | bytes | t.Iterable[str] | str | None = None,
        status: int | str | HTTPStatus | None = None,
        headers: t.Mapping[str, str | t.Iterable[str]]
        | t.Iterable[tuple[str, str]]
        | None = None,
        mimetype: str | None = None,
        content_type: str | None = None,
        direct_passthrough: bool = False,
    ) -> None:
        super().__init__(
            status=status,
            headers=headers,
            mimetype=mimetype,
            content_type=content_type
        )

        self.direct_passthrough = direct_passthrough
        self._on_close: list[t.Callable[[], t.Any]] = []

        if response is None:
            self.response = []
        elif isinstance(response, (str, bytes, bytearray)):
            self.set_data(response)
        else:
            self.response = response
    
    def iter_encoded(self) -> t.Iterable[bytes]:
        """迭代响应，并使用响应中的encoding对其进行编码， 若响应对象作为一个WSGI应用
        被调用，此方法返回值被用作应用迭代器，除非:attr:`direct_passthrough`被激活
        """
        return _iter_encoded(self.response)

    @property
    def is_sequence(self) -> bool:
        """若迭代器被缓存，此属性为True，当response的属性为list或tuple时，
        response对象会将iterator视作被缓存
        """
        return isinstance(self.response, (list, tuple))

    def close(self) -> None:
        """关闭被包装的reponse。也可以在 with 语句中使用该对象，它会自动关闭该对象。"""
        if hasattr(self.response, "close"):
            self.response.close()
        for func in self._on_close:
            func()

    def set_data(self, value: bytes | str):
        """Sets a new string as response. The value must be a string or
        bytes. If a string is set it's encoded to the charset of the
        response (utf-8 by default).
        """
        value = value.encode()
        self.response = [value]
        if self.automatically_set_content_length:
            self.headers["Content-Length"] = str(len(value))

    def get_wsgi_headers(self, environ: WSGIEnvironment) -> Headers:
        """This is automatically called right before the response is started
        and returns headers modified for the given environment. It returns a
        copy of the headers from the response with some modifications applied
        if necessary.
        
        For example the location header (if present) is joined with the root
        URL of the environment. Also the content length is automatically set
        to zero here for certain status codes.

        .. versionchanged:: 0.6
            Previously that function was called (fix_headers) and modified
            the response object in place. Also since 0.6 IRIs in location
            and content-location headers are handled properly.

            Also starting with 0.6, Werkzeug will attempt to set the content
            length if it is able to figure it out on its own. This is the 
            case if all strings in the response iterable are already
            encoded and the iterable is buffered.
        
        :param environ: theWSGI environment of the request.
        :return: returns a new class (werkzeug.datastructures.Headers) obj
        """
        headers = Headers(self.headers)
        location: str | None = None
        content_location: str | None = None
        content_length: str | int | None = None
        status = self.status_code

        for key, value in headers:
            ikey = key.lower()
            if ikey == "location":
                location = value
            elif ikey == "content-location":
                content_location = value
            elif ikey == "content-length":
                content_length = value
        if location is not None:
            location = iri_to_uri(location)

            if self.autocorrect_location_header:
                # Make the location header an absolute URL.
                current_url = get_current_url(environ, strip_querystring=True)
                current_url = iri_to_uri(current_url)
                location = urljoin(current_url, location)
            
            headers["Location"] = location
        
        # make sure the content location is a URL
        if content_location is not None:
            headers["Content-Location"] = iri_to_uri(content_location)
        
        if 100 <= status < 200 or status == 204:
            # Per section 3.3.2 of RFC 7230, "a server MUST NOT send a
            # Content-Length header field in any response with a status
            # code of 1xx (Informational) or 204 (No Content)."
            headers.remove("Content-Length")
        elif status == 304:
            remove_entity_headers(headers)

        # if we can determine the content length automatically, we
        # should try to do that.  But only if this does not involve
        # flattening the iterator or encoding of strings in the
        # response. We however should not do that if we have a 304
        # response.
        if (
            self.automatically_set_content_length
            and self.is_sequence
            and content_length is None
            and status not in (204, 304)
            and not (100 <= status < 200)
        ):
            content_length = sum(len(x) for x in self.iter_encoded())
            headers["Content-Length"] = str(content_length)
        return headers

    def get_app_iter(self, environ: WSGIEnvironment) -> t.Iterable[bytes]:
        """返回给定environ的应用迭代器。根据请求方法和当前状态，返回值可能是
        空响应而不是reponse中的一个。
        
        如果请求方法是`HEAD`或者状态码在 HTTP 规范要求返回空响应的范围内
        ，则返回一个空的可迭代对象。

        :param environ: 请求中的WSGI环境变量。
        :return: 响应迭代器
        """
        status = self.status_code
        if (
            environ["REQUEST_METHOD"] == "HEAD"
            or 100 <= status < 200
            or status in (204, 304)
        ):
            iterable: t.Iterable[bytes] = ()
        elif self.direct_passthrough:
            return self.response
        else:
            iterable = self.iter_encoded()
        return ClosingIterator(iterable, self.close)

    def get_wsgi_response(
            self, environ: WSGIEnvironment
    ) -> tuple[t.Iterable[bytes], str, list[tuple[str, str]]]:
        """Returns final WSGI response as tuple. The first item in
        the tuple is the application iterator, the second the status and
        the third the list of headers. The response returned is created
        specially for the given environment. For example if the request
        method in the WSGI environment is (HEAD) the response will be
        empty and only the headers and status code will be present.
        
        :param environ: the WSGI environment of the request.
        :return: an (app_iter, status, headers) tuple.
        """
        headers = self.get_wsgi_headers(environ)
        app_iter = self.get_app_iter(environ)
        return app_iter, self.status, headers.to_wsgi_list()

    def __call__(
        self, environ: WSGIEnvironment, start_response: StartResponse
    ) -> t.Iterable[bytes]:
        """Process this response as WSGI application.
        
        :param environ: the WSGI environment.
        :param start_response: the response callable provied by the WSGI server.
        :return: an application iterator
        """
        app_iter, status, headers = self.get_wsgi_response(environ)
        start_response(status, headers)
        return app_iter
