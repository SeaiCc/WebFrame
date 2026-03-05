import collections.abc as cabc
import os
import sys
import typing as t
import weakref
from datetime import timedelta
from inspect import iscoroutinefunction
from itertools import chain
from types import TracebackType

import click
from mywerkzeug.datastructures import ImmutableDict
from mywerkzeug.exceptions import HTTPException
from mywerkzeug.exceptions import InternalServerError
from mywerkzeug.routing import MapAdapter
from mywerkzeug.routing import Rule
from mywerkzeug.serving import is_running_from_reloader
from mywerkzeug.wrappers import Response as BaseResponse
from mywerkzeug.wsgi import get_host

from . import cli
from . import typing as ft
from .ctx import AppContext
from .ctx import RequestContext
from .globals import _cv_app
from .globals import _cv_request
from .globals import current_app
from .globals import request
from .globals import request_ctx
from .helpers import get_debug_flag
from .helpers import get_load_dotenv
from .helpers import send_from_directory
from .sansio.app import App
from .sansio.scaffold import _sentinel
from .sessions import SecureCookieSessionInterface
from .sessions import SessionInterface
from .signals import appcontext_tearing_down
from .signals import got_request_exception
from .signals import request_finished
from .signals import request_started
from .signals import request_tearing_down
from .wrappers import Request
from .wrappers import Response

if t.TYPE_CHECKING:
    from _typeshed.wsgi import StartResponse
    from _typeshed.wsgi import WSGIEnvironment

    from .typing import HeadersValue

class Flask(App):
    """flask obj实现了一个WSGI应用并作为一个核心obj.它传递应用的模块或包的名称。
    一旦被创建，将作为视图函数的中央注册表， URL规则，模板注册表以及更多功能
    
    包名被用于解析包内部或者模块所在文件夹解析资源，具体取决于package参数被解析为
    一个实际的python包(包含:file:`__init__.py`的文件夹)还是一个标准模块(一个
    ``.py``文件)

    想查看更多资源加载的信息，参考:func:`open_resource`.

    通常你像下面这样创建一个Flask实例在你的main模块或者包的:file:`__init__.py`文件中:

        from myflask import Flask
        app = Flask(__name__)
    
    .. 警告:: 关于第一个参数

        第一个参数的作用是让Flask了解哪些内容属于您的应用程序。这个名字用于从文件系统中
        找到资源，这些功能可以被扩展程序利用，以提升调试信息，以及其他更多.

        所以你这里提供的内容很重要，如果你使用了单个模块，`__name__`总是正确值。然而
        如果你使用了一个包，通常建议在这里硬编码在你的包名。

        例如你的应用定义在:file:`yourapplication/app.py`，你应使用一下两种方法之一：

            app = Flask('yourapplication')
            app = Flask(__name__.split('.')[0])
        
        由于资源查找的方式，即使使用了`__name__` 也能使应用程序正常运行。然而可能使
        调试更痛苦。某些扩展程序可以根据您的应用程序的导入名称来进行假设判断。例如
        Flask-SQLAlchemy扩展在debug模式下会搜索应用中触发SQL查询的代码。若import
        name没有被合适地设置，调试信息会丢失。（例如仅会找到`yourapplication.app`
        中的SQL查询，而不会找`yourapplication.views.frontend`）

    :param import_name: application package的名称
    :param static_url_path: 被用来指定web上静态文件的特定路径。默认是
                            `static_folder`文件夹的名称
    :param static_folder: 在`static_url_path`中用于提供静态文件的目录。与应用的
                          ``root_path``相关，或者是一个绝对路径，默认``'static'``.
    :param static_host: 当添加静态路由时使用的host。默认None，当使用
                        ``host_matching=True``和``static_folder``时需要指定。
    :param host_matching: 设置 ``url_map.host_matching`` 属性，默认None
    :param subdomain_matching: 当进行路由匹配时，考虑与:data:`SERVER_NAME`相关的
                               子域名。默认为Flase
    :param template_folder: 包含被application使用模板的目录。默认使用应用程序目录
                            下的``templates``文件夹
    :param instance_path: 应用程序的另一个实例路径，默认位于包模块同级的``'instance'``
                          目录为实例路径
    :param instance_relative_config: 若设置为True，用于加载配置时的相对文件名将被假定为                               相对于实例路径而非应用的根目录
    :param root_path: 应用文件的根路径。仅当无法自动检测时应该手动设置，如包的命名空间
    """

    default_config = ImmutableDict(
        {
            "DEBUG": None,
            "TESTING": False,
            "PROPAGATE_EXCEPTIONS": None,
            "SECRET_KEY": None,
            "SECRET_KEY_FALLBACKS": None,
            "PERMANENT_SESSION_LIFETIME": timedelta(days=31),
            "USE_X_SENDFILE": False,
            "TRUSTED_HOSTS": None,
            "SERVER_NAME": None,
            "APPLICATION_ROOT": "/",
            "SESSION_COOKIE_NAME": "session",
            "SESSION_COOKIE_DOMAIN": None,
            "SESSION_COOKIE_PATH": None,
            "SESSION_COOKIE_HTTPONLY": True,
            "SESSION_COOKIE_SECURE": False,
            "SESSION_COOKIE_PARTITIONED": False,
            "SESSION_COOKIE_SAMESITE": None,
            "SESSION_REFRESH_EACH_REQEST": True,
            "MAX_CONTENT_LENGTH": None,
            "MAX_FORM_MEMORY_SIZE": 500_000,
            "MAX_FORM_PARTS": 1_000,
            "SEND_FILE_MAX_AGE_DEFAULT": None,
            "TRAP_BAD_REQUEST_ERRORS": None,
            "TRAP_HTTP_EXCEPTIONS": False,
            "EXPLAIN_TEMPLATE_LOADING": False,
            "PREFERRED_URL_SCHEME": "http",
            "TEMPLATES_AUTO_RELOAD": None,
            "MAX_COOKIE_SIZE": 4093,
            "PROVIDE_AUTOMATIC_OPTIONS": True,
        }
    )

    # 用于请求对象的类，更多信息参考:class:`~myflaskRequest`
    request_class: type[Request] = Request

    #: 用于response对象的类，参考:class:`~myflask.Response`
    response_class: type[Response] = Response

    # 要使用的session interface。默认是:class:`~myflask.sessions.SessionInterface`
    # 的实例
    session_interface: SessionInterface = SecureCookieSessionInterface()

    def __init__(
        self,
        import_name: str,
        static_url_path: str | None = None,
        static_folder: str | os.PathLike[str] | None = "static",
        static_host: str | None = None,
        host_matching: bool = False,
        subdomain_matching: bool = False,
        template_folder: str | os.PathLike[str] | None = "templates",
        instance_path: str | None = None,
        instance_relative_config: bool = False,
        root_path: str | None = None,
    ):
        super().__init__(
            import_name=import_name,
            static_url_path=static_url_path,
            static_folder=static_folder,
            static_host=static_host,
            host_matching=host_matching,
            subdomain_matching=subdomain_matching,
            template_folder=template_folder,
            instance_path=instance_path,
            instance_relative_config=instance_relative_config,
            root_path=root_path,
        )

        # 使用提供的static_url_path, static_host 和 static_folder（如果有）添加一个
        # 静态路由。注意没有检查static_folder是否存在. 首先，可能在运行时创建(如开发
        # 环境)，其次，谷歌引擎会将他存储在某个地方
        if self.has_static_folder:
            assert bool(static_host) == host_matching, (
                "Invalid static_host/host_matching combination"
            )
            # 使用weakref 来避免在app和view function之间创建一个循环引用（see#3761）
            self_ref = weakref.ref(self)
            self.add_url_rule(
                f"{self.static_url_path}/<path:filename>",
                endpoint="static",
                host=static_host,
                view_func=lambda **kw: self_ref().send_static_file(**kw), # type: ignore # noqa: B950
            )

    def get_send_file_max_age(self, filename:str | None) -> int | None:
        """被:func:`send_file`使用,当没有传递时决定给定文件路径``max_age``的缓存值
        
        默认，从:data:`~myflask.current_app`的配置中返回:data:`SEND_FILE_MAX_AGE_DEFAULT`
        默认为``None``告诉浏览器使用条件请求而不是时间缓存，通常来说要有限

        注意这是Flask中同名方法的重复
        """
        value = current_app.config["SEND_FILE_MAX_AGE_DEFAULT"]

        if value is None: return None

        if isinstance(value, timedelta):
            return int(value.total_seconds())
        
        return value # type: ignore[no-any-return]

    def send_static_file(self, filename: str) -> Response:
        """用来从:attr:`static_folder`中提供文件的view function。如果设置了
        :attr:`static_folder`，在:attr:`static_url_path`会自动给这个view注册路由

        注意这是Flask中同名方法的重复
        """
        if not self.has_static_folder:
            raise RuntimeError("'static_folder' must be set to serve static_files")

        # app中send_file只知道调用get_send_file_max_age,这里调用这样蓝图也能工作
        max_age = self.get_send_file_max_age(filename)
        return send_from_directory(
            t.cast(str, self.static_folder), filename, max_age=max_age
        )

    def create_url_adapter(self, request: Request | None) -> MapAdapter | None:
        """为给定的请求创建URL adapter。URL adapter会在request context没有被设置时
        创建，因此请求你是被显式传递的。

        如果设置了:data:`SERVER_NAME`被设置，对于``subdomain_matching``和
        ``host_matching``，requests不会仅限于该域
        """
        if request is not None:
            if (trusted_hosts := self.config["TRUSTED_HOSTS"]) is not None:
                request.trusted_hosts = trusted_hosts

            # 在 bind_to_environ执行之前检查trusted_hosts
            request.host = get_host(request.environ, request.trusted_hosts) # pyright: ignore
            sudomain = None
            server_name = self.config["SERVER_NAME"]

            if self.url_map.host_matching:
                # 不要传递SERVER_NAME, 否则将使用它并忽略主机，会导致host匹配破坏
                server_name = None
            elif not self.subdomain_matching:
                # Werkzeug 没有实现subdomain匹配。将子域名强制设置为默认值或者空字串来
                # 禁用它
                subdomain = self.url_map.default_subdomain or ""
            
            return self.url_map.bind_to_environ(
                request.environ, server_name=server_name, subdomain=subdomain
            )

        # 至少需要SERVER_NAME来匹配/构建 在request之外
        if self.config["SERVER_NAME"] is not None:
            return self.url_map.bind(
                self.config["SERVER_NAME"],
                script_name=self.config["APPLICATION_ROOT"],
                url_scheme=self.config["PREFERRED_URL_SCHEME"],
            )
        
        return None

    def run(
        self,
        host: str | None = None,
        port: int | None = None,
        debug: bool | None = None,
        load_dotenv: bool = True,
        **options: t.Any,
    ) -> None:
        """运行本地开发服务器。

        生产设置中不要使用``run()``.并非为满足生产服务器的安全和性能要求。
        参考:doc:`/deploying/index`来获取WSGI server 推荐

        如果:attr:`debug`被设置，当代码发生改变时，服务器会自动重新加载。异常发生时，
        会展示一个debugger

        如果像启动debug模式，但是想禁用交互debugger的代码执行，可以传递
        ``use_evalex=False``作为参数，这样可以保持屏幕激活的debugger的traceback，
        而禁用代码执行

        不建议在开发过程中启动自动重载，因为支持很差。而应使用:command:`myflask`的`run`命令

        .. admonition:: Keep in Mind

            Flask 会使用通用页面错误来抑制任何服务器错误，除非是debug模式。因此，要仅启用
            交互式debugger，而不重载代码，必须执行:meth:`run` 并设置``debug=True``和
            ``use_reloader=False``.非debug模式下设置``use_debugger``为``True``
            不会捕获任何异常，因为没有任何异常
        
        :param host: 要监听的主机。默认是 ``'127.0.0.1'`` 或 config 变量中的
                     `SERVER_NAME`(若设置)。设置为 ``'0.0.0.0'`` 来监听所有可用的host。
        :param port: webserver的端口。默认是 ``5000``或者定义在``SERVER_NAME``配置变量
                     中的端口(如果有)。
        :param debug: 是否启用调试模式。参考:attr:`debug`
        :param load_dotenv: 加载最近的:file:`.env`和:file:`.flaskenv`文件来设置环境
                     变量。同时将工作目录更改为包含找到的第一个文件的目录。
        :param options: 要转发到底层 Werkzeug 服务器的选项。有关更多信息，
                    请参阅 :func:`werkzeug.serving.run_simple`。
        """

        # 忽略此次调用，这样如果`flask run` 使用时不会启动另一个服务
        if os.environ.get("FLASK_RUN_FROM_CLI") == "true":
            if not is_running_from_reloader():
                click.secho(
                    " * Ignoring a call to 'app.run()' that would block"
                    " the current 'flask' CLI command.\n"
                    "   Only call 'app.run()' in an 'if __name__ =="
                    ' "__main__"\' guard.',
                    fg="red",
                )
            return

        if get_load_dotenv(load_dotenv):
            cli.load_dotenv()

            # 若设置，环境变量覆盖现有值
            if "FLASK_DEBUG" in os.environ:
                self.debug = get_debug_flag()
        
        # debug 传递到method覆盖所有其他资源
        if debug is not None:
            self.debug = bool(debug)
        
        server_name = self.config.get("SERVER_NAME")
        sn_host = sn_port = None

        if server_name:
            sn_host, _, sn_port = server_name.partition(":")

        if not host:
            if sn_host:
                host = sn_host
            else:
                host = "127.0.0.1"
        
        if port or port == 0:
            port = int(port)
        elif sn_port:
            port = int(sn_port)
        else:
            port = 5000
        
        options.setdefault("use_reloader", self.debug)
        options.setdefault("use_debugger", self.debug)
        options.setdefault("threaded", True)

        cli.show_server_banner(self.debug, self.name)

        from mywerkzeug.serving import run_simple

        try:
            run_simple(t.cast(str, host), port, self, **options)
        finally:
            # 如果开发服务器正常重制， 重置第一次请求信息。这样可以不需要reloader和
            # 交互shell的stuff来重启服务
            self._got_first_request = False

    def handle_exception(self, e: Exception) -> Response:
        """处理一个没有错误处理器关联的异常，或者从错误处理器抛出的异常。总会触发
        500的``InternalServerError``异常

        总会发送:data:`got_request_exception`信号

        如果:data:`PROPAGATE_EXCEPTIONS`为``True``,如debug模式，错误会被抛出，
        调试器展示，否则，原始错误会被打印，返回
        :exec:`~mywerkzeug.exceptions.InternalServerError`
        
        如果错误处理器被注册为``InternalServerError``或``500``, 它会被使用
        为保证一致性，handler总是会接收到``InternalServerError``.原始的未被处理的
        异常可以通过``e.original_exception``获取
        """
        exc_info = sys.exc_info()
        got_request_exception.send(self, _async_wrapper=self.ensure_sync, exception=e)
        propagate = self.config["PROPAGATE_EXCEPTIONS"]

        if propagate is None:
            propagate = self.testing or self.debug
        
        if propagate:
            # 如果带有激活异常的调用会重新抛出，否则抛出传入的异常
            if exc_info[1] is e:
                raise

            raise

        self.log_exception(exc_info)
        server_error: InternalServerError | ft.ResponseReturnValue
        server_error = InternalServerError(original_exception=e)
        handler = self._find_error_handler(server_error, request.blueprints)

        if handler is not None:
            server_error = self.ensure_sync(handler)(server_error)
        
        return self.finalize_request(server_error, from_error_handler=True)

    def log_exception(
        self,
        exc_info: (tuple[type, BaseException, TracebackType] | tuple[None, None, None]),
    ) -> None:
        """打印异常，由:meth:`handle_exception`调用，如果debugging未启用并且正好
        在handler调用之前，默认的实现打印exception作为:attr:`logger`的错误"""
        self.logger.error(
            f"Exception on {request.path} [{request.method}]", exc_info=exc_info
        )

    def dispatch_request(self) -> ft.ResponseReturnValue:
        """做请求分发，匹配URL并返回view或者error handler的返回值，不一定非要是Response
        对象，为了将返回值转换为真正的response对象，调用:func:`make_response`
        """

        req = request_ctx.request
        if req.routing_exception is not None:
            self.raise_routing_exception(req)
        rule: Rule = req.url_rule # type: ignore[assignment]
        # 如果我们提供了URL的自动选项，请求是以OPTIONS方法发出的，会自动回应
        if (
            getattr(rule, "provide_automatic_options", False)
            and req.method == "OPTIONS"
        ):
            return self.make_default_options_response()
        # 否则给endpoint分发handler
        view_args: dict[str, t.Any] = req.view_args # type: ignore[assignment]
        return self.ensure_sync(self.view_functions[rule.endpoint])(**view_args) # type: ignore[no-any-return]
        

    def full_dispatch_request(self) -> Response:
        """分发请求，并在此基础上执行预处理后处理，以及HTTP异常捕获和错误处理"""
        self._got_first_request = True

        # try:
        request_started.send(self, _async_wrapper=self.ensure_sync)
        rv = self.preprocess_request()
        if rv is None:
            rv = self.dispatch_request()
        # except Exception as e:
        #     rv = self.handler_user_exception(e)
        return self.finalize_request(rv)

    def finalize_request(
        self,
        rv: ft.ResponseReturnValue | HTTPException,
        from_error_handler: bool = False,
    ) -> Response:
        """根据view的返回值，这一操作会完成对请求的处理，将其转换为响应，并调用后续处理
        任务，再普通的请求分发和错误处理都会调用
        
        这意味这它可能因为某种故障被调用，这时会有一个特殊的安全模式可用，可以通过
        `from_error_handler` flag来开启，如果启用，响应处理的失败会被打印，否则忽略
        """
        response = self.make_response(rv)
        try:
            response = self.process_response(response)
            request_finished.send(
                self, _async_wrapper=self.ensure_sync, response=response
            )
        except Exception:
            if not from_error_handler:
                raise
            self.logger.exception(
                "Request finalizing failed with an error while handling an error"
            )
        return response

    def make_default_options_response(self) -> Response:
        """此方法调用来创建默认``OPTIONS``响应。可以被子类重写改变``OPTIONS``响应行为"""

        adapter = request_ctx.url_adapter
        methods = adapter.allowed_methods() # type: ignore[union-attr]
        rv = self.response_class()
        rv.allow.update(methods)
        return rv

    def ensure_sync(self, func: t.Callable[..., t.Any]) -> t.Callable[..., t.Any]:
        """确保对于WSGI wokers 方法是同步的。Plain ``def``方法返回as-is。``async def``
        方法映射为run并等待response

        重写该方法改变app运行异步view
        """
        if iscoroutinefunction(func):
            return self.async_to_sync(func)

        return func

    def async_to_sync(
        self, func: t.Callable[..., t.Coroutine[t.Any, t.Any, t.Any]]
    ) -> t.Callable[..., t.Any]:
        """返回一个要运行协程的同步方法
        
        .. code-block:: python

            result = app.async_to_sync(func)(*args, **kwargs)

        重写方法来改变app将异步方法转换为同步方法的方式
        """
        try:
            from asgiref.sync import async_to_sync as asgiref_async_to_sync
        except ImportError:
            raise RuntimeError(
                "Install Flask with the `async` extra in order to use async views."
            ) from None
        
        return asgiref_async_to_sync(func)

    def make_response(self, rv: ft.ResponseReturnValue) -> Response:
        """将view function的返回值转换为:attr:`response_class`的实例
        
        :param rv: view function的返回值，view function必须返回一个response。
            返回``None``,或者view最后没有返回，如果不允许。以下类型被``view_rv``允许
        
            ``str``
                创建一个响应对象，body部分以UTF-8编码的字符串

            ``bytes``
                创建body部分是字节的响应对象

            ``dict``
                返回时会被转为JSON格式字典
            
            ``list``
                返回前会被转为JSON格式的列表
            
            ``generator`` or ``iterator``
                以流式返回``str``或``bytes``的生成器作为响应
            
            ``tuple``
                ``(body, status, headers)``, ``(body, status)`` 或者``(body, headers)``
                body再这里可以是任意的其他类型，``status``是一个字符串或者整数，
                ``headers``是一个字典或者``(key, value)``元组的列表，如果``body``
                是一个:attr:`response_class`实例， ``status``重写现有值，``header``
                被扩展
            
            :attr:`response_class`
                object原样返回

            其他:class:`~mywerkzeug.wrapper.Response`类
                对象被轻质赋值为:attr:`response_class`
            
            :func:`callable`
                function作为一个WSGI应用被调用，结果用于创建一个response对象
        """
        status: int | None = None
        headers: HeadersValue | None = None
        
        # 解析tuple返回
        if isinstance(rv, tuple):
            len_rv = len(rv)

            # 3-tuple直接解析
            if len_rv == 3:
                rv, status, headers = rv  # type: ignore[misc]
            # 判断2-tuple是否包含status或者headers
            elif len_rv == 2:
                if isinstance(rv[1], (headers, dict, tuple, list)):
                    rv, headers = rv  # pyright: ignore
                else:
                    rv, status = rv  # type: ignore[assignment,misc]
            # 其他数量的tuple不允许
            else:
                raise TypeError(
                    "The view function did not return a valid response tuple."
                    " The tuple must have the form (body, status, headers),"
                    " (body, status), or (body, headers)."
                )
        
        # body必不为空
        if rv is None:
            raise TypeError(
                f"The view function for {request.endpoint!r} did not"
                " return a valid response. The function either returned"
                " None or ended without a return statement."
            )
        
        # 确保body是response类的实例
        if not isinstance(rv, self.response_class):
            if isinstance(rv, (str, bytes, bytearray)) or isinstance(rv, cabc.Iterable):
                # 让response类设置status和headers，而不是等待手动设置，这样类可以处理
                # 任何特殊情况
                rv = self.response_class(
                    rv, # pyright: ignore
                    status=status,
                    headers=headers, # type: ignore[arg-type]
                )
                status = headers = None
            elif isinstance(rv, (dict, list)):
                rv = self.json.response(rv)
            elif isinstance(rv, BaseResponse) or callable(rv):
                # 评估一个WSGI可调用对象，或者强制一个不同的response对象为正确类型
                try:
                    rv = self.response_class.force_type(
                        rv, # type: ignore[arg-type]
                        request.environ,
                    )
                except Exception as e:
                    raise TypeError(
                        f"{e}\nThe view function did not return a valid"
                        " response. The return type must be a string, dict"
                        "list, tuple, with headers or status,"
                        " Response instance, or WSGI callable, but it"
                        f" was a {type(rv).__name__}."
                    ).with_traceback(sys.exc_info()[2]) from None
            else:
                raise TypeError(
                    "The view function did not return a valid"
                    " response. The return type must be a string,"
                    " dict, list, tuple, with headers or status,"
                    " Response instance, or WSGI callable, but it"
                    f" was a {type(rv).__name__}."
                )
        
        rv = t.cast(Response, rv)
        # 优先它提供的status
        if status is not None:
            if isinstance(status, (str, bytes, bytearray)):
                rv.status = status
            else:
                rv.status_code = status
        
        # 合并headers
        if headers:
            rv.headers.update(headers)
        
        return rv


    def preprocess_request(self) -> ft.ResponseReturnValue | None:
        """request分发前调用，调用注册在app和当前蓝图的:attr:`url_value_preprocessor`
        （如果存在）。然后调用注册在app和蓝图的:attr:`before_request_func`

        如果任意:meth:`before_request`处理器返回一个非空值，该值被视为视图的返回值，
        后续请求处理停止
        """
        names = (None, *reversed(request.blueprints))

        for name in names:
            if name in self.url_value_preprocessor:
                for url_func in self.url_value_preprocessor[name]:
                    url_func(request.endpoint, request.view_args)

        for name in names:
            if name in self.before_request_funcs:
                for before_func in self.before_request_funcs[name]:
                    rv = self.ensure_sync(before_func)()

                    if rv is not None:
                        return rv # type: ignore[no-any-return]
        
        return None

    def process_response(self, response: Response) -> Response:
        """可以被重写，在发送WSGI server之前修改response对象，默认会调用
        :meth:`after_request` 装饰器方法

        :param response: :attr:`response_class`对象
        :return: 新的response对象或者相同，必须为:attr:`response_class`的实例
        """
        ctx = request_ctx._get_current_object() # type: ignore[attr-defined]

        for func in ctx._after_request_functions:
            response = self.ensure_sync(func)(response)
        
        for name in chain(request.blueprints, (None,)):
            if name in self.after_request_funcs:
                for func in reversed(self.after_request_funcs[name]):
                    response = self.ensure_sync(func)(response)
        
        if not self.session_interface.is_null_session(response):
            self.session_interface.save_session(self, request, response)
        
        return response

    def do_teardown_request(
        self,
        exc: BaseException | None = _sentinel, # type: ignore[assignment]
    ) -> None:
        """请求分发和response返回之后调用，在request context pop 之前
        
        调用所有被:meth:`teardown_request`装饰的方法，以及如果蓝图处理request, 也会调用
        :meth:`Bluepring.teardown_request`,最后发送:data:`request_tearing_down`信号
        
        被:meth:`RequestContext.pop() <flask.ctx.RequestContext.pop>`调用，
        为保证资源供应，测试会有延迟

        :param exc: 分发请求时未处理的异常。如果未通过 从当前异常信息中检测，传递给每一个
            teardown 方法
        """
        if exc is _sentinel:
            exc = sys.exc_info()[1]
        
        for name in chain(request.blueprints, (None,)):
            if name in self.teardown_request_funcs:
                for func in reversed(self.teardown_request_funcs[name]):
                    self.ensure_sync(func)(exc)
        
        request_tearing_down.send(self, _async_wrapper=self.ensure_sync, exc=exc)
        
    def do_teardown_appcontext(
        self,
        exc: BaseException | None = _sentinel, # type: ignore[assignment]
    ) -> None:
        """在app contex pop之前调用
        
        当处理request， app context在request context之后pop。参考:meth:`do_teardown_request`

        调用所有被:meth:`teardown_appcontext`装饰的方法，然后发送
        :data:`appcontext_tearing_down`信号

        被:meth:`AppContext.pop() <flask.ctx.AppContext.pop>调用`
        """
        if exc is _sentinel:
            exc = sys.exc_info()[1]
        
        for func in reversed(self.teardown_appcontext_funcs):
            self.ensure_sync(func)(exc)
        
        appcontext_tearing_down.send(self, _async_wrapper=self.ensure_sync, exc=exc)

    def app_context(self) -> AppContext:
        """创建一个:class:`~myflask.ctx.AppContext`.作为一个``with``代码块来将context
        压栈，使得:data:`current_app`指向这个application

        :meth:`RequestContext.push() <myflask.ctx.RequestContext.push>`在处理
        request和运行CLI命令时会自动将application context压栈，在其他情况下手动
        创建一个context

        ::

            with app.app_context():
                init_db()
        
        参考 :doc:`/appcontext`.
        """
        return AppContext(self)

    def request_context(self, environ: WSGIEnvironment) -> RequestContext:
        """创建一个:class:`~flask.ctx.RequestContext`表示WSGI 环境。使用``with``
        代码块来push context，使得:data:`request`指向这个request

        参考 :doc:`/reqcontext`.

        不应该从你的代码中直接调用这个方法，当处理一个请求时，:meth:`wsgi_app`会自动push
        request context. 使用:meth:`test_request_context`来创建环境变量和context
        而不是这个方法

        :param environ: WSGI 环境变量。
        """
        return RequestContext(self, environ)

    def wsgi_app(
        self, environ: WSGIEnvironment, start_response: StartResponse
    ) -> cabc.Iterable[bytes]:
        """实际的WSGI application。不在:meth:`__call__`实现，这样可以在不丢失app
        对象的引用情况下应用中间件。相较于：
            
            app = MyMiddleware(app)
        
        这样实现会更好：

            app.wsgi_app = MyMiddleware(app.wsgi_app)
        
        这样可以保留原始的应用程序对象，并调用它的方法

        :param environ: WSGI 环境变量。
        :param start_response: 可调用对象，接收一个status code，一个headers的列表
            一个可选的exception context来启动response
        """
        ctx = self.request_context(environ)
        error: BaseException | None = None
        try:
            # try:
            ctx.push()
            response = self.full_dispatch_request()
            # except Exception as e:
            #     error = e
            #     # response = self.handle_exception(e)
            #     print(str(e))
            # except: # noqa: B001
            #     error = sys.exc_info()[1]
            #     raise
            return response(environ, start_response)
        finally:
            if "mywerkzeug.debug.preserve_context" in environ:
                environ["mywerkzeug.debug.preserve_context"](_cv_app.get())
                environ["mywerkzeug.debug.preserve_context"](_cv_request.get())
            if error is not None and False:
                error = None
            
            ctx.pop(error)


    def __call__(
        self, environ: WSGIEnvironment, start_response: StartResponse
    ) -> cabc.Iterable[bytes]:
        """WSGI server 调用 Flask application 对象作为一个WSGI application。
        调用:meth:`wsgi_app`, wrapped 以应用中间件
        """
        return self.wsgi_app(environ, start_response)
