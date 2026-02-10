import collections.abc as cabc
import importlib.util
import mimetypes
import os
import posixpath
import typing as t
from datetime import datetime
from datetime import timezone
from io import BytesIO
from time import time
from zlib import adler32

from ..http import http_date
from ..http import is_resource_modified
from ..security import safe_join
from ..utils import get_content_type
from ..wsgi import get_path_info
from ..wsgi import wrap_file

if t.TYPE_CHECKING:
    from _typeshed.wsgi import WSGIApplication
    from _typeshed.wsgi import WSGIEnvironment, StartResponse

_TOpener = t.Callable[[], tuple[t.IO[bytes], datetime, int]]
_TLoader = t.Callable[[t.Optional[str]], tuple[t.Optional[str], t.Optional[_TOpener]]]

class SharedDataMiddleware:
    """WSGI中间件，给开发环境提供静态环境或者简单的server设置。使用方法:
        import os
        from mywerkzeug.middleware.shared_data import SharedDataMiddleware

        app = SharedDataMiddleware(app, {
            '/shared': os.path.join(os.path.dirname(__file__), 'shared')
        })
    
    启动服务后``./shared``可通过``http://examples.com/shared/``访问。开发时很有用，
    因为不需要独立的服务器。文件也可以挂载到root文件夹并继续使用这个应用。因为shared
    data middleware 定向了所有未处理的请求到到应用，即使请求在shared folders之一中。

    若```pkg_resources```可用，可以告诉middleware从python package中加载静态文件。
    
    
        app = SharedDataMiddleware(app, {
            '/shared': ('myapplication', 'static')
        })

    例如，若``myapplication``是一个python package，它有一个``static``文件夹，
    则可以通过``http://examples.com/shared/``访问该文件夹中的文件。
    
    可选参数```disallow```可以是func:`~fnmatch.fnmatch`的一个列表，用于拒绝访问某
    些文件。若```cache```为False，不会发送cache headers。

    当前中间件不支持非ASCII文件名。若文件系统的编码碰巧和URI的编码匹配，可能不会有问题，
    但属于偶然现象，因此强烈建议使用ASCII文件名。

    中间件会使用python```mimetypes```模块来猜测消息内容类型。若无法识别字符集，回滚至
    `fallback_mimetype`。

    :param app: 需要wrap的应用。若不想wrap应用，可以传递exc: NotFound.
    :param exports: 需要暴露的文件和目录列表
    :param disallow: :func:`~fnmatch.fnmatch`规则列表
    :param cache: 是否启用caching headers.
    :param cache_timeout: header缓存超时时间(秒)
    :param fallback_mimetype: 若无法识别字符集，回滚至该MIME类型。

    ..verison:: 1.0
        默认``fallback_mimetype``是``application/octet-stream``。若文件名看起来像
        一个文本MIME类型，``utf-8``字符集会被添加到它。
    """

    def __init__(
        self,
        app: WSGIApplication,
        exports: (
            cabc.Mapping[str, str | tuple[str, str]]
            | t.Iterable[tuple[str, str | tuple[str, str]]]
        ),
        disallow: None = None,
        cache: bool = True,
        cache_timeout: int = 60 * 60 * 12,
        fallback_mimetype: str = "application/octet-stream"
    ) -> None:
        self.app = app
        self.exports = list[tuple[str, _TLoader]] = []
        self.cache = cache
        self.cache_timeout = cache_timeout
        
        if isinstance(exports, cabc.Mapping):
            exports = exports.items()

        for key, value in exports:
            if isinstance(value, tuple):
                loader = self.get_package_loader(*value)
            elif isinstance(value, str):
                if os.path.isfile(value):
                    loader = self.get_file_loader(value)
                else:
                    loader = self.get_directory_loader(value)
            else:
                raise TypeError(f"unknown def {value!r}")
        
            self.exports.append((key, loader))
        
        if disallow is not None:
            from fnmatch import fnmatch

            self.is_allowed = lambda x: not fnmatch(x, disallow)
        self.fallback_mimetype = fallback_mimetype
    
    def is_allowed(self, filename: str) -> bool:
        """子类可以重写此方法来拒绝访问某些文件。
        然而，若构造器中提供了`disallow`参数，此方法将被覆盖。
        """
        return True

    def _opener(self, filename: str) -> _TOpener:
        """获取文件的流，修改时间和大小。封装为一个callable对象。"""
        return lambda: (
            open(filename, "rb"),
            datetime.fromtimestamp(os.path.getmtime(filename), tz=timezone.utc),
            int(os.path.getsize(filename)),
        )

    def get_file_loader(self, filename: str) -> _TLoader:
        return lambda x: (os.path.basename(filename), self._opener(filename))

    def get_package_loader(self, package: str, package_path: str) -> _TLoader:
        load_time = datetime.now(timezone.utc)
        spec = importlib.util.find_spec(package)
        reader = spec.loader.get_resource_reader(package)

        def loader(
            path: str | None,
        ) -> tuple[str | None, _TOpener | None]:
            if path is None:
                return None, None

            path = safe_join(package_path, path)

            if path is None:
                return None, None
            
            basename = posixpath.basename(path)

            try:
                resource = reader.open_resource(path)
            except OSError:
                return None, None
            
            if isinstance(resource, BytesIO):
                return (
                    basename,
                    lambda: (resource, load_time, len(resource.getvalue())),
                )
            
            return (
                basename,
                lambda: (
                    resource,
                    datetime.fromtimestamp(
                        os.path.getmtime(resource.name), tz=timezone.utc
                    ),
                    os.path.getsize(resource.name),
                ),
            )

        return loader

    def get_directory_loader(self, directory: str) -> _TLoader:
        """获取目录下的文件。若路径是一个文件，返回该文件的流。若无文件，返回None。"""
        def loader(
            path: str = None,
        ) -> tuple[str | None, _TOpener | None]:
            if path is not None:
                path = safe_join(directory, path)
                if path is None: return None, None
            else:
                path = directory

            if os.path.isfile(path):
                return os.path.basename(path), self._opener(path)
            
            return None, None
        return loader
    
    def generate_etag(self, mtime: datetime, file_size: int, real_filename: str) -> str:
        fn_str = os.fsencode(real_filename)
        timestamp = mtime.timestamp()
        checksum = adler32(fn_str) & 0xFFFFFFFF
        return f"wzsdm-{timestamp}-{file_size}-{checksum}"

    def __call__(
        self, environ: WSGIEnvironment, start_response: StartResponse
    ) -> t.Iterable[bytes]:
        path = get_path_info(environ)
        file_loader = None
        
        for search_path, loader in self.exports:
            if search_path == path:
                real_filename, file_loader = loader(None)

                if not search_path.endswith("/"):
                    search_path += "/"
                
                if path.startswith(search_path):
                    real_filename, file_loader = loader(path[len(search_path) :])
                if file_loader is not None:
                    break
        
        if file_loader is None or not self.is_allowed(real_filename):
            return self.app(environ, start_response)
        
        guessed_type = mimetypes.guess_type(real_filename)
        mime_type = \
            get_content_type(guessed_type[0] or self.fallback_mimetype, "utf-8")
        f, mtime, file_size = file_loader()

        headers = [("Date", http_date())]

        if self.cache:
            timeout = self.cache_timeout
            etag = self.generate_etag(mtime, file_size, real_filename)
            headers += [
                ("ETag", f'"{etag}"'),
                ("Cache-Control", f"max-age={timeout}, public"),
            ]

            if not is_resource_modified(environ, etag, last_modified=mtime):
                f.close()
                start_response("304 Not Modified", headers)
                return []
            
            headers.append(("Expires", http_date(time() + timeout)))
        else:
            headers.append(("Cache-Control", "public"))
        
        headers.extend(
            (
                ("Content-Type", mime_type),
                ("Content-Length", str(file_size)),
                ("Last-Modified", http_date(mtime))
            )
        )
        start_response("200 OK", headers)
        return wrap_file(environ, f)

        

    
                