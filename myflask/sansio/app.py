import logging
import os
import sys
import typing as t
from datetime import timedelta

from mywerkzeug.exceptions import Aborter
from mywerkzeug.routing import Map
from mywerkzeug.routing import Rule
from mywerkzeug.utils import cached_property

from .. import typing as ft
from ..config import Config
from ..config import ConfigAttribute
from ..ctx import _AppCtxGlobals
from ..helpers import get_debug_flag
from ..json.provider import DefaultJSONProvider
from ..json.provider import JSONProvider
from ..logging import create_logger
from .scaffold import _endpoint_from_view_func
from .scaffold import find_package
from .scaffold import Scaffold
from .scaffold import setupmethod

def _make_timedelta(value: timedelta | int | None) -> timedelta | None:
    if value is None or isinstance(value, timedelta):
        return value
    
    return timedelta(seconds=value)

class App(Scaffold):
    """参数详细信息见:class:`myflask.Flask`"""

    #: 用于给:attr:`aborter`赋值的对象的类，由:meth:`create_aborter`创建，
    #: 被:func:`myflask.abort`调用来抛出HTTP异常,或者直接被调用
    #: 默认类别为:class:`mywerkzeug.exceptions.Aborter`
    aborter_class = Aborter

    #: testing标志，设置为``True``以启用Flask扩展的测试模式（未来可能还会包含Flask本身）
    #: 例如，这会激活test helpers, 会有额外的运行时成本，默认不应被开启
    #:
    #: 如果启用，并且PROPAGATE_EXCEPTIONS未被改变，默认会被隐式启用
    #: 
    #: 这个属性也会被从带有``TESTING``的config中配置，默认为``False``
    testing = ConfigAttribute[bool]("TESTING")

    #: 用于:data:`~myflask.g`实例的类
    #: 
    #: 自定义类的使用方法案例：
    #: 1. 在flask.g上存储任意属性
    #: 2. 添加一个属性，用于延迟加载数据库连接器
    #: 3. 对于意外的属性返回None而不是AttributeError
    #: 4. 意外属性被设置抛出异常，一个"controlled" flask.g
    app_ctx_globals_class = _AppCtxGlobals

    #: 如果secret key被设置， cryptographic 组件可以使用它来签名cookie和其他东西。
    #: 当你想使用安全的cookie时，设置为复杂的随机值
    secret_key = ConfigAttribute[t.Union[str, bytes, None]]("SECRET_KEY")

    #: 一个:class:`~datetime.timedelta`, 用于设置永久会话的到期时间，默认31天，是的
    #: 永久session存在一个月，也可以使用``PERMANENT_SESSION_LIFETIME``配置项来配置
    #: 默认``timedelta(days=31)``
    permanent_session_lifetime = ConfigAttribute[timedelta](
        "PERMANENT_SESSION_LIFETIME",
        get_converter=_make_timedelta, # type: ignore[arg-type]
    )

    json_provider_class: type[JSONProvider] = DefaultJSONProvider
    """:class:`~myflask.json.provider.JSONProvider`的子类，当创建app时一个实例会被
    闯将并赋值到:attr:`app.json`
    
    默认的:class:`~myflask.json.provider.DefaultJSONProvider`会使用python内置的
    :mod:`json`库，不同的provider可以使用不同的JSON library。
    """

    #: 被应用属性``config``使用的类，默认:class:`~myflask.Config`
    #:
    #: 使用自定义类的案例
    #:  1. 某些配置选项的默认值
    #:  2. 除了key，可以通过属性访问config值
    config_class = Config

    #: 用于已创建URL规则的规则对象，，被:meth:`add_url_rule`使用。默认类别为
    #: :class:`mywerkzeug.routing.Rule`
    url_rule_class = Rule

    #: 用来存储URL规则和路由配置参数的的map对象。默认为:class:`mywerkzeug.routing.Map`
    url_map_class = Map

    default_config: dict[str, t.Any]

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
            static_folder=static_folder,
            static_url_path=static_url_path,
            template_folder=template_folder,
            root_path=root_path,
        )

        if instance_path is None:
            instance_path = self.auto_find_instance_path()
        elif not os.path.isabs(instance_path):
            raise ValueError(
                "If an instance path is provided it must be absolute."
                " A relative path was given instead."
            )

        #: 包含实例文件夹的路径
        self.instance_path = instance_path

        #: 配置字典为:class:`Config`. 行为类似常规字典但是支持额外的方法来从文件加载
        self.config = self.make_config(instance_relative_config)

        #: 由:meth:`make_aborter`创建的:attr:`aborter_class`实例，被
        #: :func:`myflask.abort`调用，用来抛出HTTP错误，也可以被直接调用
        self.aborter = self.make_aborter()

        self.json: JSONProvider = self.json_provider_class(self)
        """提供了JSON方法。当application的content激活时``flask.json``会调用这个
        provider的方法。用于处理request和resposne的JSON

        :attr:`json_provider_class`的实例，可以通过子类中修改这个属性来自定义，或者
        之后给这个属性赋值

        默认的:class:`~myflask.json.provider.DefaultJSONProvider`使用python内置的
        :mod:`json`库，不同的provider可以使用不同的JSON库。
        """

        #: 当app context 被销毁时调用的方法列表，因为请求结束app context 也被销毁, 
        #: 因此这里应该存储与数据库断开的代码
        self.teardown_appcontext_funcs: list[ft.TeardownCallable] = []

        #: 此实例的:class:`~mywerkzeug.routing.Map`,类创建之后任何routes连接之前
        #: 可使用来改变routing转换,例如
        #: 
        #:  from mywerkzeug.routing import BaseConverter
        #:  
        #:  class ListConverter(BaseConverter):
        #:      def to_python(self, value):
        #:          return value.split(",")
        #:      def to_url(self, values):
        #:          return ",".join(super(ListConverter, self).to_url(values)
        #:                          for value in values)
        #:
        #:      app = Flask(__name__)
        #:      app.url_map.converters['list'] = ListConverter
        self.url_map = self.url_map_class(host_matching=host_matching)

        self.subdomain_matching = subdomain_matching

        # 追踪是否app已经处理了至少一个请求
        self._got_first_request = False

    def _check_setup_finished(self, f_name: str) -> None:
        if self._got_first_request:
            raise AssertionError(
                f"The setup method '{f_name}' can no longer be called"
                " on the application. It has already handled its first"
                " request, any changes will not be applied"
                " consistently.\n"
                "Make sure all imports, decorators, functions, etc."
                " needed to set up the application are done before"
                " running it."
            )

    @cached_property
    def name(self) -> str:
        """应用名称，通常是导入名称， 区别在于如果导入名称是main，从运行文件中猜测
        当Flask需要应用名称时，会使用这个属性。可以被设置和覆盖
        """
        if self.import_name == "__main__":
            fn: str | None = getattr(sys.modules["__main__"], "__file__", None)
            if fn is None: return "__main__"
            return os.path.splitext(os.path.basename(fn))[0]
        return self.import_name

    @cached_property
    def logger(self) -> logging.Logger:
        """标准的python :class:`logging.Logger`, 名称为:attr:`name`
        
        debug模式下，:attr:`~logging.Logger.level`被设置为:data:`~logging.DEBUG`

        如果没有配置handlers，默认的handler会被添加，参考:doc:`/logging`
        """
        return create_logger(self)

    def make_config(self, instance_relative: bool = False) -> Config:
        """被Flask 构造器用来创建配置attribute。`instance_relative`参数由
        Flask构造器传递(此处为`instance_relative_config`),如果config应被关联
        到instance path或者应用到root path 配置文件中应该指出
        """
        root_path = self.root_path
        if instance_relative:
            root_path = self.instance_path
        defaults = dict(self.default_config)
        defaults["DEBUG"] = get_debug_flag()
        return self.config_class(root_path, defaults)

    def make_aborter(self) -> Aborter:
        """创建对象给:attr:`aborter`赋值，被:func:`myflask.abort`调用用来抛出HTTP错误
        或者直接被调用
        
        默认创建一个:attr:`aborter_class`实例，默认类为
        :class:`mywerkzeug.exceptions.Aborter`
        """
        return self.aborter_class()

    def auto_find_instance_path(self) -> str:
        """尝试定位实例路径若application 类构造器没有提供。 它会计算出位于主文件或包旁边的
        名为``instance``的文件夹。
        """

        prefix, package_path = find_package(self.import_name)
        if prefix is None:
            return os.path.join(package_path, "instance")
        return os.path.join(prefix, "var", f"{self.name}-instance")

    @property
    def debug(self) -> bool:
        """debug模式是否启用，当使用``flask run``启动开发服务器，对于未处理异常，会显示
        交互debugger，当code改变时会重载服务。这对应于:data:`DEBUG`配置键。如果较晚设置
        可能不会按预期的行为

        **当部署在生产环境不要启用debug mode
        """
        return self.config["DEBUG"] # type: ignore[no-any-return]

    @setupmethod
    def add_url_rule(
        self,
        rule: str,
        endpoint: str | None = None,
        view_func: ft.RouteCallable | None = None,
        provide_automatic_options: bool | None = None,
        **options: t.Any,
    ) -> None:
        if endpoint is None:
            endpoint = _endpoint_from_view_func(view_func) # type: ignore
        options["endpoint"] = endpoint
        methods = options.pop("methods", None)

        # 如果没有给method并且view_func对象知道它的方法，可以使用，如果都不存在，默认使用
        # 仅包含``GET``的元组
        if methods is None:
            methods = getattr(view_func, "methods", None) or ("GET",)
        if isinstance(methods, str):
            raise TypeError(
                "Allowed methods must be a list of strings, for"
                ' example: @app.route(..., methods=["POST"])'
            )
        methods = {item.upper() for item in methods}

        # 总是应该被添加的方法
        require_methods: set[str] = set(getattr(view_func, "reuqired_methods", ()))

        # view_func 对象可以被关闭，并强制启动自动选项处理
        if provide_automatic_options is None:
            provide_automatic_options = getattr(
                view_func, "provide_automatic_options", None
            )
        
        if provide_automatic_options is None:
            if "OPTIONS" not in methods and self.config["PROVIDE_AUTOMATIC_OPTIONS"]:
                provide_automatic_options = True
                require_methods.add("OPTIONS")
            else:
                provide_automatic_options = False
        
        # 现在添加需要的方法
        methods |= require_methods

        rule_obj = self.url_rule_class(rule, methods=methods, **options)
        rule_obj.provide_automatic_options = provide_automatic_options # type: ignore[attr-defined]

        self.url_map.add(rule_obj)
        if view_func is not None:
            old_func = self.view_functions.get(endpoint)
            if old_func is not None and old_func != view_func:
                raise AssertionError(
                    f"View function mapping is overwriting an existing"
                    f" endpoint function: {endpoint}"
                )
            self.view_functions[endpoint] = view_func
