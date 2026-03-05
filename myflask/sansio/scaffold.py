import importlib.util
import pathlib
import os
import sys
import typing as t
from collections import defaultdict
from functools import update_wrapper

from .. import typing as ft
from ..helpers import get_root_path
from ..templating import _default_template_ctx_processor

# 用于参数默认值和单例哨兵值
_sentinel = object()

F = t.TypeVar("F", bound=t.Callable[..., t.Any])
T_route = t.TypeVar("T_route", bound=ft.RouteCallable)

def setupmethod(f: F) -> F:
    f_name = f.__name__

    def wrapper_func(self: Scaffold, *args: t.Any, **kwargs: t.Any) -> t.Any:
        self._check_setup_finished(f_name)
        return f(self, *args, **kwargs)

    return t.cast(F, update_wrapper(wrapper_func, f))

class Scaffold:
    """在:class:`~myflask.Flask`和:class:`~flask.blueprints.Blueprint`间共享行为

    :param import_name: 该对象所在模块的导入名称，通常应使用:attr:`__name__`
    :param static_folder: 需要提供服务的静态文件的目录路径
        若被设置，静态路由会被添加
    :param static_url_path: 静态路由的URL前缀。
    :param template_folder: 包含模板文件的目录路径, 用于渲染，若被设置，会添加一个
        Jinja loader。
    :param root_path: 静态文件，模板文件，资源文件的根目录。通常不设置，会根据
        ``import_name``自动发现。
    """

    _static_folder: str | None = None
    _static_url_path: str | None = None

    def __init__(
        self,
        import_name: str,
        static_folder: str | os.PathLike[str] | None = None,
        static_url_path: str | None = None,
        template_folder: str | os.PathLike[str] | None = None,
        root_path: str | None = None,
    ):
        #: 对象所属的包或模块名称，一旦被构造器设置，不能被修改。
        self.import_name = import_name

        self.static_folder = static_folder
        self.static_url_path = static_url_path

        #: 模板文件夹路径，相对于:attr:`root_path`,以添加至template loader. 
        #: 若模板不应被添加，应设置为``None``
        self.template_folder = template_folder

        if root_path is None:
            root_path = get_root_path(self.import_name)

        #: 文件系统中包的绝对路径。
        #: 过去常常用于查找该软件包中包含的资源
        self.root_path = root_path

        #: 将endpoint映射到view functions的字典
        #:
        #: 使用:meth:`route`装饰器来注册view function
        #: 数据结构是内置的，不应被直接修改，格式可能会在任意时间修改
        self.view_functions: dict[str, ft.RouteCallable] = {}

        #: 一个注册的error hanlders的数据结构，格式为
        #: ``{scope: {code: {class: handle}}}``.``scope``是handlers所作用的蓝图的
        #: 的名称，或者``None``表示所有请求。``code``是``HTTPException``的状态码，
        #: ``None``表示其他异常。最内层的字典将异常类别映射到处理函数。
        #:
        #: 使用:meth:`errorhandler`装饰器来注册error handlers
        #: 数据结构是内置的，不应被直接修改，格式可能会在任意时间修改
        self.error_handler_spec: dict[
            ft.AppOrBlueprintKey,
            dict[int | None, dict[type[Exception], ft.ErrorHandlerCallable]],
        ] = defaultdict(lambda: defaultdict(dict))
        
        #: 每个请求开始被调用方法的数据结构，格式为``{scope: [functions]}``
        #: ``scope``是functions所作用的蓝图的名称，``None``表示所有请求
        #:
        #: 使用装饰器:meth:`before_request`来注册方法
        #: 数据结构是内置的，不应被直接修改，格式可能会在任意时间修改
        self.before_request_funcs: dict[
            ft.AppOrBlueprintKey, list[ft.BeforeRequestCallable]
        ] = defaultdict(list)

        #: 每个请求结束被调用方法的数据结构，格式为``{scope: [functions]}``
        #: ``scope``是functions所作用的蓝图的名称，``None``表示所有请求
        #:
        #: 使用装饰器:meth:`after_request`来注册方法
        #: 数据结构是内置的，不应被直接修改，格式可能会在任意时间修改
        self.after_request_funcs: dict[
            ft.AppOrBlueprintKey, list[ft.AfterRequestCallable[t.Any]]
        ] = defaultdict(list)

        #: 每个请求结束结束会被调用的方法数据结构（异常也会被调用），格式为
        #: ``{scope: [functions]}``. 
        #: ``scope``是functions所作用的蓝图的名称，``None``表示所有请求
        #:
        #: 使用装饰器:meth:`teardown_request`来注册方法
        #: 数据结构是内置的，不应被直接修改，格式可能会在任意时间修改
        self.teardown_request_funcs: dict[
            ft.AppOrBlueprintKey, list[ft.TeardownCallable]
        ] = defaultdict(list)


        #: 渲染模版时用于调用来传递额外context值的方法的数据结构，格式为
        #: ``{scope: [functions]}``. ``scope``是functions所作用的蓝图的名称，
        #: ``None``表示所有请求
        #:
        #: 使用装饰器:meth:`context_processor`来注册方法
        #: 数据结构是内置的，不应被直接修改，格式可能会在任意时间修改
        self.template_context_processor: dict[
            ft.AppOrBlueprintKey, list[ft.TemplateContextProcessorCallable]
        ] = defaultdict(list, {None: [_default_template_ctx_processor]})

        #: 修改向view function传递keyword参数的方法的数据结构，格式为
        #: ``{scope: [functions]}``. ``scope``是functions所作用的蓝图的名称，
        #: ``None``表示所有请求
        #:
        #: 使用装饰器:meth:`url_value_preprocessor`来注册方法
        #: 数据结构是内置的，不应被直接修改，格式可能会在任意时间修改
        self.url_value_preprocessor: dict[
            ft.AppOrBlueprintKey,
            list[ft.URLValuePreprocessorCallable],
        ] = defaultdict(list)

        #: 当生成URLs时修改keyword参数的方法的数据结构，格式为
        #: ``{scope: [functions]}``. ``scope``是functions所作用的蓝图的名称，
        #: ``None``表示所有请求
        #:
        #: 使用装饰器:meth:`url_defaults`来注册方法
        #: 数据结构是内置的，不应被直接修改，格式可能会在任意时间修改
        self.url_default_functions: dict[
            ft.AppOrBlueprintKey, list[ft.URLDefaultCallable]
        ] = defaultdict(list)

    def _check_setup_finished(self, f_name: str) -> None:
        raise NotImplementedError

    @property
    def static_folder(self) -> str | None:
        """配置静态目录的绝对路径， 如果没有设置静态目录，返回``None``"""
        if self._static_folder is not None:
            return os.path.join(self.root_path, self._static_folder)
        else:
            return None

    @static_folder.setter
    def static_folder(self, value: str | os.PathLike[str] | None) -> None:
        if value is not None:
            value = os.fspath(value).rstrip(r"\/")

        self._static_folder = value    
    
    @property
    def has_static_folder(self) -> bool:
        """如果:attr:`static_folder`被设置，则为``True``"""
        return self.static_folder is not None

    @property
    def static_url_path(self) -> str | None:
        """静态路由获取的URL前缀
        
        init时没有配置，源于:attr:`static_folder`
        """
        if self._static_url_path is not None:
            return self._static_url_path

        if self.static_folder is not None:
            basename = os.path.basename(self.static_folder)
            return f"/{basename}".rstrip("/")
        
        return None
    
    @static_url_path.setter
    def static_url_path(self, value: str | None) -> None:
        if value is not None:
            value = value.rstrip("/")
        
        self._static_url_path = value

    @setupmethod
    def route(self, rule: str, **options: t.Any) -> t.Callable[[T_route], T_route]:
        """装饰一个view function来使用给到的URL 规则和选项注册它。
        调用:meth:`add_url_rule`,有更多实现的细节

        .. code-block:: python

            @app.route("/")
            def index():
                return "Hello, World!"

        参考 :ref:`url-route-registrations`.

        如果``endpoint``没有传递，路由的端点名称默认为view function的名称

        ``methods``默认参数的为``["GET"]``. ``HEAD``和``OPTIONS``会自动添加

        :param rule: URL规则字符串
        :param options: 传递给:class:`~mywerkzeug.routing.Rule`对象的额外选项
        """
        def decorator(f: T_route) -> T_route:
            endpoint = options.pop("endpoint", None)
            self.add_url_rule(rule, endpoint, f, **options)
            return f
        
        return decorator

    @setupmethod
    def add_url_rule(
        self, 
        rule: str,
        endpoint: str | None = None,
        view_func: ft.RouteCallable | None = None,
        provide_automatic_options: bool | None = None,
        **options: t.Any,
    ) -> None:
        """注册用于路由请求的规则并构建ULRs。:meth:`route`装饰器是使用``view_func``
        来调用此方法的快捷方式。下面这些是等效的:

        .. code-block: python
            @app.route("/")
            def index():
                ...
        
        .. code-block:: python

            def index():
                ...
            app.add_url_rule("/", view_func=index)
        
        参考 :ref:`url-route-registrations`.

        如果``endpoint``参数没有传递，路由的endpoint名称默认为view function的名称
        如果function已经被端点注册，会抛出错误

        ``methods``参数默认为``["GET"]``. ``HEAD``已经自动添加，``OPTIONS``会自动添加

        ``view_func``参数不是必须的，如果规则要参与路由，必须在某个时间使用
        :meth:`endpoint`装饰器关联endpoint name和view function

        .. code-block:: python

            app.add_url_rule("/", endpoint="index")

            @app.endpoint("index")
            def index():
                ...

        如果``view_func``有``required_methods``属性，这些方法会被添加到passed和automatic
        方法中。如果有``provide_automatic_methods``属性，如果参数没有传递将它作为默认值

        :param rule: URL规则字符串
        :param endpoint: 用于关联规则和view function的endpoint，当路由和构建URLs时使用
            默认为``view_func.__name__``
        :param view_func: 关联到endpoint的view function
        :param provide_automatic_options: 添加``OPTIONS``方法并自动响应``OPTIONS``
            请求
        :param options: 传递给:class:`~mywerkzeug.routing.Rule`对象的额外选项
        """
        raise NotImplementedError

def _endpoint_from_view_func(view_func: ft.RouteCallable) -> str:
    """内部辅助函数，用于返回给定函数的默认端点，总是function 名称"""
    assert view_func is not None, "expected view func if endpoint is not provided."
    return view_func.__name__

def _find_package_path(import_name: str) -> str:
    """找到包含包或者模块的路径"""
    root_mod_name, _, _ = import_name.partition(".")
    
    try:
        root_spec = importlib.util.find_spec(root_mod_name)

        if root_spec is None:
            raise ValueError("not found")
    except (ImportError, ValueError):
        # ImportError: 机器无法找到目录
        # ValueError: 
        #   - 模块命名非法
        #   - 模块名称是__main__
        #   - 由于`root_spec`是`None`
        return os.getcwd()

    if root_spec.submodule_search_locations:
        if root_spec.origin is None or root_spec.origin == "namespace":
            # namespace package
            package_spec = importlib.util.find_spec(import_name)
            
            if package_spec is not None and package_spec.submodule_search_locations:
                # 选择命名空间中包含子模块的路径
                package_path = pathlib.Path(
                    os.path.commonpath(package_spec.submodule_search_locations)
                )
                search_location = next(
                    location
                    for location in root_spec.submodule_search_locations
                    if package_path.is_relative_to(location)
                )
            else:
                # 选择第一个路径
                search_location = root_spec.submodule_search_locations[0]

            return os.path.dirname(search_location)
        else:
            # 包含__init__.py 的包
            return os.path.dirname(os.path.dirname(root_spec.origin))
    else:
        # 模块
        return os.path.dirname(root_spec.origin) # type: ignore[type-var, return-value]


def find_package(import_name: str) -> tuple[str | None, str]:
    """找到包的安装前缀及其导入路径。
    
    prefix是包含标准目录层级结构(lib, bin,等)的目录，如果包没有安装到
    系统(:attr:`sys.prefix`)或者虚拟环境(``site-package``),返回``None``

    path是:attr:`sys.path`中包含导入包的入口。如果包没有安装，那么假设它从当前目录导入。
    """
    package_path = _find_package_path(import_name)
    py_prefix = os.path.abspath(sys.prefix)

    # 安装到系统
    if pathlib.PurePath(package_path).is_relative_to(py_prefix):
        return py_prefix, package_path

    site_parent, site_folder = os.path.split(package_path)

    # 被安装到虚拟环境
    if site_folder.lower() == "site-packages":
        parent, folder = os.path.split(site_parent)

        # Windows (prefix/lib/site-packages)
        if folder.lower() == "lib": return parent, package_path

        # Unix (prefix/lib/pythonX.Y/site-packages)
        if os.path.basename(parent).lower() == "lib":
            return os.path.dirname(parent), package_path

        # 其他
        return site_parent, package_path
    
    # 未安装
    return None, package_path




