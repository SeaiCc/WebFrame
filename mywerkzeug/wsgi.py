
import typing as t
from functools import partial

from .sansio import utils as _sansio_utils

if t.TYPE_CHECKING:
    from _typeshed.wsgi import WSGIEnvironment

def get_path_info(environ: WSGIEnvironment) -> str:
    """从 WSGI环境中获取 ``PATH_INFO`` 返回

    :param environ: 用于获取path的WSGI环境
    """
    path: bytes = environ.get("PATH_INFO", "").encode("latin1")
    return path.decode(errors="replace")

class ClosingIterator:
    """WSGI 规范要求所有中间件和网关都必须遵守应用程序返回的可迭代对象的 `close` 回调。
    因为给返回的可迭代对象添加另一个关闭操作很有用，而添加自定义可迭代对象又是一项枯燥乏味
    的任务，所以可以使用此类来实现::
        return ClosingIterator(app(environ, start_response), [cleanup_session,
                                                              cleanup_locals])
    若仅有一个close 方法，可以直接将其作为参数传递，而不是传递列表

    如果应用程序使用响应对象并在响应开始时完成处理，则不需要关闭迭代器::
        try:
            return response(environ, start_response)
        finally:
            cleanup_session()
            cleanup_locals()
    """
    def __init__(
        self,
        iterable: t.Iterable[bytes],
        callbacks: None
        | (t.Callable[[], None] | t.Iterable[t.Callable[[], None]]) = None,
    ) -> None:
        iterator = iter(iterable)
        self._next = t.cast(t.Callable[[], bytes], partial(next, iterator))
        if callbacks is None:
            callbacks = []
        elif callable(callbacks):
            callbacks = [callbacks]
        else:
            callbacks = list(callbacks)
        iterable_close = getattr(iterable, "close", None)
        if iterable_close:
            callbacks.insert(0, iterable_close)
        self._callbacks = callbacks

    def __iter__(self) -> ClosingIterator:
        return self
    
    def __next__(self) -> bytes:
        return self._next()
    
    def close(self) -> None:
        for callback in self._callbacks:
            callback()

def get_current_url(
    environ: WSGIEnvironment,
    root_only: bool = False,
    strip_querystring: bool = False,
    host_only: bool = False,
    trusted_hosts: t.Iterable[str] | None = None,
) -> str:
    """从WSGI环境的各个部分中重新创建出URL
    
    此URL是一个IRI而非URI，因此可能包含非ASCII字符。使用方法
    `~mywerkzeug.urls.iri_to_uri` 转换为URI。

    :param environ: 用于获取URL的WSGI环境
    :param root_only: 只构建根路径，不包括剩余路径或查询字符串
    :param strip_querystring: 不包括查询字符串
    :param host_only: 只构建scheme和host
    :param trusted_hosts: 用于验证host的受信任host列表
    """
    parts = {
        "scheme": environ["wsgi.url_scheme"],
        "host": get_host(environ, trusted_hosts),
    }

    if not host_only:
        parts["root_path"] = environ.get("SCRIPT_NAME", "")

        if not root_only:
            parts["path"] = environ.get("PATH_INFO", "")

            if not strip_querystring:
                parts["query_string"] = environ.get("QUERY_STRING", "").encode("latin1")
        
        return _sansio_utils.get_current_url(**parts)


def _get_server(
    environ: WSGIEnvironment,
) -> tuple[str, int | None] | None:
    name = environ.get("SERVER_NAME")

    if name is None: return None

    try:
        port: int | None = int(environ.get("SERVER_PORT", None)) # type: ignore[arg-type]
    except (TypeError, ValueError):
        port = None # unix socket

    return name, port

def get_host(
    environ: WSGIEnvironment, trusted_hosts: t.Iterable[str] | None = None
) -> str:
    """从WSGI环境中返回host
    
    优先使用``Host``header，若没有设置使用``SERVER_NAME``。
    返回的host仅包含端口号，若与协议的标准端口不同。

    可选地，使用函数``host_is_trusted``验证host是否可信，若不是则抛出异常
    ``mywerkzeug.exception.SecurityError``。

    :param environ: 用于获取host的WSGI环境
    :param trusted_hosts: 用于验证host的受信任host列表

    :return: Host，若需要的话携带端口号
    :raise (mywerkzeug.exception.SecurityError): 如果host不是受信任的host
    """
    return _sansio_utils.get_host(
        environ["wsgi.url_scheme"],
        environ.get("HTTP_HOST"),
        _get_server(environ),
        trusted_hosts,
    )


def wrap_file(
    environ: WSGIEnvironment, file: t.IO[bytes], buffer_size: int = 8192
) -> t.Iterable[bytes]:
    """包装一个文件。如果WSGI的server wrapper可用则使用，否则使用通用的
    :class:`FileWrapper`.
    
    如果使用WSGI服务器的wrapper，避免在应用程序内部对其进行迭代，
    而应保持其原始状态直接传递。如果想在response内部传递文件包装器，需要设置
    :attr:`Response.direct_passthrough` 为 ``True``。

    更多文件包装器参考:pep:`333`

    :param file: 一个包含:meth:`~file.read`方法的:class:`file`-like对象
    :param buffer_size: 一次迭代中的字节数
    """
    return environ.get("wsgi.file_wrapper", FileWrapper)( #type: ignore
        file, buffer_size
    )

class FileWrapper:
    """将一个:class:`file`-like对象包装成迭代器的类。yield `buffer_size`大小的数据块
    直到文件被完整的读取。

    不应直接使用这个类，而是通过:func:`wrap_file`方法利用WSGI服务器的文件wrapper来
    支持。

    如果你和:class:`Response`一起使用，需要使用`direct_passthrough`模式。

    :param file: 一个包含:meth:`~file.read`方法的:class:`file`-like对象
    :param buffer_size: 一次迭代中的字节数
    """
    def __init__(self, file: t.IO[bytes], buffer_size: int = 8192) -> None:
        self.file = file
        self.buffer_size = buffer_size
        

