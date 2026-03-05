
import os
import typing as t

if t.TYPE_CHECKING:
    import typing_extensions as te

    from .sansio.app import App

T = t.TypeVar("T")

class ConfigAttribute(t.Generic[T]):
    """将属性转发到配置"""
    def __init__(
        self, name: str, get_converter: t.Callable[[t.Any], T] | None = None
    ) -> None:
        self.__name__ = name
        self.get_converter = get_converter
    
    @t.overload
    def __get__(self, obj: None, owner: None) -> te.Self: ...
    
    @t.overload
    def __get__(self, obj: App, owner: type[App]) -> T: ...

    def __get__(self, obj: App | None, owner: type[App] | None = None) -> T | te.Self:
        if obj is None:
            return self

        rv = obj.config[self.__name__]

        if self.get_converter is not None:
            rv = self.get_converter(rv)

        return rv # type: ignore[no-any-return]


class Config(dict): # type: ignore[type-arg]
    """工作方式类似于dict但是提供了从文件或者特殊字典中创建的方式，有两种通用方式来填充配置
    
    1. 从文件填充：
        app.config.from_pyfile('yourconfig.cfg')
    
    2.  或者可以在调用:meth:`from_object`或者提供需要加载模块import path中定义配置选项
    也可以告诉他使用相同的module名，并在调用之前提供配置值:

        DEBUG = True
        SECRET_KEY = 'development key'
        app.config.from_object(__name__)
    
    上面两种情况（Python file / modules），配置中仅添加大写字母键。这样可以使用小写来表示
    不会被添加到配置文件中的临时值，或者在实现application的相同文件中定义config keys

    可能最有趣的加载配置方式是从环境变量指定文件

        app.config.from_envvar('YOURAPPLICATION_SETTINGS')

    这种情况下，在启动application前必须设置这个环境变量为你想使用的文件，Linux和OS X上使用：
        
        export YOURAPPLICATION_SETTINGS='/path/to/config/file'

    Win使用set

    :param root_path: 文件读取的相对路径，当config由application创建时，此路径为
    :attr:`~myflask.Flask.root_path`
    :param defaults: 可选的默认字典
    """

    def __init__(
        self,
        root_path: str | os.PathLike[str],
        defaults: dict[str, t.Any] | None = None,
    ) -> None:
        super().__init__(defaults or {})
        self.root_path = root_path

