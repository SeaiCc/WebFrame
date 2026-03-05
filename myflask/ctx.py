
import contextvars
import sys
import typing as t

from mywerkzeug.exceptions import HTTPException

from . import typing as ft
from .globals import _cv_app
from .globals import _cv_request
from .signals import appcontext_pushed

if t.TYPE_CHECKING: # pragma: no cover
    from _typeshed.wsgi import WSGIEnvironment

    from .app import Flask
    from .sessions import SessionMixin
    from .wrappers import Request

# 用于参数默认值和单例哨兵值
_sentinel = object()

class _AppCtxGlobals:
    """一个普通对象，作为app context中存储数据的命名空间
    
    创建app context时自动创建此对象，以:data:`g`代理形式提供

    .. describe:: 'key' in g
        检查属性是否存在

    .. describe:: iter(g)
        返回属性名称的迭代器
    """

    # 定义 attr方法使得mypy知道这是一个具有任意属性的命名空间对象
    pass

class AppContext:
    """app context 包含application特定的信息。在请求开始时若app context没有被激活
    则会创建一个并压栈。当执行CLI命令时也会被压栈
    """
    def __init__(self, app: Flask) -> None:
        self.app = app
        self.url_adapter = app.create_url_adapter(None)
        self.g: _AppCtxGlobals = app.app_ctx_globals_class()
        self._cv_tokens: list[contextvars.Token[AppContext]] = []

    def push(self) -> None:
        """将app context和当前context绑定"""
        self._cv_tokens.append(_cv_app.set(self))
        appcontext_pushed.send(self.app, _async_wrapper=self.app.ensure_sync)

    def pop(self, exc: BaseException | None = _sentinel) -> None: #type: ignore
        """pop app context """
        try:
            if len(self._cv_tokens) == 1:
                if exc is _sentinel:
                    exc = sys.exc_info()[1]
                self.app.do_teardown_appcontext(exc)
        finally:
            ctx = _cv_app.get()
            _cv_app.reset(self._cv_tokens.pop())
        
        if ctx is not self:
            raise AssertionError(
                f"Popped wrong app context. ({ctx!r} instead of {self!r})"
            )

class RequestContext:
    """request context 包含先前请求的信息。在请求开始时创建并压栈，之后在请求结束弹出
    它会根据提供的WSGI environment创建URL adapter和reqeust对象

    不要尝试直接使用这个类，而是使用:meth:`~myflask.Flask.test_request_context`和
    :meth:`~myflask.Flask.request_context`来创建对象

    当reqeust context 出栈时，他将评估所有应用上注册的用于清理执行的方法
    (:meth:`~myflask.Flask.teardown_request`).

    request context在请求结束会自动出栈，当使用可交互debugger时，context会被存储
    因此``request``仍然可访问。相同的，测试客户端可以在reqeust结束重新请求context
    然而，清理方法可能早已关闭了某些资源，如数据库连接
    """
    def __init__(
            self, 
            app: Flask, 
            environ: WSGIEnvironment,
            request: Request | None = None,
            session: SessionMixin | None = None,
    ) -> None:
        self.app = app
        if request is None:
            request = app.request_class(environ)
            request.json_module = app.json
        self.request: Request = request
        self.url_adapter = None
        try:
            self.url_adapter = app.create_url_adapter(request)
        except HTTPException as e:
            self.request.routing_exception = e
        self.flashes: list[tuple[str, str]] | None = None
        self.session: SessionMixin | None = session
        # request之后应在response上执行的方法。这些应在常规的"after_request"方法前执行
        self._after_request_functions: list[ft.AfterRequestCallable[t.Any]] = []

        self._cv_tokens: list[
            tuple[contextvars.Token[RequestContext], AppContext | None]
        ] = []

    def match_request(self) -> None:
        """可以由子类重写以参与请求的匹配"""
        try:
            result = self.url_adapter.match(return_rule=True) # type: ignore
            self.request.url_rule, self.request.view_args = result # type: ignore
        except HTTPException as e:
            self.request.routing_exception = e

    def push(self) -> None:
        # 在将request context压栈前，需要确保没有application context
        app_ctx = _cv_app.get(None)

        if app_ctx is None or app_ctx.app is not self.app:
            app_ctx = self.app.app_context()
            app_ctx.push()
        else:
            app_ctx = None
        
        self._cv_tokens.append((_cv_request.set(self), app_ctx))

        # 在request context 可用时开启session. 这允许一个自定义方法来使用request context
        # 仅当request第一次压栈时才会开启一个新session，否则 stream_with_context丢弃
        # 这个session
        if self.session is None:
            session_interface = self.app.session_interface
            self.session = session_interface.open_session(self.app, self.request)

            if self.session is None:
                self.session = session_interface.make_null_session(self.app)
        
        # 加载session之后匹配request URL，这样session在自定义URL 转换器中可用
        if self.url_adapter is not None:
            self.match_request()

    def pop(self, exc: BaseException | None = _sentinel) -> None: # type: ignore
        """pop出request context 并取消绑定，这也会触发:meth:`~myflask.Flask.teardown_request`
        装饰器注册的函数的执行
        """

        clear_request = len(self._cv_tokens) == 1

        try:
            if clear_request:
                if exc is _sentinel:
                    exc = sys.exc_info()[1]
                self.app.do_teardown_request(exc)

                request_close = getattr(self.request, "close", None)
                if request_close is not None:
                    request_close()
        finally:
            ctx = _cv_request.get()
            token, app_ctx = self._cv_tokens.pop()
            _cv_request.reset(token)

            # request结束消除循环依赖, 因此不需要启动GC
            if clear_request:
                ctx.request.environ["mywerkzeug.request"] = None
            
            if app_ctx is not None:
                app_ctx.pop(exc)
            
            if ctx is not self:
                raise AssertionError(
                    f"Popped wrong request context. ({ctx!r} instead of {self!r})"
                )
        