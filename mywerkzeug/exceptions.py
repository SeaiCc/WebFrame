import typing as t

from markupsafe import escape

from mywerkzeug._internal import _get_environ

if t.TYPE_CHECKING:
    from _typeshed.wsgi import WSGIEnvironment
    
    from mywerkzeug.sansio.response import Response as SansIOResponse
    from mywerkzeug.wrappers.request import Request as WSGIRequest
    from mywerkzeug.wrappers.response import Response as WSGIResponse

class HTTPException(Exception):
    """The base class for all HTTP exception. This exception can be called as a
    WSGI appliciton to render a default error page or you can catch the subclasses
    of it independently and render nicer erro messages.
    
    .. versionchanged:: 
    2.1 - Removed the (wrap) class method.
    """

    code: int | None = None
    description: str | None = None

    def __init__(
        self,
        description: str | None = None,
        response: SansIOResponse | None = None,
    ) -> None:
        super().__init__()
        if description is not None:
            self.description = description
        self.response = response
    
    @property
    def name(self) -> str:
        """The status name."""
        from .http import HTTP_STATUS_CODES

        return HTTP_STATUS_CODES.get(self.code, "Unknown Error") # type: ignore
    
    def get_description(
        self,
        environ: WSGIEnvironment | None = None,
        scope: dict[str, t.Any] | None = None,
    ) -> str:
        """Get the description."""
        if self.description is None:
            description = ""
        else:
            description = self.description

    def get_body(
        self,
        environ: WSGIEnvironment | None = None,
        scope: dict[str, t.Any] | None = None,
    ) -> str:
        """Get the HTML body."""
        return (
            "<!doctype html>\n"
            "<html lang=en>\n"
            f"<title>{self.code} {escape(self.name)}</title>\n"
            f"<h1>{escape(self.name)}</h1>\n"
            f"{self.get_description(environ)}\n"
        )

    def get_headers(
        self, 
        environ: WSGIEnvironment | None = None,
        scope: dict[str, t.Any] | None = None,
    ) -> list[tuple[str, str]]:
        """Get a list of headers."""
        return [("Content-Type", "text/html; charset=utf-8")]

    @t.overload
    def get_reponse(
        self,
        environ: WSGIEnvironment | WSGIRequest | None = ...,
        scope: None = None,
    ) -> WSGIResponse: ...
    @t.overload
    def get_response(
        self,
        environ: None = None,
        scope: dict[str, t.Any] = ...,
    ) -> SansIOResponse: ...
    def get_response(
        self,
        environ: WSGIEnvironment | WSGIRequest | None = None,
        scope: dict[str, t.Any] | None = None,
    ) -> WSGIResponse | SansIOResponse:
        """Get a response object.
        
        :param environ: A WSGI environ dict or request object. If given, may be
            used to customize the response based on the request.
        :param scope: An ASGI scope dict. If give, may be used to customize the
            response based on the request.
        :return: A WSGI class (mywerkzeug.wrappers.Reponse) if called without
            arguments or with (envion). A sans-IO class (mywerkzeug.sansio.Response)
            for ASGI if called with (scope).
        """
        from .wrappers.response import Response
        if self.response is not None:
            return self.response
        if environ is not None:
            environ = _get_environ(environ)
        headers = self.get_headers(environ, scope)
        return Response(self.get_body(environ, scope), self.code, headers)

class BadRequest(HTTPException):
    """*400* Bad Request
    
    Raise if brower sends somthing to the application the application
    or server cannot handle.
    """
    code = 400
    description = (
        "The browser (or proxy) sent a request that this server could not understand."
    )

class BadRequestKeyError(BadRequest, KeyError):
    """An exception that is used to singl both a (exeception.KeyError) and a
    exeception.BadRequest. Used by many of the datastructures.
    """

    def __init__(self, arg: object | None = None, *args: t.Any, **kwargs: t.Any):
        super().__init__(*args, **kwargs)

        if arg is None:
            KeyError.__init__(self)
        else:
            KeyError.__init__(self, arg)

class SecurityError(BadRequest):
    """Raised if something triggers a security error.  
    This class just for differ with a bad request error.
    """

class InternalServerError(HTTPException):
    """*500* 服务器内部错误
    
    内部服务器错误时抛出，若调度程序中发生位置错误，这是一个很好的fallback
    """
    code = 500
    description = (
        "The server encontered an internal error and was unable to"
        " complete your request. Either the server is overloaded or"
        " there is an error in the application."
    )

    def __init__(
        self,
        description: str | None = None,
        response: SansIOResponse | None = None,
        original_exception: BaseException | None = None
    ) -> None:
        # 导致此 500 错误的原始异常。框架可以使用此异常在处理意外错误时提供上下文信息。
        self.original_exception = original_exception
        super().__init__(description=description, response=response)
        