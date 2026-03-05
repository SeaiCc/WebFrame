
import io
import mimetypes
import os
import typing as t
import unicodedata
from datetime import datetime
from urllib.parse import quote

from markupsafe import escape

from ._internal import _DictAccessorProperty
from ._internal import _missing
from ._internal import _TAccessorValue
from .datastructures import Headers
from .exceptions import NotFound
from .security import safe_join
from .wsgi import wrap_file

if t.TYPE_CHECKING:
    from _typeshed.wsgi import WSGIEnvironment

    from .wrappers.response import Response

_T = t.TypeVar("_T")

class cached_property(property, t.Generic[_T]):
    """一个仅被evaluate一次的:func:`property`,后续访问返回缓存值。设置property会设置缓存值
    删除property会清楚缓存，再次访问将再次evaluate
    
    .. code-block:: python

        class Example:
            @cached_property
            def value(self):
                # 计算value
                return 42
        e = Example()
        e.value # evaluates
        e.value # 使用缓存
        e.value = 16 # 设置缓存
        del e.value # 清理缓存

    如果class定义了``__slots__``， 必须添加``_cache_{name}``作为一个slot. 或者可以
    添加 ``__dict__``,但通常不是一个理想的做法。
    """

    def __init__(
        self,
        fget: t.Callable[[t.Any], _T],
        name: str | None = None,
        doc: str | None = None,
    ) -> None:
        super().__init__(fget, doc=doc)
        self.__name__ = name or fget.__name__
        self.solt_name = f"_cache_{self.__name__}"
        self.__module__ = fget.__module__
    
    def __set__(self, obj: object, value: _T) -> None:
        if hasattr(obj, "__dict__"):
            obj.__dict__[self.__name__] = value
        else:
            setattr(obj, self.solt_name, value)
    
    def __get__(self, obj: object, type: type = None) -> _T: #type: ignore
        if obj is None: return self #type: ignore

        obj_dict = getattr(obj, "__dict__", None)

        if obj_dict is not None:
            value: _T = obj_dict.get(self.__name__, _missing)
        else:
            value = getattr(obj, self.solt_name, _missing) # type: ignore[arg-type]

        if value is _missing:
            value = self.fget(obj) # type: ignore

            if obj_dict is not None:
                obj.__dict__[self.__name__] = value
            else:
                setattr(obj, self.solt_name, value)
        
        return value

    def __delete__(self, obj: object) -> None:
        if hasattr(obj, "__dict__"):
            del obj.__dict__[self.__name__]
        else:
            setattr(obj, self.solt_name, _missing)

class header_property(_DictAccessorProperty[_TAccessorValue]):
    """类似`environ_propertry`但是headers"""

    pass

_charset_mimetypes = {
    "application/ecamascript",
    "application/javascript",
    "application/sql",
    "application/xml",
    "application/xml-dtd",
    "application/xml-external-parsed-entity",
}

def get_content_type(mimetype: str, charset: str) -> str:
    """返回一个完整的content type字符串，包含charset。
    
    如果mimetype代表文本，charset参数会被添加，否则mimetype会被原样返回。

    :param mimetype: 要作为content type的mimetype。
    :param charset: 文本mimetype要添加的charset。
    :return: content type

    .. versionchanged:: 0.15
        任何以```+xml```结尾的mimetype都将被添加charset，而不仅仅是
        以```application/```开头的mimetype。已知的文本类型，如
        ```application/javascript```也会被添加charset。
    """
    if (
        mimetype.startswith("text/")
        or mimetype in _charset_mimetypes
        or mimetype.endswith("+xml")
    ):
        mimetype += f"; charset={charset}"


def redirect(
    location: str, code: int = 302, Response: type[Response] | None = None
) -> Response:
    """返回一个response对象（WSGI应用），如果调用，重定向到目标位置。支持的code包括
    301, 302, 303, 305, 307 和 308. 300不支持，因为不是一个真正的重定向，304则是因为
    它是针对带有一定义If-Modified-Since头的请求的答案
    
    :param localtion: response需要重定向到的位置
    :param code: 重定向状态码，默认302
    :param class Response: 实例化response时需要用到的Response类，默认为
        :class:`mywerkzeug.wrappers.Response`
    """
    if Response is None:
        from .wrappers import Response

    html_localtion = escape(location)
    response = Response( # type: ignore[misc]
        "<!doctype html>\n"
        "<html lang=end>\n"
        "<title>Redirecting...</title>\n"
        "<h1>Redirection...</h1>\n"
        "<p>You should be rediected automatically to the target URL: "
        f'<a href="{html_localtion}">{html_localtion}</a>. If not, click the link.\n',
        code,
        mimetype="text/html",
    )
    response.headers["Location"] = location
    return response

def send_file(
    path_or_file: os.PathLike[str] | str | t.IO[bytes],
    environ: WSGIEnvironment,
    mimetype: str | None = None,
    as_attachment: bool = False,
    download_name: str | None = None,
    conditional: bool = True,
    etag: bool | str = True,
    last_modified: datetime | int | float | None = None,
    max_age: None | (int | t.Callable[[str | None], int | None]) = None,
    use_x_sendfile: bool = False,
    response_class: type[Response] | None = None,
    _root_path: os.PathLike[str] | str | None = None,
) -> Response:
    """给客户端发送文件内容
    
    第一个参数可以是文件路径或者类文件对象. 更多情况下路径更优，因为Werkzeug可以管理文件并
    可以从路径中获取额外的信息，传递一个文件对象需要以二进制形式打开，当使用:class:`io.BytesIO`
    在内存中构建文件很有用

    永远不要传递一个用户提供的文件路径，路径假定被信任，因此用户可以构建一个路径来获取一个你不想
    提供的文件，使用:func:`send_from_directory`来安全的处理用户提供的路径

    如果WSGIserver 在``environ`` 设置了一个``file_wrapper``，会使用它，否则使用
    Werkzeug's 内置的装饰器。另外，如果HTTP server支持``X-Sendfile``，
    ``use_x_sendfile=True``会告诉服务器发送给定的路径，这比在Python里读取要高效

    :param path_or_file: 要发送的文件路径，如果给的相对路径，则相对于当前工作路径，另外，
        以二进制打开的文件对象，确保文件指针定位到数据开始
    :param environ: 当前请求的WSGI环境
    :param mimetype: 发送文件的MIME类型，如果没有提供，会从文件名称检测
    :param as_attachment: 告诉浏览器应该保存文件而不是展示它
    :param download_name: 浏览器保存时默认的文件名，默认为传递的文件名
    :param conditional: 启用基于请求头的条件和范围响应，需要传递一个文件路径和``environ``
    :param etag: 计算文件的ETag，需要传递文件路径，也可以使用字符串
    :param last_modified: 发送文件的上次修改时间（按秒），如果没有提供，会从文件路径检测
    :param max_age: 文件缓存的时间（按秒），如果设置，``Cache-Contorl``为``public``
        否则将使用``no-cache``选项，优先选择条件缓存
    :param use_x_sendfile: 设置``X-Sendfile``头使server高效地发送文件，需要HTTP server
        支持，需要传递文件路径
    :param response_class: 使用此类构建response。默认:class:`~werkzeug.wrappers.Response`
    :param _root_path: 仅内部使用，使用:func:`send_from_directory`安全地发送路径下的文件
    """
    if response_class is None:
        from .wrappers import Response

        response_class = Response
    
    path: str | None = None
    file: t.IO[bytes] | None = None
    size: int | None = None
    mtime: float | None = None
    headers = Headers()

    if isinstance(path_or_file, (os.PathLike, str)) or hasattr(
        path_or_file, "__fspath__"
    ):
        path_or_file = t.cast("t.Union[os.PathLike[str], str]", path_or_file)

        # Flask 会传递app.root_path, 使其send_file装饰器不需要处理路径
        if _root_path is not None:
            path = os.path.join(_root_path, path_or_file)
        else:
            path = os.path.abspath(path_or_file)
        
        stat = os.stat(path)
        size = stat.st_size
        mtime = stat.st_mtime
    else:
        file = path_or_file

    if download_name is None and path is not None:
        download_name = os.path.basename(path)

    if mimetype is None:
        if download_name is None:
            raise TypeError(
                "Unable to detect the MIME type because a file name is"
                " not available. Either set 'download_name', pass a"
                " path instead of a file, or set 'mimetype'."
            )
        
        mimetype, encoding = mimetypes.guess_type(download_name)

        if mimetype is None:
            mimetype = "application/octet-stream"

        # 不要发送文件的编码，会导致浏览器保存解压缩的tar.gz文件
        if encoding is not None and not as_attachment:
            headers.set("Content-Encoding", encoding)
    
    if download_name is not None:
        try:
            download_name.encode("ascii")
        except UnicodeEncodeError:
            simple = unicodedata.normalize("NFKD", download_name)
            simple = simple.encode("ascii", "ignore").decode("ascii")
            # safe = RFC 5987 attr-char
            quoted = quote(download_name, safe="!#$&+-.^_`|~")
            names = {"filename": simple, "filename*": f"UTF-8''{quoted}"}
        else:
            names = {"filename": download_name}

        value = "attachment" if as_attachment else "inline"
        headers.set("Content-Disposition", value, **names)
    elif as_attachment:
        raise TypeError(
            "No name provided for attachment. Either set"
            " 'download_name' or pass a path instead of a file."
        )

    if use_x_sendfile and path is not None:
        headers["X-Sendfile"] = path
        data = None
    else:
        if file is None:
            file = open(path, "rb") # type: ignore
        elif isinstance(file, io.BytesIO):
            size = file.getbuffer().nbytes
        elif isinstance(file, io.TextIOBase):
            raise ValueError("Files must be opened in binary mode or use BytesIO.")
        
        data = wrap_file(environ, file)

    rv = response_class(
        data, mimetype=mimetype, headers=headers, direct_passthrough=True
    )

    if size is not None:
        rv.content_length = size
    
    if last_modified is not None:
        rv.last_modified = last_modified # type: ignore
    elif mtime is not None:
        rv.last_modified = mtime # type: ignore

    rv.cache_control.no_cache = True

    # Flask 会传递app.root_path, 使其send_file装饰器不需要处理路径
    if callable(max_age):
        max_age = max_age(path)
    
    if max_age is not None:
        if max_age > 0:
            rv.cache_control.no_cache = None
            rv.cache_control.public = True
        
        rv.cache_control.max_age = max_age
        rv.expires = int(time() + max_age)

    if isinstance(etag, str):
        rv.set_etag(etag)
    elif etag and path is not None:
        check = adler32(path.encode()) &0xFFFFFFFF
        rv.set_etag(f"{mtime}-{size}-{check}")
    
    if conditional:
        try:
            rv = rv.make_conditional(environ, accept_ranges=True, complete_length=size)
        except ReqeustRangeNotSatisfiable:
            if file is not None:
                file.close()
            
            raise
        
        # 一些x-sendfile错误地实现忽略了304状态码并发送了文件
        if rv.status_code == 304:
            rv.headers.pop("x-sendfile", None)
    
    return rv
    

def send_from_directory(
    directory: os.PathLike[str] | str,
    path: os.PathLike[str] | str,
    environ: WSGIEnvironment,
    **kwargs: t.Any,
) -> Response:
    """使用:func:`send_file` 发送目录中的文件
    
    一个从目录中提供文件的安全方式，如静态文件或上传，使用:func:`~mywerkzeug.security.safe_join`
    来确保来自客户端的路径不是恶意提供的,来执行具体的路径之外

    如果最终的路径不指向存在的常规文件，返回404:exec:`~werkzeug.exceptions.NotFound`

    :param directory:``path``必须定位到的目录，必不能由客户端提供，否则不安全
    :param path: 发送文件的路径，与``directory``相关，由客户端提供的路径部分，为安全检查
    :param environ: 当前请求的WSGI环境
    :param kwargs: 传递给:func:`send_file`的参数
    """
    path_str = safe_join(os.fspath(directory), os.fspath(path))

    if path_str is None: raise NotFound()

    # Flask会传递 app.root_path,使其send_from_directory包装器不必处理路径
    if "_root_path" in kwargs:
        path_str = os.path.join(kwargs["_root_path"], path_str)
    
    if not os.path.isfile(path_str):
        raise NotFound()

    return send_file(path_str, environ, **kwargs)

