
import collections.abc as cabc
import typing as t

if t.TYPE_CHECKING: # pragma: no cover
    from _typeshed.wsgi import WSGIApplication # noqa: F401
    from mywerkzeug.datastructures import Headers # noqa: F401
    from mywerkzeug.sansio.response import Response #noqa: F401

# 可能的类型是一个Response对象，或者直接可转换Response的类型。
ResponseValue = t.Union[
    "Response",
    str,
    bytes,
    list[t.Any],
    # 目前只接受字典（dict），但映射（Mapping）功能允许使用类型化字典（TypedDict）。
    t.Mapping[str, t.Any],
    t.Iterator[str],
    t.Iterator[bytes],
    cabc.AsyncIterable[str], # 用于Quart，直到 App 类实现泛型支持
    cabc.AsyncIterable[bytes],
]

# 单个HTTP header可能的类型
# 应为Union，但是mypy不会通过，除非是一个TypeVar
HeaderValue = t.Union[str, list[str], tuple[str, ...]]

# HTTP headers可能类型
HeadersValue = t.Union[
    "Headers",
    t.Mapping[str, HeaderValue],
    t.Sequence[tuple[str, HeaderValue]],
]

# route function 可能的返回类型
ResponseReturnValue = t.Union[
    ResponseValue,
    tuple[ResponseValue, HeadersValue],
    tuple[ResponseValue, int],
    tuple[ResponseValue, int, HeadersValue],
    "WSGIApplication",
]

# 允许mywerkzeug.Response的所有子类，例如Flask中的一个，作为callback的参数
# 直接使用mywerkzeug.Response会导师带有myflask.Response注解的callback
# 无法通过类型检查
ResponseClass = t.TypeVar("ResponseClass", bound="Response")

AppOrBlueprintKey = t.Optional[str] # App key是None，而blueprints 被命名
AfterRequestCallable = t.Union[
    t.Callable[[ResponseClass], ResponseClass],
    t.Callable[[ResponseClass], t.Awaitable[ResponseClass]],
]
BeforeRequestCallable = t.Union[
    t.Callable[..., ResponseReturnValue],
    t.Callable[..., t.Awaitable[ResponseReturnValue]],
]
TeardownCallable = t.Union[
    t.Callable[[t.Optional[BaseException]], None],
    t.Callable[[t.Optional[BaseException]], t.Awaitable[None]],
]
TemplateContextProcessorCallable = t.Union[
    t.Callable[[], dict[str, t.Any]],
    t.Callable[[], t.Awaitable[dict[str, t.Any]]],
]

URLDefaultCallable = t.Callable[[str, dict[str, t.Any]], None]
URLValuePreprocessorCallable = t.Callable[
    [t.Optional[str], t.Optional[dict[str, t.Any]]], None
]

# 这应该接受 Exception，但这要么会破坏使用特定异常对参数进行类型化，
# 要么会多次使用不同的异常进行修饰（并在​​参数上使用联合类型）。
# https://github.com/pallets/flask/issues/4095
# https://github.com/pallets/flask/issues/4295
# https://github.com/pallets/flask/issues/4297
ErrorHandlerCallable = t.Union[
    t.Callable[[t.Any], ResponseReturnValue],
    t.Callable[..., t.Awaitable[ResponseReturnValue]],
]

RouteCallable = t.Union[
    t.Callable[..., ResponseReturnValue],
    t.Callable[..., t.Awaitable[ResponseReturnValue]],
]